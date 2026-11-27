#!/usr/bin/env python3
"""申能 DWD 验证 SQL 模板生成器（编译 / 三层对账 / 三类抽样 / 缺失判定 / 双表血缘）。

只使用 Python 3.10+ 标准库；不连接数据库、不访问网络、不执行 SQL。

用法：
  python scripts/generate_validation_sql.py \
    --kind <compile|reconcile|sample|missing|blood|all> \
    [--spec <spec.json>] \
    [--target-table <schema.table>] \
    [--function-name <schema.f_name>] \
    [--key-cols ...] [--metric-cols ...] \
    [--grain day96|day|month] [--date-col target_date] \
    [--unit-col transactionunit] [--blood-batch <batch>] [--out <file.sql>]

退出码：0 = 成功；2 = 参数或写入错误。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


def _parse_col_list(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return []
    cols: list[str] = []
    for entry in raw_values:
        for piece in entry.split(","):
            cleaned = piece.strip()
            if cleaned and cleaned not in cols:
                cols.append(cleaned)
    return cols


def _split_schema_table(qualified: str) -> tuple[str, str]:
    if "." in qualified:
        schema, table = qualified.split(".", 1)
        return schema.strip().strip('"'), table.strip().strip('"')
    return "dwd", qualified.strip().strip('"')


def render_compile(target_table: str, function_name: str, grain: str) -> str:
    return f"""\
-- =====================================================================
-- [compile] 编译验证与函数头导出检查（仅离线生成模板，未连接数据库）
-- 目标表：{target_table} | 函数：{function_name} | 粒度：{grain}
-- 授权后在测试事务中执行，确认定义与 RETURNS integer 契约后必须 ROLLBACK。
-- =====================================================================
BEGIN;

-- 1. 在此处粘贴或 \\i 引入待验证的 CREATE OR REPLACE FUNCTION {function_name}(...)
--    （若只做只读复核，可跳过定义语句直接执行下方导出检查）

-- 2. 验证函数已编译且返回类型非 smallint（应为 integer）
SELECT
    p.oid::regprocedure AS func_signature
    , format_type(p.prorettype, NULL) AS return_type
    , CASE WHEN p.prosecdef THEN 'SECURITY DEFINER' ELSE 'SECURITY INVOKER' END AS security_mode
    , p.proconfig AS func_config
FROM
    pg_catalog.pg_proc AS p
WHERE
    p.oid = '{function_name}'::regprocedure;

-- 3. 验证函数体内部八字段头部可被 pg_get_functiondef 原样导出
SELECT pg_catalog.pg_get_functiondef('{function_name}'::regprocedure) AS exported_ddl;

ROLLBACK;
"""


def render_reconcile(
    target_table: str,
    function_name: str,
    key_cols: list[str],
    metric_cols: list[str],
    grain: str,
    date_col: str,
) -> str:
    keys_csv = ", ".join(key_cols)
    t_key_select = "\n    , ".join(f"t.{k}" for k in key_cols)
    s_key_select = "\n    , ".join(f"s.{k}" for k in key_cols)
    join_on = "\n    AND ".join(f"t.{k} = s.{k}" for k in key_cols)
    key_out = "\n    , ".join(f"coalesce(t.{k}, s.{k}) AS {k}" for k in key_cols)

    sum_t = "\n    , ".join(f"sum(coalesce(t.{m}, 0)) AS {m}" for m in metric_cols)
    sum_s = "\n    , ".join(f"sum(coalesce(s.{m}, 0)) AS {m}" for m in metric_cols)
    layer1_diff = "\n    , ".join(
        f"t.{m} AS tgt_{m}\n    , s.{m} AS src_{m}\n    , t.{m} - s.{m} AS diff_{m}"
        for m in metric_cols
    )
    diff_pred = "\n    OR ".join(
        f"abs(coalesce(t.{m}, 0) - coalesce(s.{m}, 0)) > 1e-6" for m in metric_cols
    )

    d96_block = ""
    if grain == "day96":
        d96_sum_t = "\n    , ".join(f"sum(coalesce(t.{m}, 0)) AS tgt_{m}" for m in metric_cols)
        d96_sum_s = "\n    , ".join(f"sum(coalesce(s.{m}, 0)) AS src_{m}" for m in metric_cols)
        d96_pred = "\n    OR ".join(
            f"abs(coalesce(t.tgt_{m}, 0) - coalesce(s.src_{m}, 0)) > 1e-6"
            for m in metric_cols
        )
        non_tp_keys = [k for k in key_cols if k != "timeperiod"]
        unit_group_cols = ", ".join(non_tp_keys) if non_tp_keys else date_col
        d96_block = f"""\
