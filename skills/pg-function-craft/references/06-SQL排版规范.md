# SQL 与 PL/pgSQL 排版规范

本文给出一套可直接执行的 PostgreSQL / PL/pgSQL 排版默认值，用于生成、改写与审查函数。
它只约束“文本长什么样”，不改变 SQL 语义，也不替代 schema、数据、执行计划或负载测试。

PostgreSQL 官方文档定义语法，不规定排版；下面的规则是工程约定，不是数据库强制要求。
社区风格指南（如公开的 SQL Style Guide）在逗号前后置、`AND` 缩进宽度等细节上
并不统一，本文取一套固定默认值，不追求与某一指南逐字一致。

## 0. 范围、等级与边界

### 0.1 适用范围

- 适用：手写的 `CREATE FUNCTION` / `CREATE PROCEDURE`（仅目标引擎支持时）、函数体内的 SQL 与
  PL/pgSQL、配套 DDL/DML 脚本。
- 部分适用：`pg_get_functiondef` 导出的文本。导出器会重建最外层 `CREATE` 头，并丢掉
  `GRANT`/`REVOKE`、`COMMENT`、属主与 ACL；导出头部的换行与美元标签是工具产物，不是个人排版，
  不得据此推断个人偏好。
- 不适用：数据库中的实际对象、权限、统计信息与执行计划；这些不是排版对象。
- 不适用：非 PostgreSQL / Greenplum 的引擎方言；跨引擎先读 §12。

### 0.2 规则等级

- `MUST`（必须）：违反即视为排版不合格，评审或 CI 应拦截。
- `SHOULD`（应当）：默认遵守；偏离时在 PR 或改动说明里写理由。
- `MAY`（可以）：团队可选，不构成缺陷。

规则编号 `F-xx` 供评审引用，例如“违反 F-13”。

### 0.3 与项目约定、工具默认值的关系

本文是 `normative` 默认值，不是对任何样例或个人的统计描述。本技能把前置逗号（`,col` 起行）、
4 空格缩进、`$function$` 与默认行宽 100 固定为仓库默认，以与 `README.md` 第 8 节的速查表
一致。跨项目或使用工具默认值时，尾逗号也可接受，但同一文件、同一仓库只能选一种。

速查与本文细则冲突时以本文为准；项目已有明确书面约定时，以项目约定为准，但不得低于本文的
`MUST` 项。不因本规范重排整个既有文件。

### 0.4 排版与业务优化的边界

排版只改空白、换行、大小写、逗号位置和注释位置。索引、连接方式、谓词位置、聚合、去重、
类型转换、时间窗与空值兜底都属于业务或性能决策，不能借“格式化”之名顺手改掉。完整对照见 §10。

## 1. 文件级约定

### 1.1 编码

- F-01 `MUST` 使用 UTF-8（无 BOM）。BOM 会让 `psql` 把首行当成非法 token；不要把 GBK/GB18030
  文件直接提交。
- 历史文件若是 GBK，先单独提交一次编码转换（`iconv -f GBK -t UTF-8`），再提交排版改动；两次
  改动不要混在同一个 diff 里。
- 中文只出现在注释、字符串字面量与 `COMMENT ON` 文本中；代码区（关键字、标识符、运算符、
  括号、逗号、分号）一律用 ASCII 半角字符。全角括号 `（`、全角逗号 `，`、全角分号 `；`
  不是 SQL 语法。

### 1.2 换行与文件尾

- F-02 `MUST` 使用 LF；文件以单个换行结束；不得混用 CRLF/LF。
- 仓库根放 `.gitattributes`，避免 Windows 提交时整文件换行变化：

```gitattributes
*.sql text eol=lf
```

- 编辑器把 `files.eol` 设为 `\n`；不要依赖 `core.autocrlf` 在提交时转换。

### 1.3 空白

- F-03 `MUST` 缩进 4 个空格；禁止 tab，包括字符串内部的 tab，避免日志与校验文本不稳定。
- 行尾不得有空白；文件开头不得有空行；连续空行最多 1 行。
- 不使用多空格做列对齐；参数、`SET`、`=` 均以单个空格分隔。例外只有两种：`CREATE TABLE`
  列定义需要纵向对齐且团队已统一（对应 pgFormatter 的 `--vertical-align`），以及 GP 存储参数
  `key=value`（见 §12）。

### 1.4 行宽

- F-04 `SHOULD` 代码行默认不超过 100 字符（`README.md` 第 8 节的 80–100 区间取上限）；宽表或
  长 `IN` 列表不超过 120。超过时按 §8 换行，不要靠缩小字体。
- 中文字符按 2 列宽估算，不要用“字符数”机械判断。注释行可放宽到 120。

### 1.5 语句与文件组织

- F-05 `MUST` 一条语句以 `;` 结束并单独成段；函数定义以 `$function$;` 结束。语句之间最多
  1 个空行。
- 新文件用小写 snake_case、`.sql` 后缀；不要用空格或中文文件名。历史 `_copyN` 副本不因本规范
  改名，改名会影响调用方。

## 2. 词法与大小写

### 2.1 关键字

- F-06 `MUST` SQL 保留字、子句关键字、布尔与空值字面量大写：`SELECT`、`FROM`、`WHERE`、
  `JOIN`、`ON`、`GROUP BY`、`ORDER BY`、`WITH`、`AS`、`AND`、`OR`、`NOT`、`NULL`、`TRUE`、
  `FALSE`、`CASE`、`WHEN`、`THEN`、`ELSE`、`END`。
