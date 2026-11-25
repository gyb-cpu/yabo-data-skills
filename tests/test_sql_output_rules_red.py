#!/usr/bin/env python3
"""RED 阶段测试：pg-function-craft 的 SQL 输出规则校验能力。

被测能力当前不存在，因此本文件所有用例都失败（预期，不要修掉失败）。

目标契约 —— skills/pg-function-craft/scripts/check_sql_output.py：

    python scripts/check_sql_output.py --json <file.sql>

    stdout（JSON）：
        {
          "ok": true | false,
          "database_connected": false,
          "violations": [
            {"rule": "F-12", "line": 12, "message": "..."}
          ]
        }

    退出码：0 = 无违规；1 = 有违规；2 = 用法或读取错误。

至少识别以下规则（编号沿用仓库既有规则，不自造）：
    F-06     关键字未大写            references/06-SQL排版规范.md §2.1
    F-12     前置逗号仓库出现尾逗号   references/06-SQL排版规范.md §3.2
    F-21     AS 函数体之后缺八字段头或头部位置错误    references/06-SQL排版规范.md §6.1
    STYLE-01 函数名未使用 f_ 前缀     references/04-固定风格.md §1
    PERF-29  过滤列被套 ::date        references/07-性能优化规则.md §4.7

约束：只使用 Python 标准库；不连接数据库、不访问网络、不执行 SQL。

运行：
    python tests/test_sql_output_rules_red.py -v
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "pg-function-craft"
CHECKER = SKILL_ROOT / "scripts" / "check_sql_output.py"

REQUIRED_RULES = ("F-06", "F-12", "F-21", "PERF-29", "STYLE-01")

# 故意写坏的样例：尾逗号、关键字小写、缺八字段头、列侧 ::date、函数名无 f_ 前缀。
BAD_SQL = """\
create or replace function demo.get_orders(p_id bigint)
returns bigint
language plpgsql
as $function$
begin
    select
        a.order_id,
        a.dt
    from demo.order_header as a
    where a.dt::date >= (select min(x.dt) from demo.order_header as x);
end;
$function$;
"""

# 符合 references/06、07 与固定风格的样例，用于证明校验器不是“永远报错”。
GOOD_SQL = """\
CREATE OR REPLACE FUNCTION demo.f_demo_orders(p_start date)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
/*****************************************************************
*name       : demo.f_demo_orders
*function   : 统计演示订单
*input      : p_start 起始日期
*output     : -1参数异常, >=0影响行数
*increment  : 不适用
*author     : <team>
*CreateDate : 2026-01-01
*UpdateDate : 2026-01-01
******************************************************************/

DECLARE
    v_cnt bigint := 0;
    v_max_dt date;

BEGIN
    -- 1. 主处理
    SELECT
        count(*)
        , max(a.dt)
    INTO
        v_cnt
        , v_max_dt
    FROM
        demo.order_header AS a
    WHERE
        a.dt >= p_start::date;

    RETURN v_cnt;
END;
$function$;
"""

# 规范 06 §1.5/§3 要求多行 CASE 与拆开的算术式展开；F-32 只对同层列表项生效，
# 不得因表达式内部续行缩进而误报，否则检查器会反向逼迫把代码压成难读的长行。
MULTILINE_EXPR_SQL = """\
CREATE OR REPLACE FUNCTION demo.f_demo_price(p_start date)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
/*****************************************************************
*name       : demo.f_demo_price
*function   : 演示跨行表达式
*input      : p_start 起始日期
*output     : -1参数异常, >=0影响行数
*increment  : 不适用
*author     : <team>
*CreateDate : 2026-01-01
*UpdateDate : 2026-01-01
******************************************************************/

DECLARE
    v_rows integer := 0;
BEGIN
    SELECT
        a.company
        , CASE
              WHEN coalesce(a.energy, 0) = 0 THEN 0
              ELSE a.amount / a.energy
          END AS price
        , (coalesce(a.energy, 0)
           - coalesce(a.other, 0))::numeric AS net_energy
    FROM
        demo.clearing AS a
    WHERE
        a.target_date >= p_start;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$function$;