-- 4. 24→96 日合计守恒检查（预期 0 行；差 4 倍说明 /4.0 用错或漏用）
WITH tgt_daily AS (
    SELECT
        {date_col}
        , {d96_sum_t}
    FROM
        {target_table}
    WHERE
        {date_col} BETWEEN :'start_date' AND :'end_date'
    GROUP BY
        {date_col}
)
, src_daily AS (
    -- 请替换为与 {function_name} 24点源同口径的日合计查询
    SELECT
        s.{date_col}
        , {d96_sum_s}
    FROM
        <source_base_cte_or_table> AS s
    WHERE
        s.{date_col} BETWEEN :'start_date' AND :'end_date'
    GROUP BY
        s.{date_col}
)
SELECT
    coalesce(t.{date_col}, s.{date_col}) AS {date_col}
    , '24->96_DAILY_SUM_MISMATCH' AS check_tag
FROM
    tgt_daily AS t
FULL OUTER JOIN
    src_daily AS s
    ON t.{date_col} = s.{date_col}
WHERE
    t.{date_col} IS NULL
    OR s.{date_col} IS NULL
    OR {d96_pred};

-- 5. 96 点时段完整性检查（每个应有主体×日期恰有 96 个不重复合法时段，预期 0 行）
SELECT
    {unit_group_cols}
    , count(*) AS row_cnt
    , count(DISTINCT timeperiod) AS distinct_tp_cnt
FROM
    {target_table}
WHERE
    {date_col} BETWEEN :'start_date' AND :'end_date'
GROUP BY
    {unit_group_cols}
HAVING
    count(*) <> 96
    OR count(DISTINCT timeperiod) <> 96;
"""

    return f"""\
-- =====================================================================
-- [reconcile] 源目标三层对账模板（总量 → 分日/分月 → 分主体，容差 1e-6）
-- 目标表：{target_table} | 对应函数：{function_name} | 粒度：{grain}
-- 提醒：对账前先比对 pg_get_functiondef('{function_name}'::regprocedure) 与本地脚本；
--       源侧过滤条件、deleted = 0 与 24→96 /4.0 换算必须与函数当前版本完全一致。
-- =====================================================================

-- 0. 目标表业务键重复检查（期望 0 行）
SELECT
    {keys_csv}
    , count(*) AS dup_cnt
FROM
    {target_table}
WHERE
    {date_col} BETWEEN :'start_date' AND :'end_date'
GROUP BY
    {keys_csv}
HAVING
    count(*) > 1;

-- 1. 第一层：总量对账
WITH tgt_total AS (
    SELECT
        count(*) AS row_cnt
        , {sum_t}
    FROM
        {target_table}
    WHERE
        {date_col} BETWEEN :'start_date' AND :'end_date'
)
, src_total AS (
    -- 请替换为与 {function_name} 同口径的目标粒度源查询
    SELECT
        count(*) AS row_cnt
        , {sum_s}
    FROM
        <source_aligned_to_target_grain> AS s
    WHERE
        s.{date_col} BETWEEN :'start_date' AND :'end_date'
)
SELECT
    t.row_cnt AS tgt_rows
    , s.row_cnt AS src_rows
    , {layer1_diff}
FROM
    tgt_total AS t
CROSS JOIN
    src_total AS s
WHERE
    t.row_cnt <> s.row_cnt
    OR {diff_pred};