- PL/pgSQL 关键字同样大写：`DECLARE`、`BEGIN`、`EXCEPTION`、`IF`、`ELSIF`、`LOOP`、`RETURN`、
  `RAISE`、`EXECUTE`、`PERFORM`、`GET DIAGNOSTICS`。
- 多词关键字作为一个整体：`GROUP BY`、`ORDER BY`、`LEFT JOIN`、`INNER JOIN`、`IS NULL`、
  `NOT IN`、`ON CONFLICT`（仅目标引擎支持时）。不要在词中间换行。

### 2.2 标识符

- F-07 `MUST` 未加引号的标识符（schema、表、列、别名、函数、参数、变量）用小写字母、数字、
  下划线；不要用驼峰。
- 加双引号的标识符保持原样，**不得**被格式化工具改写大小写；`"OrderID"` 与 `orderid` 是两个
  不同对象。
- 表别名短且语义化（`o`、`ol`、`src`），列别名写清业务含义；别名不要用 SQL 关键字。

### 2.3 类型与函数

- F-08 `MUST` 数据类型小写：`bigint`、`numeric(18,2)`、`date`、`timestamp`、`text`、`jsonb`。
  内置函数小写：`count`、`sum`、`coalesce`、`nullif`、`format`。
- `LANGUAGE` 是关键字，大写；语言名 `plpgsql` 小写：写作 `LANGUAGE plpgsql`；`SECURITY DEFINER` /
  `SECURITY INVOKER` 大写。整条子句都不是小写。
- 自定义函数名按 §2.2 小写；调用时函数名与 `(` 之间不加空格：`f_demo(...)`。

### 2.4 字面量

- F-09 `MUST` 字符串用单引号；需要转义时优先用 `E'...'` 或美元引用，不用反斜杠拼字符串。
- 日期/时间用类型化字面量：`date '2026-01-01'`、`timestamp '2026-01-01 00:00:00'`；不要用
  `to_date('...')` 包一层，除非业务确实需要格式解析。
- 数值不加千分位、不写多余前导零；布尔与空值用 `TRUE`、`FALSE`、`NULL`。

### 2.5 运算符与标点

- F-10 `MUST`
  - 二元运算符两侧各一个空格：`a = b`、`a >= b`、`a || b`、`a + b`。
  - `::` 两侧不加空格：`p_id::bigint`。
  - 逗号前不加空格，后加一个空格；`;` 前不加空格。
  - 函数调用与 `(` 之间不加空格：`sum(x)`；`IN (`、`VALUES (` 保留一个空格。
  - 一元负号与操作数相连：`-1`；`NOT` 后一个空格。
  - `count(*)`、`SELECT *` 中的 `*` 不拆行；乘法 `a * b` 两侧空格。

## 3. 缩进与子句布局

### 3.1 基本规则

- F-11 `MUST` 每级缩进 4 空格。子句关键字（`SELECT`、`FROM`、`WHERE`、`GROUP BY`、
  `ORDER BY`、`HAVING`、`LIMIT`、`UNION`）与语句起始同列；子句内容再缩进 4。
- 嵌套超过 4 级（16 空格）时，优先提取 CTE、子查询或临时表；不要用 2 空格“省地方”。
- 子查询、CTE、`CASE`、函数体的缩进各自独立计算，不继承父级的额外偏移。
- 函数体内一律展开；单行只用于函数体外的极简临时查询（整条 ≤ 100 字符、无 `JOIN`、无子查询）。

### 3.2 SELECT

- F-12 `MUST` `SELECT` 列表一项一行；列别名用 `AS`；最后一项不加逗号。

```sql
SELECT
    a.order_id
    , a.amount
    , sum(b.qty) AS total_qty
```

- 逗号约定：本技能默认前置逗号（`,col` 起行，第一项不带逗号），与
  `README.md` 第 8 节一致。若仓库选择尾逗号（`col,` 在行尾），必须全库统一，并在 `.sqlfluff`
  或评审规则中固定；同一文件不得混用。
- 前置逗号用于列/值列表（`SELECT`、`GROUP BY`、`ORDER BY`、`INSERT` 列清单、`VALUES`、
  `IN`）和函数参数；CTE 之间用 `),` 连接，因为逗号跟在 `)` 后，不是列表项。
- pgFormatter 用 `-b` 切到前置逗号；SQLFluff 按所装版本把逗号位置配置为 leading。不要只靠
  手工维持两种风格。
- 纯逗号位置调整不改变语义，但会产生大 diff；既有文件只改被触碰的块，不整文件重排。
  局部转换会让单个文件暂时混用两种逗号位置——这是允许的过渡状态，但同一提交内新增或被
  完整重写的文件必须统一；评审时按“文件级混用”而不是“仓库级混用”判定。
- `SELECT *` 不用于函数落表或对外结果；需要全部列时显式列出。这是稳定性要求，不是排版，
  见 §10。
- `DISTINCT` 与 `SELECT` 同行：`SELECT DISTINCT`。
- `SELECT ... INTO` 的 `INTO` 与 `SELECT` 同列；单目标写 `INTO v_cnt`，多目标或超宽时每个
  目标一行、缩进 4。

### 3.3 FROM、JOIN、ON