"""

FORBIDDEN_IMPORTS = {
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pg8000",
    "sqlalchemy",
    "requests",
    "urllib",
    "http",
    "socket",
    "ftplib",
}


class SqlOutputRuleCheckerRedTest(unittest.TestCase):
    maxDiff = None

    _MISSING = (
        "RED：缺少 SQL 输出规则校验能力。未找到 "
        "skills/pg-function-craft/scripts/check_sql_output.py。\n"
        "现状：references/06-SQL排版规范.md 的 F-xx 与 "
        "references/07-性能优化规则.md 的 PERF-29 只能人工对照，"
        "没有可重复、可断言的机器校验入口；tests/README.md 也只是人工清单。\n"
        "期望：脚本以 --json 输出 violations（rule/line/message），"
        "并对尾逗号、关键字小写、缺八字段头、列侧 ::date、函数名缺 f_ 前缀分别报 "
        "F-12 / F-06 / F-21 / PERF-29 / STYLE-01。"
    )

    def _require_checker(self) -> pathlib.Path:
        if not CHECKER.is_file():
            self.fail(self._MISSING)
        return CHECKER

    def _run_checker(self, sql: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        checker = self._require_checker()
        with tempfile.TemporaryDirectory(prefix="pgfc-sqlout-") as tmp:
            sql_path = pathlib.Path(tmp) / "case.sql"
            # 用 bytes 写入，保证 LF，避免 Windows 默认换行干扰判定。
            sql_path.write_bytes(sql.encode("utf-8"))
            proc = subprocess.run(
                [sys.executable, str(checker), "--json", str(sql_path)],
                cwd=str(SKILL_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(
                "check_sql_output.py 未输出可解析的 JSON。\n"
                f"exit={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
            )
        self.assertIsInstance(payload, dict, msg=f"JSON 顶层应为对象：{payload!r}")
        return proc, payload

    def test_bad_sql_reports_each_required_rule(self):
        proc, payload = self._run_checker(BAD_SQL)
        self.assertEqual(
            proc.returncode,
            1,
            msg=(
                "含违规的 SQL 应以退出码 1 结束。\n"
                f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
            ),
        )
        self.assertFalse(payload.get("ok"), msg=f"ok 应为 false：{payload!r}")
        self.assertIs(
            payload.get("database_connected"),
            False,
            msg="校验器必须声明未连接数据库（database_connected=false）。",
        )
        violations = payload.get("violations")
        self.assertIsInstance(violations, list, msg=f"violations 应为列表：{payload!r}")
        reported = {item.get("rule") for item in violations if isinstance(item, dict)}
        missing = sorted(set(REQUIRED_RULES) - reported)
        self.assertEqual(
            missing,
            [],
            msg=(
                f"未报告必需规则 {missing}；实际报告 {sorted(r for r in reported if r)}。\n"
                "样例同时包含：尾逗号（F-12）、关键字小写（F-06）、缺八字段头（F-21）、"
                "列侧 a.dt::date（PERF-29）、函数名 demo.get_orders（STYLE-01）。"
            ),
        )
        line_total = len(BAD_SQL.splitlines())
        for item in violations:
            self.assertIsInstance(item.get("line"), int, msg=f"line 应为整数：{item!r}")
            self.assertTrue(
                1 <= item["line"] <= line_total,
                msg=f"line 越界：{item!r}（文件共 {line_total} 行）",
            )
            self.assertTrue(str(item.get("message", "")).strip(), msg=f"message 为空：{item!r}")

    def test_compliant_sql_reports_no_violations(self):
        proc, payload = self._run_checker(GOOD_SQL)
        self.assertEqual(
            proc.returncode,
            0,
            msg=(
                "符合固定风格的 SQL 应以退出码 0 结束，否则校验器只是无条件报错。\n"
                f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
            ),
        )
        self.assertTrue(payload.get("ok"), msg=f"ok 应为 true：{payload!r}")
        self.assertEqual(
            payload.get("violations"),
            [],
            msg=f"合规样例不应有违规：{payload.get('violations')!r}",
        )
        self.assertIs(payload.get("database_connected"), False)

    def test_checker_is_offline_and_stdlib_only(self):
        checker = self._require_checker()
        source = checker.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(checker))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        offenders = sorted(imported & FORBIDDEN_IMPORTS)
        self.assertEqual(
            offenders,
            [],
            msg=f"校验器不得引入数据库驱动或网络模块：{offenders}",
        )

    def test_multiline_expression_not_flagged_as_comma_misalignment(self):
        """跨行 CASE / 拆开的算术式不得被 F-32 误报。

        规范 06 要求这类表达式展开，检查器必须与规范一致；否则只能靠压行过关，
        与「函数体内一律展开」的规则直接冲突。
        """
        proc, payload = self._run_checker(MULTILINE_EXPR_SQL)
        rules = {item.get("rule") for item in payload.get("violations", [])}
        self.assertNotIn(
            "F-32",
            rules,
            msg=(
                "跨行表达式被误报 F-32。\n"
                f"violations={payload.get('violations')!r}"
            ),
        )
        self.assertTrue(
            payload.get("ok"),
            msg=f"合规的跨行表达式样例不应有违规：{payload.get('violations')!r}",
        )


if __name__ == "__main__":
    # Windows 控制台默认代码页会把中文断言消息输出成乱码。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