-- 2. 第二层：分期对账（按 {date_col} FULL OUTER JOIN，期望 0 行）
WITH tgt_period AS (
    SELECT
        {date_col}
        , count(*) AS row_cnt
        , {sum_t}
    FROM
        {target_table}
    WHERE
        {date_col} BETWEEN :'start_date' AND :'end_date'
    GROUP BY
        {date_col}
)
, src_period AS (
    SELECT
        s.{date_col}
        , count(*) AS row_cnt
        , {sum_s}
    FROM
        <source_aligned_to_target_grain> AS s
    WHERE
        s.{date_col} BETWEEN :'start_date' AND :'end_date'
    GROUP BY
        s.{date_col}
)
SELECT
    coalesce(t.{date_col}, s.{date_col}) AS {date_col}
    , t.row_cnt AS tgt_rows
    , s.row_cnt AS src_rows
FROM
    tgt_period AS t
FULL OUTER JOIN
    src_period AS s
    ON t.{date_col} = s.{date_col}
WHERE
    t.{date_col} IS NULL
    OR s.{date_col} IS NULL
    OR t.row_cnt <> s.row_cnt
    OR {diff_pred};

-- 3. 第三层：分主体 / 业务键双向差集（期望 0 行）
WITH tgt_key AS (
    SELECT
        {t_key_select}
        , {sum_t}
    FROM
        {target_table} AS t
    WHERE
        t.{date_col} BETWEEN :'start_date' AND :'end_date'
    GROUP BY
        {keys_csv}
)
, src_key AS (
    SELECT
        {s_key_select}
        , {sum_s}
    FROM
        <source_aligned_to_target_grain> AS s
    WHERE
        s.{date_col} BETWEEN :'start_date' AND :'end_date'
    GROUP BY
        {keys_csv}
)
SELECT
    {key_out}
    , CASE
        WHEN t.{key_cols[0]} IS NULL THEN 'MISSING_IN_TARGET'
        WHEN s.{key_cols[0]} IS NULL THEN 'EXTRA_IN_TARGET'
        ELSE 'VALUE_DIFF_GT_1E6'
    END AS diff_type
FROM
    tgt_key AS t
FULL OUTER JOIN
    src_key AS s
    ON {join_on}
WHERE
    t.{key_cols[0]} IS NULL
    OR s.{key_cols[0]} IS NULL
    OR {diff_pred};

{d96_block}"""


def render_sample(
    target_table: str,
    function_name: str,
    grain: str,
    date_col: str,
    unit_col: str,
) -> str:
    if grain == "day96":
        exp1, exp2, exp3 = 96, 480, 960
    elif grain == "day":
        exp1, exp2, exp3 = 1, 5, 10
    else:
        exp1, exp2, exp3 = 1, 1, 2

    return f"""\
-- =====================================================================
-- [sample] 三类抽样校验模板（SOP §7.5；同一张表、同一套日期、同一 unit_A）
-- 目标表：{target_table} | 函数：{function_name} | 粒度：{grain}
-- 预期行数公式 = D * U * P * K；96点表三场景分别为 96 / 480 / 960。
-- 若任意前提不满足，必须标记 SAMPLE_NOT_READY，不得换样本后判定通过。
-- =====================================================================

-- 0. 样本前置就绪检查（unit_A 与 unit_B 必须在源与目标上月 1～5 日均有有效数据）
WITH readiness AS (
    SELECT
        (SELECT count(DISTINCT {date_col}) FROM {target_table}
         WHERE {unit_col} = :'unit_A' AND {date_col} BETWEEN :'d1' AND :'d5') AS tgt_unit_a_days
        , (SELECT count(DISTINCT {date_col}) FROM {target_table}
           WHERE {unit_col} = :'unit_B' AND {date_col} BETWEEN :'d1' AND :'d5') AS tgt_unit_b_days
        , (SELECT count(DISTINCT {date_col}) FROM <source_table>
           WHERE {unit_col} = :'unit_A' AND {date_col} BETWEEN :'d1' AND :'d5') AS src_unit_a_days
        , (SELECT count(DISTINCT {date_col}) FROM <source_table>
           WHERE {unit_col} = :'unit_B' AND {date_col} BETWEEN :'d1' AND :'d5') AS src_unit_b_days
)
SELECT
    r.*
    , CASE
        WHEN r.tgt_unit_a_days >= 5
         AND r.src_unit_a_days >= 5
         AND r.tgt_unit_b_days >= 5
         AND r.src_unit_b_days >= 5
        THEN 'READY'
        ELSE 'SAMPLE_NOT_READY'
    END AS sample_status