- F-13 `MUST`
  - `FROM` 单独一行，表引用缩进 4。
  - 每个 `JOIN` 单独一行，与第一个表引用同列；不要用逗号连接表。
  - 显式写 `INNER JOIN` / `LEFT JOIN` / `RIGHT JOIN` / `FULL JOIN`；`CROSS JOIN` 不需要 `ON`。
  - `ON` 相对 `JOIN` 缩进 4；多个条件每个一行，`AND` 与第一个条件同列。

```sql
FROM
    demo.order_header AS a
    INNER JOIN demo.order_line AS b
        ON b.order_id = a.order_id
        AND b.line_status = 1
```

- 外连接的过滤条件放在 `ON` 还是 `WHERE` 会改变结果；这是语义问题，不是排版。格式化工具不得
  移动谓词。

### 3.4 WHERE

- F-14 `MUST` `WHERE` 单独一行；每个谓词一行，`AND`/`OR` 写在行首，与第一个谓词同列；混合
  `AND`/`OR` 必须加括号，不依赖优先级。

```sql
WHERE
    a.biz_date >= p_start
    AND a.biz_date < p_end
    AND (a.status = 1 OR b.qty > 0)
```

- `BETWEEN ... AND ...` 尽量保持一行；这里的 `AND` 不是布尔连接符，不要被格式化工具拆错。
- 注释掉的谓词不要留在 `WHERE` 里“备用”；需要保留时写清原因和日期。

### 3.5 GROUP BY、HAVING、ORDER BY

- F-15 `MUST` 每个子句单独一行；列一项一行；最后一项不加逗号。
- 新代码写显式列名，不用序号（`GROUP BY 1, 2`）；序号在增删列时极易错位。
- `ORDER BY` 需要稳定结果时显式写 `NULLS FIRST/LAST` 和排序列。这是语义要求，不是排版。

```sql
GROUP BY
    a.order_id
    , a.amount
HAVING
    sum(b.qty) > 0
ORDER BY
    a.order_id
    , a.amount DESC
```

### 3.6 集合运算

- F-16 `MUST` `UNION` / `UNION ALL` / `INTERSECT` / `EXCEPT` 单独一行，与前后 `SELECT` 同列；
  每个分支按完整 `SELECT` 排版。
- `UNION` 去重，`UNION ALL` 不去重；这是语义与性能选择，不是排版，见 §10。

### 3.7 子查询

- F-17 `MUST`
  - `(` 留在上一行行尾，子查询内容缩进 4，`)` 单独一行并与开启它的表达式同列。
  - 相关子查询与外层查询的别名不要同名；别名重复会让阅读和改写都出错。

```sql
WHERE
    a.order_id IN (
        SELECT
            b.order_id
        FROM
            demo.order_line AS b
        WHERE
            b.qty > 0
    )
```

- 能否把子查询改成 `JOIN` 是业务/性能决策，不是排版；改写前按 `05-重写协议.md` 验证行数与
  重复行。

### 3.8 DML

- F-18 `MUST` `INSERT` / `UPDATE` / `DELETE` 的子句各自成行；列清单一项一行；`VALUES` 每行
  一组。

```sql
INSERT INTO demo.t_demo (
    id
    , dt
)
VALUES
    (1, date '2026-01-01')
    , (2, date '2026-01-02');

UPDATE demo.t_demo AS t
SET
    amount = t.amount + 1
    , updated_at = now()
WHERE
    t.id = p_id;

DELETE FROM demo.t_demo AS t
WHERE
    t.dt < p_start;
```

- `INSERT ... SELECT` 的 `SELECT` 与 `INSERT` 同列，列清单与查询列按顺序对应；不要靠
  `SELECT *` 隐式对应。
- `DELETE` 必须带业务谓词；`TRUNCATE` 不是排版替代品（见 `01-基线规范.md`）。

## 4. CTE

- F-19 `MUST`
  - `WITH` 与主语句同列；每个 CTE 一个块；CTE 名后 `AS (`，`(` 留在行尾。
  - CTE 体缩进 4；结束 `)` 与 `WITH`/CTE 名同列；多个 CTE 用 `),` 连接，最后一个 `)` 后
    空一行再写主查询（可选，但同一文件要一致）。
  - 递归 CTE 写 `WITH RECURSIVE`；`RECURSIVE` 大写。
  - 原生 PG 12+ 支持 `MATERIALIZED` / `NOT MATERIALIZED`；仅当目标显式声明为 GP 6.6 / PG 9.4 时
    不写该修饰符（GP 6.6 / PG 9.4 的 CTE 恒物化，不支持该语法）。

```sql
WITH base AS (
    SELECT
        a.order_id
        , a.amount
    FROM
        demo.order_header AS a
    WHERE
        a.biz_date >= p_start
),
agg AS (
    SELECT
        base.order_id
        , sum(base.amount) AS amount
    FROM
        base
    GROUP BY
        base.order_id
)
SELECT
    agg.order_id
    , agg.amount
FROM
    agg;
```

- CTE 之间的逗号固定在 `)` 后（`),`），不适用列表的前置逗号约定；前置逗号只用于列/值列表
  和函数参数。若工具把 CTE 逗号移到下一行行首，属等价排版，选一种并全文件统一。
- 把长查询拆成 CTE 是**结构变更**：CTE 可能改变优化器行为（PG 12+ 对单次引用的非递归 CTE 默认内联，而 GP 6.6 与 PG 9.4 恒物化）。不要以
  “排版”为名拆 CTE；拆之前按 §10 和 `05-重写协议.md` 评估。

## 5. CASE