FROM
    readiness AS r;

-- 1. 场景一：单交易单元单日期（上月 1 日；96点预期总计 {exp1} 行）
SELECT
    {date_col}
    , {unit_col}
    , count(*) AS group_rows
    , {exp1} AS expected_total_rows
FROM
    {target_table}
WHERE
    {unit_col} = :'unit_A'
    AND {date_col} = :'d1'
GROUP BY
    {date_col}
    , {unit_col};

-- 2. 场景二：单交易单元多日期（上月 1～5 日；按日×单元分组核对行数，96点预期总计 {exp2} 行）
SELECT
    {date_col}
    , {unit_col}
    , count(*) AS group_rows
    , {exp2} AS expected_total_rows
FROM
    {target_table}
WHERE
    {unit_col} = :'unit_A'
    AND {date_col} BETWEEN :'d1' AND :'d5'
GROUP BY
    {date_col}
    , {unit_col}
ORDER BY
    {date_col};

-- 3. 场景三：多交易单元多日期（上月 1～5 日，unit_A + unit_B；按日×单元分组核对行数，96点预期总计 {exp3} 行）
SELECT
    {date_col}
    , {unit_col}
    , count(*) AS group_rows
    , {exp3} AS expected_total_rows
FROM
    {target_table}
WHERE
    {unit_col} IN (:'unit_A', :'unit_B')
    AND {date_col} BETWEEN :'d1' AND :'d5'
GROUP BY
    {date_col}
    , {unit_col}
ORDER BY
    {date_col}
    , {unit_col};
"""


def render_missing(
    target_table: str,
    metric_cols: list[str],
    grain: str,
    date_col: str,
) -> str:
    month_expr = (
        f"t.{date_col}" if grain == "month" else f"to_char(t.{date_col}, 'YYYY-MM')"
    )
    field_values = "\n        , ".join(f"('{m}', '<fill_mode>')" for m in metric_cols)
    unpivot_branches = "\n    UNION ALL\n    ".join(
        f"""SELECT
        {month_expr} AS ym
        , '{m}' AS field_name
        , t.{m}::text AS raw_val
        , (t.{m} = 0) AS is_zero
    FROM
        {target_table} AS t"""
        for m in metric_cols
    )

    return f"""\
-- =====================================================================
-- [missing] 字段缺失五态诊断模板（SOP §7.6）
-- 目标表：{target_table} | 粒度：{grain}
-- 缺失定义：NULL / 空串 / 纯空白；0 不算缺失。
-- 五种状态：NO_ROWS_IN_MONTH / ALL_NULL / PARTIAL_NULL / HARD_NULL_BY_DESIGN / FIELD_NOT_EXIST
-- 源表无数的月份通过 VALUES CROSS JOIN 保底输出一行，防止缺行误判为字段空。
-- =====================================================================
WITH expected_months(ym) AS (
    VALUES
        ('2026-01')
        , ('2026-02')
        , ('2026-03')
)
, target_fields(field_name, expected_fill_mode) AS (
    VALUES
        {field_values}
)
, existing_columns AS (
    SELECT
        column_name
    FROM
        information_schema.columns
    WHERE
        table_schema = '{_split_schema_table(target_table)[0]}'
        AND table_name = '{_split_schema_table(target_table)[1]}'
)
, unpivoted AS (
    {unpivot_branches}
)
, month_stats AS (
    SELECT
        ym
        , field_name
        , count(*) AS total_rows
        , count(*) FILTER (WHERE raw_val IS NULL OR btrim(raw_val) = '') AS missing_rows
        , count(*) FILTER (WHERE is_zero) AS zero_rows
    FROM
        unpivoted
    GROUP BY
        ym
        , field_name
)
SELECT
    m.ym
    , f.field_name
    , f.expected_fill_mode
    , coalesce(s.total_rows, 0) AS total_rows
    , coalesce(s.missing_rows, 0) AS missing_rows
    , coalesce(s.zero_rows, 0) AS zero_rows
    , CASE
        WHEN ec.column_name IS NULL THEN 'FIELD_NOT_EXIST'
        WHEN coalesce(s.total_rows, 0) = 0 THEN 'NO_ROWS_IN_MONTH'
        WHEN f.expected_fill_mode = 'HARD_NULL'
         AND s.missing_rows = s.total_rows THEN 'HARD_NULL_BY_DESIGN'
        WHEN s.missing_rows = s.total_rows THEN 'ALL_NULL'
        WHEN s.missing_rows > 0 THEN 'PARTIAL_NULL'
        ELSE 'OK'
    END AS missing_state
FROM
    expected_months AS m
CROSS JOIN
    target_fields AS f
LEFT JOIN
    existing_columns AS ec
    ON ec.column_name = f.field_name
LEFT JOIN
    month_stats AS s
    ON s.ym = m.ym
   AND s.field_name = f.field_name
ORDER BY
    m.ym
    , f.field_name;
"""


def _render_single_blood_checks(
    blood_table: str, schema: str, table: str, blood_batch: str
) -> str:
    return f"""\
-- --- {blood_table}：8 项登记后校验（除 ⑦ 外全部期望 0 行） ---
-- ① 字典字段在 DWD 表里存在
SELECT
    b.en_column
FROM
    {blood_table} AS b
WHERE
    b.table_name = '{table}'
    AND b.is_deleted = 0
    AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns AS c
        WHERE c.table_schema = '{schema}'
          AND c.table_name = '{table}'
          AND c.column_name = b.en_column
    );

-- ② cn_table_name 等于目标表 COMMENT ON TABLE 原文
SELECT
    b.table_name
    , b.cn_table_name
    , obj_description(format('%I.%I', '{schema}', '{table}')::regclass, 'pg_class') AS ddl_table_comment
FROM
    {blood_table} AS b
WHERE
    b.table_name = '{table}'
    AND b.is_deleted = 0
    AND coalesce(b.cn_table_name, '') <> coalesce(
        obj_description(format('%I.%I', '{schema}', '{table}')::regclass, 'pg_class'), ''
    );

-- ③ cn_column 等于目标列 COMMENT ON COLUMN 原文（不美化、不删科目编码）
SELECT
    b.en_column
    , b.cn_column
    , col_description(format('%I.%I', '{schema}', '{table}')::regclass, a.attnum) AS ddl_col_comment
FROM
    {blood_table} AS b
JOIN
    pg_catalog.pg_attribute AS a
    ON a.attrelid = format('%I.%I', '{schema}', '{table}')::regclass
   AND a.attname = b.en_column
   AND a.attnum > 0
   AND NOT a.attisdropped
WHERE
    b.table_name = '{table}'
    AND b.is_deleted = 0
    AND coalesce(b.cn_column, '') <> coalesce(
        col_description(format('%I.%I', '{schema}', '{table}')::regclass, a.attnum), ''
    );

-- ④ DWD 有业务列（排除技术基座列与 ext_1..ext_10）但该表未登记
SELECT
    c.column_name
FROM
    information_schema.columns AS c
WHERE
    c.table_schema = '{schema}'
    AND c.table_name = '{table}'
    AND c.column_name NOT IN (
        'id', 'province', 'company', 'transactionunit',
        'target_date', 'target_yearmonth', 'timeperiod', 'updated_time'
    )
    AND c.column_name !~ '^ext_([1-9]|10)$'
    AND NOT EXISTS (
        SELECT 1
        FROM {blood_table} AS b
        WHERE b.table_name = '{table}'
          AND b.en_column = c.column_name
          AND b.is_deleted = 0
    );

-- ⑤ 同表同字段重复有效记录
SELECT
    b.table_name
    , b.en_column
    , count(*) AS active_cnt
FROM
    {blood_table} AS b
WHERE
    b.table_name = '{table}'
    AND b.is_deleted = 0
GROUP BY
    b.table_name
    , b.en_column
HAVING
    count(*) > 1;

-- ⑦ is_deleted 分布核对
SELECT
    b.is_deleted
    , count(*) AS row_cnt
FROM
    {blood_table} AS b
WHERE
    b.table_name = '{table}'
GROUP BY
    b.is_deleted;

-- ⑧ 本批新增行数核对（与变更单数量比对，批次：{blood_batch}）
SELECT
    count(*) AS batch_row_cnt
FROM
    {blood_table} AS b