- F-20 `MUST`
  - 多分支或总宽超过行宽时，`CASE` 单独一行；`WHEN` 缩进 4；`THEN` 与 `WHEN` 同行；
    `ELSE` 与 `WHEN` 同列；`END` 与 `CASE` 同列。
  - 单分支且短可写一行：`CASE WHEN a.status = 1 THEN 'on' ELSE 'off' END AS flag`；超过
    100 字符必须展开。
  - `THEN` 后的结果过长时，在 `THEN` 后换行并再缩进 4；不要把所有 `THEN` 结果对齐成一列。
  - PL/pgSQL 的 `CASE` **语句**以 `END CASE;` 结束；SQL 的 `CASE` **表达式**以 `END` 结束，
    可带 `AS` 别名。两者不要混。

```sql
CASE
    WHEN a.status = 1 THEN 'active'
    WHEN a.status = 2 THEN 'inactive'
    ELSE 'unknown'
END AS status_desc
```

## 6. 函数头与函数体

### 6.1 头部注释块

- F-21 `MUST` 头部块放在 `AS $function$` 之后、`DECLARE` 或 `BEGIN` 之前，使用独立的
  `/***** ... *****/` 块注释。只写在 `CREATE` 之前的普通注释不算合格：`pg_get_functiondef`
  不会保留它，部署后无法从 `prosrc` 导出。
- 必需字段及顺序固定为：`*name`、`*function`、`*input`、`*output`、`*increment`、`*author`、
  `*CreateDate`、`*UpdateDate`。字段名称和冒号前的对齐风格保持不变。
- F-36 `MUST` `*name` 使用 schema 全限定名，并与实际 `CREATE FUNCTION` 名称一致。
- F-37 `MUST` `*input` 包含全部 `p_` 参数名并解释业务含义；不能只写类型。
- F-38 `MUST` `*output` 与代码实际返回行为一致；返回影响行数时写
  `-1参数异常, >=0影响行数`，不能写 `0正常`。
- F-39 `MUST` 使用 `update_time`、`v_changed_dates` 或 `v_changed_months` 的增量函数必须说明
  水位线、回看窗口和半开区间；非增量函数写 `不适用`。
- F-40 `MUST` `*CreateDate` 使用 `YYYY-MM-DD`；`*UpdateDate` 使用 `YYYY-MM-DD`，修改已有函数时可在同一行用逗号追加日期（`YYYY-MM-DD, YYYY-MM-DD`）或追加新的 `*UpdateDate` 行，不覆盖历史修改日期。
- F-41 `MUST` 函数头必须有 `/*****` 起始分隔线和 `*****/` 结束分隔线。
- `*author` 写项目允许的署名或明确占位符；不得把真实人名、手机号、
  邮箱、内网地址、账号、连接串写进注释。
- 头部块不参与自动换行；不要让 `pgFormatter -C` 或任何 formatter 重排它。

### 6.2 CREATE 头

- F-22 `MUST`
  - `CREATE OR REPLACE FUNCTION` 一行；函数名与 `(` 之间不留空格。
  - 导出件保留 `"schema"."f_name"("p_flag" int4, ...)` 的引号标识符与 `int4`/`varchar`/`int2`
    类型拼写，不改写为 `smallint`/`character varying`。
  - **不增删前导子句**：原函数有 `LANGUAGE` 就保留，没有也不补充；`RETURNS` / `LANGUAGE` / `AS`
    的行序保持原样。`LANGUAGE` 在 PostgreSQL 里是必需子句，删掉会导致 `no language specified`，
    所以“看着多余”也不能删。
  - 参数不超过 2 个且整行不超过 100 字符时可写单行；否则每个参数一行，缩进 4，逗号前置；
    最后一个参数不带逗号。
  - `RETURNS`、`LANGUAGE`、`SECURITY`、`SET`、`AS` 各占一行；建议顺序
    `LANGUAGE` → `SECURITY` → `SET` → `AS`，既有文件不因顺序差异重排。
  - `RETURNS TABLE (...)` 的列定义一项一行。

```sql
CREATE OR REPLACE FUNCTION demo.f_demo(p_id bigint, p_from date)
RETURNS bigint
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
/*****************************************************************
*name       : demo.f_demo
*function   : 演示函数
*input      : p_id 主键, p_from 起始日期
*output     : -1参数异常, 0正常
*increment  : 不适用
*author     : <team>
*CreateDate : 2026-01-01
*UpdateDate : 2026-01-01
******************************************************************/

DECLARE
    v_cnt bigint := 0;
BEGIN
    RETURN 0;
END;
$function$;
```

- 函数属性（`COST`、`ROWS`、`PARALLEL`、`STRICT`）各占一行，写在 `AS` 之前；不要为了“紧凑”
  塞回一行。
- `SECURITY DEFINER` 必须同时固定 `search_path`：`SET search_path = pg_catalog, <trusted_schema>, pg_temp`
  （`pg_temp` 放最后），或 `SET search_path = ''` + 全限定对象，二选一。这是安全要求，不是排版；
  见 `01-基线规范.md`。

### 6.3 DECLARE

- F-23 `MUST` `DECLARE` 顶格（相对函数体）；每个变量一行，缩进 4；`类型 := 初值` 用单个空格。
  `DECLARE` 块与 `BEGIN` 之间留 1 个空行（新代码；既有文件不要为这一条单独补空行）；
  没有声明时不要写空的 `DECLARE`。