WHERE
    b.table_name = '{table}'
    AND b.is_deleted = 0
    AND b.batch_no = '{blood_batch}';
"""


def render_blood(target_table: str, blood_batch: str) -> str:
    schema, table = _split_schema_table(target_table)
    return f"""\
-- =====================================================================
-- [blood] 双血缘表登记校验与精确回滚模板（SOP §8）
-- 目标表：{schema}.{table} | 批次：{blood_batch}
-- 说明：dim_dictionary_blood 与 dim_dictionary_blood2 id 空间独立，
--       必须按各自实际结构与业务键分别校验、成对配对与回滚。
-- =====================================================================

{_render_single_blood_checks("dim.dim_dictionary_blood", schema, table, blood_batch)}
{_render_single_blood_checks("dim.dim_dictionary_blood2", schema, table, blood_batch)}

-- ⑥ 两表按业务键成对校验（差异期望 0 行；按实际键列调整 JOIN 键）
WITH b1 AS (
    SELECT
        table_name
        , en_column
        , cn_column
    FROM
        dim.dim_dictionary_blood
    WHERE
        table_name = '{table}'
        AND is_deleted = 0
)
, b2 AS (
    SELECT
        table_name
        , en_column
        , cn_column
    FROM
        dim.dim_dictionary_blood2
    WHERE
        table_name = '{table}'
        AND is_deleted = 0
)
SELECT
    coalesce(b1.table_name, b2.table_name) AS table_name
    , coalesce(b1.en_column, b2.en_column) AS en_column
    , CASE
        WHEN b1.en_column IS NULL THEN 'ONLY_IN_BLOOD2'
        WHEN b2.en_column IS NULL THEN 'ONLY_IN_BLOOD1'
        ELSE 'CN_COLUMN_DIFF'
    END AS pair_diff
FROM
    b1
FULL OUTER JOIN
    b2
    ON b1.table_name = b2.table_name
   AND b1.en_column = b2.en_column
WHERE
    b1.en_column IS NULL
    OR b2.en_column IS NULL
    OR coalesce(b1.cn_column, '') <> coalesce(b2.cn_column, '');

-- --- 精确回滚模板（按批次或精确键集将 is_deleted 置 1，禁止照搬他省历史日期） ---
BEGIN;

UPDATE dim.dim_dictionary_blood
SET
    is_deleted = 1
    , updated_time = CURRENT_TIMESTAMP
WHERE
    table_name = '{table}'
    AND batch_no = '{blood_batch}'
    AND is_deleted = 0;

UPDATE dim.dim_dictionary_blood2
SET
    is_deleted = 1
    , updated_time = CURRENT_TIMESTAMP
WHERE
    table_name = '{table}'
    AND batch_no = '{blood_batch}'
    AND is_deleted = 0;