- 变量、参数、游标的命名遵循项目既有约定（如有书面风格说明则以它为准）；无项目约定时按
  `04-固定风格.md` STYLE-01 的默认前缀。本文只规定声明行的排版，不重新定义命名。

```sql
DECLARE
    v_cnt bigint := 0;
    v_sql text;
    v_row record;
```

### 6.4 BEGIN、控制结构与 END

- F-24 `MUST`
  - `BEGIN` 顶格；语句缩进 4；`END;` 顶格。
  - `IF` / `ELSIF` / `ELSE` / `END IF;` 按层级缩进；`THEN` 与条件同行；嵌套块再 +4。
  - `LOOP` / `FOR ... LOOP` / `WHILE ... LOOP` 与 `END LOOP;` 同列；循环体 +4。
  - `RETURN` 单独一行；不要写 `IF ... THEN RETURN ...; END IF;` 在同一行。

```sql
BEGIN
    IF p_id IS NULL THEN
        RETURN 0;
    END IF;

    FOR v_row IN
        SELECT
            t.id
        FROM
            demo.t_demo AS t
        WHERE
            t.dt >= p_from
    LOOP
        PERFORM demo.f_touch(v_row.id);
    END LOOP;

    RETURN 1;
END;
```

### 6.5 EXCEPTION

- F-25 `MUST`
  - `EXCEPTION` 与 `BEGIN` 同列；`WHEN` 缩进 4；handler 语句缩进 8；多个 `WHEN` 之间不空行，
    或统一一个空行；`BEGIN` 块与 `EXCEPTION` 之间留 1 个空行（新代码；既有文件不单独补）。
  - 只捕获明确的条件；`WHEN OTHERS` 只用于兜底重抛，handler 内必须 `RAISE;` 或带 `ERRCODE`
    重抛（见 `01-基线规范.md`）。
  - 不要用 `WHEN OTHERS THEN NULL`；这是反模式，不是排版。

```sql
EXCEPTION
    WHEN unique_violation THEN
        RAISE;
    WHEN OTHERS THEN
        RAISE;
END;
```

- `GET STACKED DIAGNOSTICS` 每条赋值一行；变量对齐可选，默认单空格。

### 6.6 美元引用

- F-26 `MUST` 新代码的函数体默认用 `$function$`。从 `pg_get_functiondef` 导出的既有函数常见
  `$BODY$`，**保留原标签**，不要为统一而改；同一对象内成对即可。不要混用 `$$`，迁移时单独批准。
  过程（PG 11+，默认 PG 12+ 基线可用）可用 `$procedure$` 区分。
- 函数体内出现与正文冲突的同名标签（例如动态 SQL 里再用 `$function$`）时，改用 `$fn$` 或
  `$sql$`，并保持同一函数内标签成对、大小写一致。
- `AS $function$` 与结尾 `$function$;` 顶格。导出文本的标签不作为个人风格证据：换库或换
  工具时不要因为标签不同就重排整个函数。

## 7. 动态 SQL

- F-27 `MUST` 值用 `EXECUTE ... USING` 绑定；标识符用 `format('%I', ...)` 或白名单；不得把值
  拼进字符串（安全底线，见 `01-基线规范.md`）。
- F-28 `MUST` `format()` 的参数多于 2 个或整行超宽时，每个参数一行，`)` 与 `format` 所在行
  同列；`USING` 与 `EXECUTE` 同行（短）或缩进 4（长）。

```sql
v_sql := format(
    $sql$
    INSERT INTO %I.%I (id, dt)
    SELECT
        id
        , dt
    FROM
        %I.%I
    WHERE
        dt >= $1
    $sql$
    , v_schema
    , v_table
    , v_schema
    , v_stage
);
EXECUTE v_sql USING p_start;
```

- 动态 SQL 字符串内部不要使用 `--` 行注释；拼接或换行会把后续内容注释掉。需要注释时用
  `/* ... */`，或干脆不写。
- 不要对动态 SQL 文本做“美化”后不验证：文本会进入日志、审计、缓存键或下游解析器，空白变化
  可能影响文本匹配。格式化前后保留一份生成文本用于对比。
- 若日志或校验依赖生成文本，固定字符串内部的缩进，不随意改。

## 8. 长表达式与换行

- F-29 `MUST`
  - 布尔表达式在 `AND` / `OR` 前换行，运算符留在行首；续行缩进 4。
  - 算术/字符串表达式在运算符前换行（`+`、`-`、`||`），续行缩进 4；括号内的表达式再 +4。
  - 函数参数超过 3 个或超宽时，每个参数一行，`)` 与函数名所在行同列；不要悬挂缩进到参数中间。
  - `IN (...)` 列表超过 5 项或超宽时，每项一行，`)` 单独一行；最后一项不加逗号。
  - 不得在字符串字面量、双引号标识符、美元引用内部换行；不得拆开 `::type`、
    `AT TIME ZONE`、`INTERVAL '...'`、`BETWEEN ... AND ...`。

```sql
WHERE
    (
        a.status = 1
        OR a.status = 2
    )
    AND (
        b.qty > 0
        OR b.qty IS NULL
    )
```

- 超过 3 层括号或 4 级缩进时，先提取 CTE/子查询；不要用换行把复杂度藏起来。
- 不要为了对齐 `THEN`/`ELSE` 结果插入多个空格；对齐会在字段名变化时产生噪声 diff。

## 9. 注释

- F-30 `MUST`
  - 函数头按 `F-21` 放置在 `AS $function$`（或导出件 `AS $BODY$`）之后、`DECLARE`/`BEGIN` 之前，
    使用独立的 `/***** ... *****/` 八字段块注释；`README.md` 速查表与本规范一致，不再使用
    仅写在 `CREATE` 之前的 `--` 行块头。
  - 段注释 `-- 1. 说明` 与当前语句同列；行尾注释与代码之间至少 2 个空格，`--` 后 1 个空格。
  - 普通多行说明用 `/* ... */`，每行以 ` * ` 对齐；函数体内八字段头按模板，不强制 ` * ` 对齐；
    不要嵌套块注释。
  - 中文注释用中文标点；代码区仍用半角。注释里的示例 SQL 也按本规范排版。
- F-32 `MUST` 前置逗号的续行必须与首项同列，不得与子句关键字同列。
  - `SELECT` / `GROUP BY` / `ORDER BY` / `INSERT INTO ... (` 之后，首项与后续 `,项` 都缩进
    子句 +4；不要出现“首项 8 格、逗号项 4 格”的锯齿。
  - 每个列表项一行；`GROUP BY` 也写成关键字独占一行，与 `SELECT` 保持一致。

- F-33 `SHOULD` 空行收敛：段与段之间最多 1 个空行，连续空行压成 1 个；函数体内不得出现
  3 个及以上连续空行；文件首尾不留空行，文件尾单个换行。

- F-34 `MUST` 空行与空注释不得切断列表：`SELECT` / `INSERT` 列清单 / `GROUP BY` 等列表项之间，
  不得插入空行，也不得插入只有 `--` 的行。分组需要视觉分隔时，写有内容的注释（如 `-- 省间`），
  不要留空行。

- F-35 `MUST` 分号跟在最后一行代码末尾，不单独成行。`CREATE TEMPORARY TABLE ... AS SELECT ...;`
  与 `INSERT ... SELECT ... FROM x;` 的分号都贴在最后一行语句上。

- F-31 `MUST`
  - 不得用 formatter 重排 `--` 行注释；合并两行会把第二行代码变成注释。
  - 不得在注释中写真实人名、手机号、邮箱、内网 IP/主机名、账号、密码、连接串、密钥；用
    `<owner>`、`<host>`、`***` 占位。
  - 不保留大段注释掉的代码；确需保留时写明原因、日期和恢复条件，并在评审中确认。
  - `RAISE NOTICE/INFO` 是运行时输出，不是注释；生产路径控制级别，避免打印敏感值。

## 10. 排版与业务优化的边界

先判断改动是否只影响文本。只有空白、换行、大小写、逗号位置、注释位置变化，且忽略空白与
大小写后 token 序列不变，才算纯排版。

| 操作 | 归类 | 说明 |
|---|---|---|
| 调整缩进、换行、关键字大小写、逗号位置 | 排版 | 语义不变，可工具化 |
| 增加不改变分组的括号 | 排版/可读性 | 可工具化；删除括号要逐处复核 |
| 重排 `--` 注释、合并注释行 | 危险，非纯排版 | 可能把后续代码注释掉 |
| 重排动态 SQL 字符串 | 非纯排版 | 日志、审计、缓存键或下游文本匹配可能变化 |
| `DELETE` 谓词从日期切片改成整表 | 业务/正确性 | 删除范围变化 |
| `LEFT JOIN` 改 `INNER JOIN` | 业务 | 结果集变化 |
| 谓词从 `ON` 移到 `WHERE` | 业务 | 外连接语义变化 |
| `UNION` 改 `UNION ALL` | 业务/性能 | 去重语义变化 |
| 加索引、改 JOIN 顺序、加 `WHERE`、加 `LIMIT` | 性能/业务 | 需要 schema、数据与执行计划 |
| 子查询改 CTE 或 JOIN | 结构/性能 | 可能改变计划与重复行 |
| 展开 `SELECT *` | 稳定性/正确性 | 列依赖与列序变化 |
| 加/去 `NULLS LAST`、`coalesce` 默认值 | 业务 | 排序与 NULL 语义变化 |
| `date` 改 `timestamp`、改时间窗 | 业务 | 边界、时区与重跑确定性变化 |

判定方法：先看 `git diff -w`，再人工确认 token、括号分组、谓词位置、连接类型、类型转换、
排序稳定性没有变化。任何一项变了，就按行为变更走 `05-重写协议.md`，不能只给“格式更漂亮”
的说明。

## 11. 工具：用途与局限

pgFormatter、SQLFluff、sql-formatter 都是文本工具，不是数据库客户端。它们默认不读取数据库
统计信息，也不执行 SQL、不生成执行计划。工具运行成功只说明文本被解析或重排，**不证明**业务
正确、权限安全、结果一致或性能更好。

| 工具 | 定位 | 适合 | 不适合/局限 |
|---|---|---|---|
| pgFormatter（`pg_format`） | Perl 美化器 | 单文件 SQL/PLpgSQL 的空白、关键字/类型大小写、逗号、换行 | 启发式而非完整语义分析；动态 SQL、美元引用、GP 关键字可能误判；`-w` 会折行字符串常量；DML 中默认尝试删除冗余括号；`-n` 删注释 |
| SQLFluff | Python linter + fixer | 方言感知的规则检查与批量修复；支持 `postgres`、`greenplum` 方言；可进 CI | 过程体（`$function$...$function$` 内）的解析与规则覆盖取决于版本，可能不完整；GP 6.6 语法未必全覆盖；parse error 不等于 SQL 非法；fix 可能产生大 diff |
| sql-formatter | JS/TS pretty-printer | 临时查询、DDL/DML 片段的快速缩进 | 官方 README 声明不支持存储过程；没有 greenplum 方言；无 lint、无语义校验 |