-- 核对两表受影响行数后手动 COMMIT；若存在异常则执行 ROLLBACK;
ROLLBACK;
"""


def generate_sql(
    *,
    kind: str,
    target_table: str,
    function_name: str,
    key_cols: list[str] | None = None,
    metric_cols: list[str] | None = None,
    grain: str | None = None,
    date_col: str | None = None,
    unit_col: str = "transactionunit",
    blood_batch: str = "<blood_batch>",
) -> str:
    _, tbl_short = _split_schema_table(target_table)
    eff_grain = grain
    if eff_grain is None:
        if tbl_short.endswith("_m"):
            eff_grain = "month"
        elif tbl_short.endswith("_d"):
            eff_grain = "day"
        else:
            eff_grain = "day96"

    eff_date_col = date_col
    if eff_date_col is None:
        eff_date_col = "target_yearmonth" if eff_grain == "month" else "target_date"

    eff_keys = key_cols if key_cols else [
        "province",
        "company",
        unit_col,
        eff_date_col,
        *(["timeperiod"] if eff_grain == "day96" else []),
    ]
    eff_metrics = metric_cols if metric_cols else [
        "settlement_energy",
        "settlement_price",
        "settlement_electricfee",
    ]

    parts: list[str] = []
    if kind in ("compile", "all"):
        parts.append(render_compile(target_table, function_name, eff_grain))
    if kind in ("reconcile", "all"):
        parts.append(
            render_reconcile(
                target_table,
                function_name,
                eff_keys,
                eff_metrics,
                eff_grain,
                eff_date_col,
            )
        )
    if kind in ("sample", "all"):
        parts.append(
            render_sample(
                target_table, function_name, eff_grain, eff_date_col, unit_col
            )
        )
    if kind in ("missing", "all"):
        parts.append(render_missing(target_table, eff_metrics, eff_grain, eff_date_col))
    if kind in ("blood", "all"):
        parts.append(render_blood(target_table, blood_batch))

    return "\n".join(part.rstrip("\n") for part in parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        description="离线生成申能 DWD 编译、对账、抽样、缺失诊断与双血缘校验 SQL 模板。"
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=("compile", "reconcile", "sample", "missing", "blood", "all"),
        help="生成模板类型：compile | reconcile | sample | missing | blood | all",
    )
    parser.add_argument(
        "--spec",
        default=None,
        help="可选：阶段 4→5 函数规格 JSON 路径，用于自动填充表名/函数名/业务键/量值列/粒度/批次",
    )
    parser.add_argument("--target-table", default=None, help="目标表全限定名（如 dwd.t_demo_d96）")
    parser.add_argument("--function-name", default=None, help="函数全限定名（如 dwd.f_demo_d96）")
    parser.add_argument("--key-cols", nargs="+", default=None, help="业务键列名（空格或逗号分隔）")
    parser.add_argument("--metric-cols", nargs="+", default=None, help="量值列名（空格或逗号分隔）")
    parser.add_argument(
        "--grain",
        choices=("day96", "day", "month"),
        default=None,
        help="目标粒度：day96 | day | month",
    )
    parser.add_argument("--date-col", default=None, help="日期/年月列名（默认 target_date 或 target_yearmonth）")
    parser.add_argument("--unit-col", default=None, help="交易单元列名（默认 transactionunit）")
    parser.add_argument("--blood-batch", default=None, help="血缘登记批次标识")
    parser.add_argument("--out", default=None, help="输出 SQL 文件路径（默认打印到 stdout）")
    args = parser.parse_args(argv)

    spec_data: dict = {}
    if args.spec:
        spec_path = pathlib.Path(args.spec)
        if not spec_path.is_file():
            print(f"读取 Spec 文件失败：文件不存在或不是常规文件：{spec_path}", file=sys.stderr)
            return 2
        try:
            loaded = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"读取或解析 Spec 文件失败：{exc}", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print("Spec 文件顶层必须是 JSON 对象", file=sys.stderr)
            return 2
        spec_data = loaded

    target_table = (args.target_table or spec_data.get("target_table") or "").strip()
    function_name = (args.function_name or spec_data.get("function_name") or "").strip()
    if not target_table or not function_name:
        print(
            "缺少 --target-table 或 --function-name（可通过参数传入或由 --spec 提供）",
            file=sys.stderr,
        )
        return 2

    spec_keys = spec_data.get("business_keys")
    spec_metrics = spec_data.get("metric_columns")
    key_cols = _parse_col_list(args.key_cols) or (
        [str(c).strip() for c in spec_keys if str(c).strip()]
        if isinstance(spec_keys, list)
        else []
    )
    metric_cols = _parse_col_list(args.metric_cols) or (
        [str(c).strip() for c in spec_metrics if str(c).strip()]
        if isinstance(spec_metrics, list)
        else []
    )
    grain = args.grain or spec_data.get("grain")
    date_col = args.date_col or spec_data.get("date_col")
    unit_col = args.unit_col or spec_data.get("unit_col") or "transactionunit"
    blood_batch = args.blood_batch or spec_data.get("blood_batch") or "<blood_batch>"

    sql_text = generate_sql(
        kind=args.kind,
        target_table=target_table,
        function_name=function_name,
        key_cols=key_cols,
        metric_cols=metric_cols,
        grain=grain,
        date_col=date_col,
        unit_col=unit_col,
        blood_batch=blood_batch,
    )

    if args.out:
        out_path = pathlib.Path(args.out)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(sql_text.encode("utf-8"))
        except OSError as exc:
            print(f"写入 SQL 文件失败：{exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(sql_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