### 11.1 pgFormatter

- 默认 4 空格、关键字大写、类型小写；显式写 `-s 4 -u 2 -U 1 -f 1`，不要依赖默认值随版本变化。
- `-e` 尾逗号是默认；`-b` / `--comma-start` 改为前置逗号。不同列表（参数、`SELECT`、
  `VALUES`、CTE）的处理可能不一致，输出要逐段复核；选一种，不要混用。
- `--no-space-function` 去掉函数名与 `(` 之间的空格，符合 F-10；`--redundant-parenthesis`
  保留括号，避免工具删掉有表达意图的括号。
- `-p` / `--placeholder` 保护 GP 专属子句、动态代码片段；`--extra-keyword` 补充 GP 关键字词表。
- `-w` / `--wrap-limit` 在达到长度时会折行**字符串常量**，可能改变动态 SQL 与字面量内容。
  含长字符串的文件不要启用，或先用 `-p` 保护。
- `-C` / `--wrap-comment` 会重排注释，可能破坏头部块与 `--` 边界；不要对函数头启用。
- `-n` / `--nocomment` 删除所有注释；不要对源文件使用。
- `-I` / `--ident-case` 改标识符大小写；引号标识符不会被改，但仍要复核。`-i` 原地改写只用于
  临时副本，不用于生产脚本或用户提供的只读样例。

### 11.2 SQLFluff

- 默认方言用 `postgres`；仅当目标显式声明为 GP 6.6 时切换为 `greenplum`，且不要假设它覆盖 GP 6.6 的全部
  语法。
- 固定版本与 `.sqlfluff` 配置，先 `sqlfluff lint` 再 `sqlfluff fix`；CI 只检查本次变更的文件，
  避免历史文件全量报错。
- 用 `sqlfluff parse` 确认函数体是否真的被解析。过程体解析不完整时，layout 规则可能没有进入
  `$function$ ... $function$` 内部；lint 通过不等于函数体已排版。
- parse error 可能只是方言未覆盖，不代表 SQL 非法；不要用忽略规则掩盖方言问题，先换 dialect
  或缩小检查范围。

### 11.3 sql-formatter

- 只支持查询与普通 DDL/DML 片段；官方 README 明确“不支持存储过程”，不要用它格式化函数文件。
- 没有 greenplum 方言；GP DDL 不要用它。
- 配置项包括 `language`、`tabWidth`、`keywordCase`、`linesBetweenQueries`；没有逗号前置选项，
  生成的是尾逗号。本仓库默认前置逗号，因此不要用它做最终排版，只用于临时查询。
- 它不做 lint，也不校验语义。

### 11.4 共同边界

- 工具可能改动括号、注释、字符串折行、美元标签与标识符大小写；这些都不在“纯排版”的自动
  信任范围内，必须逐项复核。
- 不要对用户提供的只读样例跑原地格式化：样例是证据，字节变化会让后续引用失效；
  需要试验时复制到临时目录。
- 不要把格式化通过当作正确性或性能证明；性能结论只能由用户在代表性数据与参数上执行
  `EXPLAIN (ANALYZE, BUFFERS)` 后得出，GP 还要按 slice/segment 解读；本技能不代跑。

### 11.5 最小配置与命令

`.sqlfluff`：

```ini
[sqlfluff]
dialect = postgres
templater = raw
max_line_length = 100

[sqlfluff:indentation]
indent_unit = space
tab_space_size = 4

[sqlfluff:layout:type:comma]
line_position = leading
```

- 目标显式声明为 Greenplum 6.6 时把 `dialect` 改为 `greenplum`。关键字大写与逗号位置的配置段名随版本变化，
  按所装版本的文档核对，不要盲目复制旧配置。

`.sql-formatter.json`（仅用于临时查询；不要用于函数文件或最终排版）：

```json
{
  "language": "postgresql",
  "tabWidth": 4,
  "keywordCase": "upper",
  "linesBetweenQueries": 1
}
```

pgFormatter（输出到新文件，不原地改）：

```bash
pg_format -s 4 -u 2 -f 1 -U 1 -b \
    --no-space-function --redundant-parenthesis \
    -o out.sql in.sql
```

- `-b` 生成前置逗号；需要尾逗号时去掉它。GP 关键字用 `--extra-keyword` 或 `-p` 保护。
- 不要加 `-w`，除非确认文件里没有会被折行的长字符串/动态 SQL。
- 本技能默认前置逗号。仓库书面约定用尾逗号时，检查器必须加 `--comma-style trailing`，
  否则 `F-12` 会误报（见 `tests/README.md` §8）。

## 12. Greenplum 6.6 兼容提醒（按需启用）

仅当目标显式声明为 GP 6.6 时适用，原生 PG 12+ 默认不启用以下降级约束：

- GP 6.6 核心基于 PostgreSQL 9.4。目标为 GP 6.6 时不要引入 PG 9.5+ 语法；**具体特性与最低版本只查
  `10-PLpgSQL语法与函数形态.md` §1.1**，本节不维护清单。格式化工具可能接受高版本语法，
  但 GP 目标库不会。
- GP 专属子句单独成行，按目标版本顺序保留：`DISTRIBUTED BY (...)`、`DISTRIBUTED RANDOMLY`、
  `PARTITION BY ...`、`WITH (appendonly=true, orientation=column)`。不要让工具把它们挪到
  `SELECT` 之后或删掉。

```sql
CREATE TABLE demo.t_demo (
    id bigint
    , dt date
)
WITH (appendonly=true, orientation=column)
DISTRIBUTED BY (id);
```

- 存储参数写 `key=value`，不加空格；这是 GP 习惯，也是与普通比较表达式区分的排版例外。
- 方言选择：SQLFluff 用 `greenplum`；pgFormatter 用 `--extra-keyword` / `-p` 保护 GP 关键字；
  sql-formatter 没有 greenplum 方言，不要用于 GP DDL。
- GP 6.6 的 CTE 恒物化；不要把“拆 CTE/合并 CTE”当排版。GP 7 基于 PG 12 且受 ORCA 影响，
  也不能把 GP 6.6 的结论直接套过去。
- `EXPLAIN` 输出是 slice/segment，不是社区 PG 的 plan 文本；格式化不改变计划，也不能用来
  证明性能。
- 从高版本 PG dump 出来的 DDL 可能含 GP 6.6 不支持的语法；先降级/改写，再排版。

## 13. before/after

以下示例只演示排版。谓词、连接类型、聚合与排序语义均未改变；`demo` 是占位 schema，
不包含真实表名、人名或连接信息。before 故意保留未排版状态，因此不遵守 100 字符行宽。

before：

```sql
with base as (select a.order_id,a.amount,b.qty from demo.order_header as a inner join demo.order_line as b on b.order_id=a.order_id where a.biz_date>=date '2026-01-01' and a.status in (1,2))
select order_id,sum(amount) as amount,case when sum(qty)>0 then 'ok' else 'empty' end as flag from base group by order_id order by amount desc;
```

after：

```sql
WITH base AS (
    SELECT
        a.order_id
        , a.amount
        , b.qty
    FROM
        demo.order_header AS a
        INNER JOIN demo.order_line AS b
            ON b.order_id = a.order_id
    WHERE
        a.biz_date >= date '2026-01-01'
        AND a.status IN (1, 2)
)
SELECT
    order_id
    , sum(amount) AS amount
    , CASE
        WHEN sum(qty) > 0 THEN 'ok'
        ELSE 'empty'
    END AS flag
FROM
    base
GROUP BY
    order_id
ORDER BY
    amount DESC;
```

改动仅包括：关键字大写、子句分行、4 空格缩进、`AS` 别名、逗号位置、`CASE` 展开。没有增加
索引、没有改连接类型、没有移动谓词、没有改 `NULL` 或排序语义。

## 14. 提交前检查清单

- [ ] F-01/F-02：UTF-8 无 BOM、LF、文件尾单换行。
- [ ] F-03：4 空格、无 tab、无行尾空白、最多 1 个连续空行。
- [ ] F-04：默认 100 字符（宽表 120）与中文宽度。
- [ ] F-06~F-10：关键字大写；标识符、类型、函数小写；引号标识符未变；运算符空格。
- [ ] F-12：前置逗号一致；函数参数、`IN` 列表、`VALUES` 未混用尾逗号。
- [ ] F-11、F-13~F-18：子句分行；`JOIN`/`ON`；`WHERE`；`GROUP BY`/`ORDER BY`；集合运算；
      子查询；DML。
- [ ] F-19：CTE 缩进、`),` 连接；仅当显式声明 GP 6.6 / PG 9.4 时未写 `MATERIALIZED`。
- [ ] F-20：`CASE` 的 `WHEN`/`ELSE`/`END`，以及 PL/pgSQL 的 `END CASE;`。
- [ ] F-21、F-36~F-41：函数头位置、八字段、名称、输入、输出、增量、日期与分隔线。
- [ ] F-22~F-26：`CREATE` 头、`DECLARE`/`BEGIN`/`EXCEPTION`、`$function$` 标签与空行。
- [ ] F-27~F-28：动态 SQL 的 `format`/`%I`/`%L`、`USING`、字符串内无 `--`。
- [ ] F-29：长表达式换行；未拆字符串、引号标识符、`::type`、`BETWEEN ... AND ...`。
- [ ] F-30/F-31：注释未重排；无真实人名、联系方式、内网地址、账号或连接串。
- [ ] `git diff -w` 后仅空白变化；token、括号分组、谓词位置、连接类型未变。
- [ ] 若目标显式声明为 GP 6.6，未引入 PG 9.5+ 语法；GP 子句未被工具挪动。
- [ ] 未对用户提供的只读样例跑原地格式化。
- [ ] 未把格式化通过当作正确性、权限安全或性能证明。

## 15. 参考

- pgFormatter：<https://github.com/darold/pgFormatter>
- SQLFluff：<https://docs.sqlfluff.com/>、<https://github.com/sqlfluff/sqlfluff>
- sql-formatter：<https://github.com/sql-formatter-org/sql-formatter>
- 公开 SQL Style Guide：<https://www.sqlstyle.guide/>
- PostgreSQL 文档：<https://www.postgresql.org/docs/>
- Greenplum 6.6 文档：<https://docs.greenplum.org/6-6/>

社区指南在逗号前后置、`AND` 缩进宽度、是否对齐类型等细节上各不相同。本文固定一套默认值，
并允许仓库级覆盖；评审时先看仓库配置，再按本规范检查未被覆盖的部分。
