# PL/pgSQL 语法与函数形态

> **来源性质**：本文整理自公开参考来源与 PostgreSQL / Greenplum 官方文档，属于
> `reference-derived`（参考来源推导）的语法与形态建议。它**不是**对任何个人或语料的观测证据，
> 不得把本文规则标成 `observed`，也不得用本文为个人风格、契约或性能背书。`observed` 只描述
> 用户当次输入中的现状，见 `references/02-反模式.md` 与 `04-固定风格.md`。
>
> **验证状态**：撰写过程中未连接数据库、未执行任何 SQL、未运行格式化或静态分析工具、未采集
> `EXPLAIN` 或负载数据。文中不包含任何“已实测更快/更慢”的结论；凡涉及性能，只作静态分类，
> 见 §10。

## 0. 范围、编号与证据等级

### 0.1 适用范围

- 适用：`LANGUAGE plpgsql` 的函数、过程（仅目标版本支持时）、触发器函数、`DO` 匿名块。
- 部分适用：`LANGUAGE sql` 函数。本文只在“该选 SQL 还是 PL/pgSQL”“返回形态是否一致”时提及，
  不展开 SQL 函数的语法。
- 不适用：其他过程语言、非 PostgreSQL / Greenplum 方言、客户端驱动侧的分页或重试逻辑。
- 目标引擎：默认基线为**原生 PostgreSQL 12+**（13+ 特性需标出引入版本并在目标库确认）；**Greenplum 6.6 / PostgreSQL 9.4**（GP 6.6 核心基于 PG 9.4）为可选兼容目标，仅当显式声明时启用低版本限制。

### 0.2 编号与相邻文件

- 本文规则编号 `PLS-xx`（PL/pgSQL Syntax），与相邻文件不重叠：

| 文档 | 编号 | 主题 |
|---|---|---|
| `01-基线规范.md` | 无编号条目 | 安全/正确性/事务/落表/性能默认值 |
| `02-反模式.md` | `AP-xx`、`B-xx` | 常见反模式、通用反模式 |
| `06-SQL排版规范.md` | `F-xx` | 文本形态 |
| `04-固定风格.md` | `STYLE-xx` | 命名、头部、结构、默认风格 |
| `07-性能优化规则.md` | `PERF-xx` | 性能证据与优化检查 |
| `08-PostgreSQL审查规则.md` | `REV-*` | 审查级别与问题表 |
| `09-工程与函数结构规范.md` | `ENG-xx` | 工程安全与函数结构 |
| 本文件 | `PLS-xx` | PL/pgSQL 语法与形态 |
| `11-增量与水位线.md` | `INC-xx` | 按更新时间增量、回看窗与水位线 |

- 引用格式统一写 `PLS-17`。跨文件引用只在需要划边界时出现；若相邻文件尚未随包提供，相关句子
  只作边界说明，不构成对未提供内容的依赖。
- 本文与既有文件冲突时的优先级见 `00-风格与边界.md` §6，本节不另列顺序。本文只补充语法与
  函数形态，不覆盖安全、正确性或排版 `MUST`。

### 0.3 证据等级

| 标记 | 含义 | 本文用法 |
|---|---|---|
| `语法事实` | PostgreSQL 官方语法定义，可静态核对 | 块结构、语句形式、关键字 |
| `版本事实` | 官方 release notes / 版本文档给出的引入版本 | 9.5、9.6、10、11、12 等 |
| `待验证` | 需要在目标 PG 版本（如 13+）或可选 GP 6.6 上确认 | 高版本特性或 GP 对某语法、扩展、视图的支持 |
| `static-risk` | 仅由代码形状判断的风险 | 见 §10，不等于慢 |
| `plan-required` | 需要执行计划才能定论 | 见 §10 |
| `workload-required` | 需要并发/数据量/锁/WAL 等负载数据才能定论 | 见 §10 |

本文不产生实测性能结论。没有计划输出、参数、数据快照与版本信息时，不得声称某写法已被
计划验证。

### 0.4 来源清单与归因边界

| 来源 | 本文取用的内容 | 未取用的内容 |
|---|---|---|
| supabase/agent-skills `supabase-postgres-best-practices` | 函数/查询形态、索引与统计的通用原则、`SECURITY DEFINER` 的 `search_path` 纪律 | 其“100–1000x”等性能倍数；Supabase 专有函数与 RLS 上下文 |
| github/awesome-copilot `postgresql-code-review` | 触发器函数、JSONB/数组、权限与 RLS 的审查视角 | 高版本（13+）或 Supabase 专属扩展假设直接套用到通用模板 |
| claude-dev-suite `skills/databases/plpgsql` | 块结构、异常、游标、动态 SQL、触发器与过程的语法骨架 | 其默认面向现代 PG 的示例（如过程、`ON CONFLICT`） |
| damusix/skills → `postgres-writing-guidelines` | 块结构、异常与 SQLSTATE 目录、动态 SQL、事务与锁纪律、连接池、触发器“薄函数”形态 | `fn_*`/`pr_*`/`tg_*` 命名、DOMAIN 全覆盖、`FOR UPDATE SKIP LOCKED`、`ON CONFLICT`、`MERGE`、生成列、UUID v7 |
| PostgreSQL 官方文档 | PL/pgSQL 语句、异常、触发器、过程、事务管理 | — |
| Greenplum 6.6 官方文档 | `CREATE FUNCTION`、`CREATE INDEX`、函数执行位置与方言限制 | — |

`damusix/postgres-writing-guidelines` 不是独立仓库；实际位置是 `damusix/skills` 根目录下的同名
技能目录。本文按该路径读取，只用于核对其 PL/pgSQL 形态与异常/事务表述，不把其命名体系、类型
体系或现代语法写成 `PLS-xx` 规则。该来源关于“没有显式 `SAVEPOINT` 就没有子事务”的表述与
PL/pgSQL 的 `EXCEPTION` 块行为不符，本文以 `PLS-35` 为准。

## 1. 版本与方言

### PLS-01 `MUST` 先定目标版本，再选语法

生成或改写前必须确认目标引擎与版本。未显式声明版本时，默认按**原生 PostgreSQL 12+** 基线编写（PG 13+ 特性列入 `Assumptions` 或带版本前提）；仅当显式声明目标为 **GP 6.6 或 PG 9.4** 时按两者交集降级。

### PLS-02 `MUST` 高版本特性带版本条件，显式 GP 6.6 目标不套 PG 特性

在默认 PostgreSQL 12+ 基线之上使用 13+ 特性（如 `EXPLAIN (WAL)`、`total_exec_time`、`MERGE`）或处于显式 GP 6.6 / PG 9.4 兼容模式时，写法必须回答“目标库版本是否支持”：

- PG 12+（默认基线可用，仅显式 GP 6.6 / PG 9.4 需规避或降级）：`ON CONFLICT`（9.5+）、`SKIP LOCKED`（9.5+）、RLS（9.5+）、`PARALLEL SAFE`（9.6+）、`GENERATED AS IDENTITY` / 转换表（10+）、`CREATE PROCEDURE` / `INCLUDE` / `EXECUTE FUNCTION`（11+）、`[NOT] MATERIALIZED` CTE / `REINDEX CONCURRENTLY`（12+）。
- PG 13+（默认 PG 12+ 基线未包含，需确认目标版本）：`EXPLAIN (WAL)`、`pg_stat_statements.total_exec_time`、`gen_random_uuid()` 内置（13+）；`pg_locks.waitstart`（14+）；`MERGE`（15+）。

当显式指定目标为 GP 6.6（基于 PG 9.4）时，注意其独有执行模型，以下结论不能平移：

- 没有 `ON CONFLICT`、`CREATE PROCEDURE`、RLS、`SKIP LOCKED`、`GROUPING SETS` / `CUBE` / `ROLLUP`、
  `PARALLEL` 属性、转换表、`MATERIALIZED` CTE、identity 列。
- 常见索引方法为 B-tree、bitmap、GiST、SP-GiST、GIN；没有 BRIN，hash 索引被停用；
  `CREATE INDEX CONCURRENTLY` 不支持。以上以目标 GP 6.6 文档与集群为准，未逐项实测。
- 函数有 GP 专属的 `EXECUTE ON ANY | MASTER | ALL SEGMENTS | INITPLAN`，没有 `PARALLEL` 属性。
- `EXPLAIN` 输出是 slice / segment / motion，不是社区 PG 的计划文本；不能用 PG 的 cost 数值比较。
- 不能从任何函数返回 `refcursor`（GP `CREATE FUNCTION` 的限制，`[GP-待验证]`，按目标集群确认）。

方言分支要显式化：不要用 `current_setting('server_version_num')` 在函数体里猜语法；用部署脚本、
独立函数文件或构建期变量区分。函数体内的版本分支会把不可达分支带进生产。

#### 1.1 版本敏感特性表（唯一事实源）

**本表是版本事实的唯一来源。** `04`、`06`、`07`、`08` 需要判断“某特性是否可用”时引用本节，
不再各自维护清单。`08` §7.1 只定义“查到之后怎么定级”。

| 特性 | PG 12+（默认） | GP 6.6 / PG 9.4（可选） | 引入版本 | 默认策略 |
|---|---|---|---|---|
| `jsonb` 类型 | 可用 | PG 9.4 可用；GP `待验证` | 9.4 | PG 12+ 可用；GP 先确认 |
| `FILTER` 聚合子句 | 可用 | PG 9.4 可用；GP `待验证` | 9.4 | PG 12+ 可用；GP 先确认 |
| `WITH ORDINALITY` | 可用 | PG 9.4 可用；GP `待验证` | 9.4 | PG 12+ 可用；GP 先确认 |
| `ON CONFLICT` | 可用 | 否 | 9.5 | PG 12+ 可用；仅 GP / 9.4 规避 |
| RLS / `CREATE POLICY` | 可用 | 9.4 否；GP `待验证` | 9.5 | PG 12+ 可评估；GP 先确认 |
| `SKIP LOCKED` | 可用 | 否 | 9.5 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `GROUPING SETS` / `CUBE` / `ROLLUP` | 可用 | 否 | 9.5 | PG 12+ 可用；仅 GP / 9.4 规避 |
| BRIN 索引 | 可用 | 否 | 9.5 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `ASSERT`（PL/pgSQL） | 可用 | 否 | 9.5 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `jsonb_set` | 可用 | 否 | 9.5 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `PARALLEL` 函数属性 | 可用 | 否 | 9.6 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `pg_stat_progress_vacuum` | 可用 | 否 | 9.6 | PG 12+ 可用；GP / 9.4 查 `pg_stat_activity` |
| `wait_event` / `wait_event_type` | 可用 | 否 | 9.6 | PG 12+ 可用；GP / 9.4 查 `waiting` |
| hash 索引 WAL-safe | 可用 | 否（9.4 崩溃风险 / GP 禁用） | 10 | PG 12+ 安全；9.4 / GP 不推荐 |
| identity 列 | 可用 | 否 | 10 | PG 12+ 可用（既有 `serial` 不擅改）；GP / 9.4 用 `serial` |
| 触发器转换表 | 可用 | 否 | 10 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `CREATE STATISTICS` | 可用 | 否 | 10 | PG 12+ 可用；仅 GP / 9.4 规避 |
| `CREATE PROCEDURE` / `CALL` / 过程内 `COMMIT` | 可用 | 否 | 11 | PG 12+ 可用（受 `PLS-44` 约束）；GP / 9.4 无过程 |
| `INCLUDE` 覆盖索引 | 可用 | 否 | 11 | PG 12+ 可用；仅 GP / 9.4 用多列索引 |
| `EXECUTE FUNCTION`（触发器） | 可用 | 否 | 11 | PG 12+ 可用；GP / 9.4 用 `EXECUTE PROCEDURE` |
| `MATERIALIZED` / `NOT MATERIALIZED` CTE | 可用 | 否 | 12 | PG 12+ 可用；GP / 9.4 恒物化 |
| `REINDEX CONCURRENTLY` | 可用 | 否 | 12 | PG 12+ 可用；GP / 9.4 用普通 `REINDEX` |
| `EXPLAIN (WAL)` | 否（需 PG 13+） | 否 | 13 | 需确认目标 >= PG 13 |
| `pg_stat_statements.total_exec_time` | 否（PG 12 为 `total_time`，PG 13+ 用 `total_exec_time`） | 否（用 `total_time`） | 13 | 诊断脚本按版本区分列名 |
| `pg_locks.waitstart` | 否（需 PG 14+） | 否 | 14 | 需确认目标 >= PG 14 |
| `MERGE` | 否（需 PG 15+） | 否 | 15 | PG 12+ 默认不直接依赖，需 >= PG 15 |

上表“可用”只代表原生 PG 12+ 语法合法；若显式切换到 GP 6.6，`jsonb`、GIN、`FILTER` 等实际支持范围仍标
`待验证`，需在目标库用 `\df`、`pg_settings` 或最小样例确认。

## 2. 函数形态、查询结果与属性

### PLS-03 `MUST` 先选对象类型：函数、过程、触发器函数、`DO`

| 形态 | 调用方式 | 事务控制 | 适用 |
|---|---|---|---|
| 函数 | `SELECT` / 表达式 / `FROM` | 不能 `COMMIT` / `ROLLBACK` | 计算、查询、落表、返回集合 |
| 过程（PG 11+） | `CALL` | 受调用上下文限制，见 PLS-44 | 需要分批提交的长任务 |
| 触发器函数 | 由触发器调用 | 跟随触发语句 | 审计、校验、派生列 |
| `DO` 块 | 一次性执行 | PG 12+（11+）顶层可控制；9.4 / GP 无事务控制 | 迁移、校验、一次性修复 |

不要用函数模拟过程的分批提交；也不要把触发器函数当普通函数直接 `SELECT` 调用。

### PLS-04 `MUST` 参数模式、默认值与重载遵守声明规则

- 默认值只能出现在尾部；一个参数有默认值后，后续输入参数也必须有默认值。
- 只有 `IN` / `INOUT` 参数可以有默认值；`OUT` 参数不能有默认值。
- `VARIADIC` 只能有一个，且只能放在最后；`VARIADIC` 之后只能跟 `OUT` 参数。
- `OUT` / `INOUT` 不能与 `RETURNS TABLE` 混用；`RETURNS TABLE` 已隐含集合返回。
- 命名参数调用（`f(p_limit => 10)`）可用；不要用默认值制造歧义重载。
- 同名、不同输入参数类型是不同函数；`DROP FUNCTION` 必须带参数类型。
- 重载解析可能因隐式 cast 选错函数；调用方应显式 cast。

参数与变量命名优先用 `p_` / `v_` 前缀（与项目命名约定一致）。PL/pgSQL 默认 `#variable_conflict error`：
参数/变量与 SQL 中的列同名会直接报错。无法改名时用块标签限定（`label.var`），不要把
`#variable_conflict use_variable` 当成全局默认。

### PLS-05 `MUST` `SELECT INTO` 的非 `STRICT` 行为与 `STRICT` 行为分开写

`SELECT ... INTO target FROM ...` 在未指定 `STRICT` 时：

- 0 行：目标变量置 NULL，`FOUND = false`；
- 多行：**取第一行**，其余行丢弃；“第一行”在没有 `ORDER BY` 时没有定义；
- 不会因为多行而报错。

`SELECT ... INTO STRICT target ...`：

- 0 行 → `NO_DATA_FOUND`（`P0002`）；
- 多行 → `TOO_MANY_ROWS`（`P0003`）；
- 成功时 `FOUND = true`。

因此，凡是业务上要求“恰好一行”的查询，必须显式决定是否使用 `STRICT`，或加 `ORDER BY` + `LIMIT 1`
并写明取哪一行。`STRICT` 适合“缺行就是错误”的契约；不适合“0 行合法”的场景（空日期区间、源表
无增量）。不要把 `STRICT` 当成默认，也不要把 `NO_DATA_FOUND` 静默转成 NULL。

`INSERT/UPDATE/DELETE ... RETURNING ... INTO` 即使没有 `STRICT`，返回多行也会报错；因为没有
`ORDER BY` 可以决定取哪一行。需要多行时用 `FOR ... IN` 或 `RETURN QUERY`，不要用 `INTO` 接集合。

### PLS-06 `MUST` `FOUND` 与 `GET DIAGNOSTICS` 的来源要记清

`FOUND` 在每个函数调用开始时为 `false`，由以下语句设置：

- `SELECT INTO`：有行赋值则 true；
- `PERFORM`：产生至少一行则 true；
- `INSERT` / `UPDATE` / `DELETE`：至少影响一行则 true；
- `FETCH`：取到一行则 true；
- `MOVE`：成功重定位则 true；
- `FOR` / `FOREACH`：至少迭代一次则 true（循环退出时设置；循环体内不被循环语句本身修改）；
- `RETURN QUERY` / `RETURN QUERY EXECUTE`：查询至少返回一行则 true。

**`EXECUTE` 不改变 `FOUND`**。动态 SQL 之后不要靠 `FOUND` 判断是否有行；用 `GET DIAGNOSTICS`
取 `ROW_COUNT`，或用 `EXECUTE ... INTO STRICT`。

```sql
GET DIAGNOSTICS v_cnt = ROW_COUNT;
GET DIAGNOSTICS v_stack = PG_CONTEXT;
```

- `ROW_COUNT` 是最近一条 SQL 命令处理的行数；可用于 DML 与 `EXECUTE` 之后。
- `PG_CONTEXT` 返回当前调用栈文本。
- `RESULT_OID` 只对带 OID 的表插入有意义；OID 已属遗留特性，不要在新代码中使用。

丢弃查询结果时用 `PERFORM query`。PL/pgSQL 中能返回行的 `SELECT` 如果没有 `INTO`，会被拒绝执行；
`PERFORM` 是语法要求，不是“优化写法”，它仍然执行查询并设置 `FOUND`。

### PLS-07 `MUST` 返回形态与调用契约一致

| 返回形态 | 语法 | 语义要点 |
|---|---|---|
| 标量 | `RETURNS type` | 必须能返回一个值；走到顶层块末尾仍未 `RETURN` 会运行时报错 |
| `VOID` | `RETURNS void` | 只做副作用；`RETURN;` 可提前退出 |
| `SETOF type` | `RETURNS SETOF type` | 0..N 行；用 `RETURN NEXT` / `RETURN QUERY`，最后 `RETURN;` |
| `TABLE(...)` | `RETURNS TABLE(col type, ...)` | 本质是命名的 `OUT` 参数，并隐含 `SETOF` |
| `OUT` / `INOUT` | 参数模式 | 多返回值；`RETURNS` 可省略，存在时必须与输出参数一致 |
| `record` | `RETURNS record` | 调用处需列定义列表，除非有 `OUT` 参数；稳定性差 |
| `trigger` | `RETURNS trigger` | 只能由触发器调用，见 §8 |

不要用 `text` 传递结构化结果（JSON 字符串、拼接的 CSV、`col1|col2`）；这会把列类型、NULL 与转义
问题推给调用方。需要多列时用 `RETURNS TABLE`、`OUT` 参数或复合类型。

`RETURNS record` 没有 `OUT` 参数时，调用方必须提供列定义列表：

```sql
SELECT *
FROM demo.f_dynamic() AS t (id bigint, amount numeric);
```

`RETURNS TABLE` 的列是命名的 `OUT` 参数，函数体内可以直接引用；这也意味着它们可能与表列同名，
触发 `#variable_conflict`。命名时加业务前缀，或显式限定。

### PLS-08 `MUST` 集合返回用 `RETURN NEXT` / `RETURN QUERY` 累积

- `RETURN NEXT expr` 追加一行；标量与复合类型都可。
- `RETURN QUERY SELECT ...` 追加查询的全部结果。
- `RETURN QUERY EXECUTE '...' USING ...` 追加动态查询结果。
- 两者可以混用，结果按执行顺序拼接。
- 最后用无参数的 `RETURN;` 结束，或让控制走到函数末尾。

`RETURN NEXT` / `RETURN QUERY` 不会立即返回调用方；它们只累积结果集。PostgreSQL 文档说明
该实现会先把整个结果集累积起来再返回；结果集很大时可能写入磁盘，受 `work_mem` 影响。这是实现事实，不等于“必然慢”；
实际影响属于 `workload-required`，需要结果行数、内存与耗时数据。

### PLS-09 `MUST` volatility / `STRICT` / `COST` / `ROWS` 按实际行为声明

- 默认 `VOLATILE`。写表、调用 `random()` / `clock_timestamp()`、依赖序列的函数必须是 `VOLATILE`。
- `STABLE`：不写库，且同一条语句内对相同参数返回稳定结果；可用于依赖表查找或 `current_timestamp`
  的函数。
- `IMMUTABLE`：不读表、不依赖任何外部状态、对相同参数永远返回相同结果；可用于表达式索引。
- 只读函数保持默认 `VOLATILE` 不会破坏正确性；不要仅因“它是只读的”就强制改 `STABLE`。
- 在 GP 6.6，`STABLE` / `VOLATILE` 函数含 SQL 或修改数据时在 segment 上受限，见 PLS-13。

`STRICT`（等价 `RETURNS NULL ON NULL INPUT`）表示任一参数为 NULL 时不执行函数体、直接返回 NULL。
这会改变副作用是否发生、错误是否抛出、NULL 返回契约。改写既有函数时，增删 `STRICT` 属于行为
变更，必须单独列出并取得同意。

对 `VARIADIC` 参数，`STRICT` 只检查整个数组是否为 NULL；数组含 NULL 元素时 PL/pgSQL 仍会调用
函数。不要把它误解为“逐元素跳过 NULL”。

`COST` / `ROWS` 是规划器提示，不是性能证明。`COST` 影响规划器对函数求值次数的估计；`ROWS` 只对
集合返回函数有意义，GP 6.6 的 `CREATE FUNCTION` 语法未列出 `ROWS`，使用前确认。没有计划和负载
数据时，不要用调大/调小 `COST` 来声称优化；这类改动属于 `plan-required`。

### PLS-10 `MUST` `PARALLEL` 与 `EXECUTE ON` 不可互换

- PostgreSQL 9.6+ 用 `PARALLEL SAFE | RESTRICTED | UNSAFE` 描述函数能否在并行 worker 中执行；
  默认 `UNSAFE`。
- GP 6.6 没有 `PARALLEL` 属性，改用 `EXECUTE ON ANY | MASTER | ALL SEGMENTS | INITPLAN` 描述
  执行位置。
- 两者语义不同：一个是“能否并行”，一个是“在哪执行”。不要把 GP 的 `EXECUTE ON` 写进 PostgreSQL
  函数，也不要把 `PARALLEL SAFE` 写进 GP 6.6。

GP 的 `EXECUTE ON MASTER` / `ALL SEGMENTS` 还有额外限制：函数必须是集合返回、不能出现在
`FROM` 子句、不能出现在带 `FROM` 的 `SELECT` 列表，且查询会从 GPORCA 回退到 Postgres Planner。
`EXECUTE ON INITPLAN` 只支持用在 `CREATE TABLE AS` 或 `INSERT` 的 `FROM` 子句中，不支持 CTE。

### PLS-11 `MUST` `SECURITY DEFINER` 采用可审计的语法形态

```sql
CREATE OR REPLACE FUNCTION demo.f_secure(p_id bigint)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, demo, pg_temp
AS $function$
/*****************************************************************
*name       : demo.f_secure
*function   : 演示函数
*input      : p_id 主键
*output     : -1参数异常, 0正常
*increment  : 不适用
*author     : <team>
*CreateDate : 2026-01-01
*UpdateDate : 2026-01-01
******************************************************************/

BEGIN
    RETURN 0;
END;
$function$;
```

- 两种合格写法二选一：上面这种显式三件套，或 `SET search_path = ''` + 函数内全限定对象
  （见 `01-基线规范.md`）。
- `pg_temp` 必须**显式放在最后**；只写“排除 `pg_temp`”不够。
- 所有对象名尽量 schema 限定；不要依赖调用方的 `search_path`。
- `REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC`；按最小权限授予角色。
- `SET search_path = ''` 是更严格的写法，但要求函数内所有对象都限定；PG 12+ 与 9.4 均可用，GP 6.6 需用户侧验证。
- 函数 owner 使用最小权限角色；不要用 superuser 作为 owner。
- 这条与 `references/01-基线规范.md` 的“安全”一节重复时，以 01 为准；本文只固定语法形态。

### PLS-12 `MUST` `CREATE OR REPLACE` 不能改契约

- `CREATE OR REPLACE FUNCTION` 不能改函数名、输入参数类型、返回类型；改这些等于新建函数。
- 不能改已有输入参数的名字（可以给原本无名的参数补名字）；有多个 `OUT` 参数时不能改 `OUT` 名，
  否则结果列名变化。
- 不要用默认值制造歧义：`f(int)` 与 `f(int, int DEFAULT 42)` 会让 `f(10)` 无法解析。
- 需要改返回类型、参数类型或参数名时，走显式迁移：新函数名 + 调用方切换，或 `DROP` + `CREATE`
  并重新授权；不要假设 `CREATE OR REPLACE` 能保住依赖对象。

### PLS-13 `MUST` GP 函数要声明执行位置与数据访问边界

GP 6.6 中，函数在 master 还是 segment 执行会影响结果与可行性：

- 只读复制表（`DISTRIBUTED REPLICATED`）的函数可以在 segment 上执行；访问 hash/random 分布表
  的函数通常应在 master 执行。
- 函数读取或修改分布表、返回多行、且参数来自分布表时，可能不被支持；见 GP `CREATE FUNCTION`
  的“Using Functions with Queries on Distributed Data”。
- `EXECUTE ON` 是 GP 专属语法；生成通用模板时不要带它。
- 不能从 GP 函数返回 `refcursor`（`[GP-待验证]`，按目标集群确认）。

## 3. 块结构、变量与赋值

### PLS-14 `MUST` 基本块结构固定

```sql
[ <<label>> ]
[ DECLARE
    ... ]
BEGIN
    ...
[ EXCEPTION
    WHEN ... THEN
        ... ]
END [ label ];
```

- `DECLARE` 必须在 `BEGIN` 之前；`EXCEPTION` 必须在块末尾；一个块只能有一个 `EXCEPTION` 段。
- `END` 后可跟块标签；标签必须与开头一致。
- 空块 `BEGIN END;` 合法但无意义；`NULL;` 是合法的空语句。

### PLS-15 `MUST` 标签与变量遮蔽要显式处理

- `<<outer>> LOOP ... EXIT outer; ... END LOOP outer;`
- `EXIT` 可以退出带标签的 `BEGIN` 块；无标签 `EXIT` 只匹配循环，不匹配 `BEGIN` 块。
- `CONTINUE` 的标签必须指向循环，不能指向普通块。
- 标签名不要与变量名、表名冲突；限定变量时写 `label.var`。
- 内层块的同名变量会遮蔽外层变量。默认 `#variable_conflict error` 会在 SQL 语句里发现参数/变量
  与列名冲突时报错；`use_variable` / `use_column` 是块级指令，只影响该块，不要全局打开。

推荐顺序：改名（`p_` / `v_`）→ 用块标签限定 → 最后才考虑 `#variable_conflict`。

### PLS-16 `MUST` `DECLARE` 的初始化时机与类型选择

- `DECLARE` 中的默认表达式在**每次进入块时**求值，不是函数创建时求值一次。
- 没有默认值的变量初始化为 NULL。
- 不要把昂贵查询、序列调用或副作用放进 `DECLARE` 默认值；它们会在每次进入块时执行。
- `CONSTANT` 必须初始化；`NOT NULL` 变量必须有非 NULL 初值或在使用前赋值，否则运行时错误。
- `table.column%TYPE` 跟随列类型，减少列类型变更带来的漂移。
- `table%ROWTYPE` 跟随整行结构；适合 `SELECT * INTO` 或 `FOR ... IN SELECT *`。
- `RECORD` 是动态的：字段在赋值后才确定，拼写错误到运行时才暴露。
- 不要用 `%ROWTYPE` 承接宽表后长期依赖列序；显式列更稳。

### PLS-17 `MUST` 赋值用 `:=`，不要与 SQL 的 `=` 混淆

- PL/pgSQL 赋值可写 `var := expr` 或 `var = expr`；统一用 `:=`（与 `06-SQL排版规范.md` 一致）。
- `SELECT ... INTO` 是赋值，不是建表；建表用 `CREATE TABLE ... AS SELECT`。
- 多目标赋值 `SELECT a, b INTO v_a, v_b` 按位置对应，列数/类型必须匹配。
- 变量赋值会经过类型转换；字符串转数值失败会在运行时抛错，不要依赖隐式转换处理脏数据。

## 4. 控制结构

### PLS-18 `MUST` `IF` / `ELSIF` / `ELSE` / `END IF;` 成对

- `ELSIF` 是一个关键字；写成 `ELSE IF` 会开启嵌套 `IF`，需要额外的 `END IF`。
- 条件为 NULL 时按“非真”处理，走 `ELSE` 分支。
- 每个 `IF` 必须有匹配的 `END IF;`。

### PLS-19 `MUST` `CASE` 语句以 `END CASE;` 结束，且注意缺省 `ELSE`

- 简单 `CASE expr WHEN val THEN ... END CASE;`
- 搜索 `CASE WHEN cond THEN ... END CASE;`
- 没有 `ELSE` 且没有匹配项时，抛 `CASE_NOT_FOUND`，不是“什么也不做”。
- 这与 SQL 的 `CASE` 表达式不同：表达式以 `END` 结束，可用于 `SELECT` 列表。

### PLS-20 `MUST` 循环必须有出口或上界

- `LOOP ... END LOOP;` 是无条件循环，必须有 `EXIT` / `RETURN` 或可证明的上界。
- `WHILE cond LOOP ... END LOOP;` 在每次进入循环体前检查条件。
- `EXIT [label] [WHEN cond];` 可退出当前循环或带标签的外层循环/块。
- `CONTINUE [label] [WHEN cond];` 跳到下一次迭代；标签必须指向循环。

`FOR` 的三种形态：

```sql
FOR i IN 1..10 LOOP ... END LOOP;                 -- 整数范围
FOR i IN REVERSE 10..1 BY 2 LOOP ... END LOOP;    -- 反向、步长
FOR r IN SELECT ... LOOP ... END LOOP;            -- 查询结果
FOR r IN EXECUTE 'SELECT ...' USING v_id LOOP ... END LOOP;  -- 动态查询
```

- 整数范围的下界/上界/步长在进入循环时求值一次；下界大于上界（或反向时小于）不执行循环体，
  不报错。
- 查询形态的 `FOR` 会执行一次查询并逐行取；它仍是逐行处理，不等于一条集合式 SQL。
- `FOR ... IN EXECUTE` 在执行该语句时重新规划一次，然后逐行迭代；重规划发生在语句级，
  不是每一行一次。与普通 `EXECUTE` 一样没有可复用的计划缓存。

`FOREACH` 只用于数组/复合值：

```sql
FOREACH x IN ARRAY v_arr LOOP ... END LOOP;
FOREACH x SLICE 1 IN ARRAY v_arr LOOP ... END LOOP;
```

- `SLICE` 必须是整数常量，且不大于数组维数；目标变量必须是数组。
- 没有 `SLICE`（或 `SLICE 0`）时逐元素迭代。
- 数组元素按存储顺序访问，不保证业务顺序；需要顺序时显式排序或改用查询。

### PLS-21 `MUST` 循环内 SQL 的改写要先过语义关

语法允许在循环里执行 DML/DDL，但“能写”不等于“该写”。把循环改成集合式之前，必须确认：

- 是否有逐行副作用、顺序依赖、异常处理差异；
- 行数上界、批大小、锁持有时间；
- 目标引擎是否支持所需的集合式写法（GP 6.6 的分布/分区限制）。

性能判断只能按 §10 分类，不能因为“有循环”就断言慢，也不能因为“改成集合式”就断言快。

## 5. 游标

### PLS-22 `MUST` 绑定游标与无绑定游标分清

绑定游标：

```sql
DECLARE
    cur CURSOR FOR SELECT id FROM demo.t_demo WHERE dt >= p_from;
BEGIN
    OPEN cur;
    FETCH cur INTO v_id;
    CLOSE cur;
END;
```

无绑定游标 / `refcursor`：

```sql
OPEN v_cur FOR SELECT ...;
OPEN v_cur FOR EXECUTE 'SELECT ... WHERE id = $1' USING p_id;
```

绑定游标的查询在声明时确定；无绑定游标可在运行时决定查询与参数。需要动态表名/列名时用后者，
但必须遵守 §6 的绑定与引用规则。

取行状态只用 PL/pgSQL 真正提供的接口：

- `FETCH` 之后检查特殊变量 `FOUND`：取到行则为 true，没有下一行则为 false（PG 官方文档
  “Using Cursors” 一节只给出这一种判断方式）。
- **PL/pgSQL 没有 `cur%FOUND` / `cur%ROWCOUNT` / `cur%ISOPEN` 这类游标属性**。它们是 Oracle
  PL/SQL 的语法，PostgreSQL 不实现，照抄会在编译时报语法错误；`FOUND`、`ROW_COUNT` 也不能
  加在游标名后面。
- 需要“已取行数”时自己维护计数器（`v_cnt := v_cnt + 1`），或在循环外对比首末键；
  `GET DIAGNOSTICS ... = ROW_COUNT` 取的是最近一条 SQL 命令的行数，不是游标累计取行数。
- 需要“游标是否打开”时用显式状态变量记录，并让 `OPEN` / `CLOSE` 成对出现；不要依赖
  不存在的 `%ISOPEN`。
- `FOUND` 是函数级局部变量，会被循环体内的其他语句改写；在同一次 `FETCH` 之后立即判断，
  不要跨语句复用。

### PLS-23 `MUST` `refcursor` 的可用性先确认

- PostgreSQL 可以返回 `refcursor`，但调用方必须在同一事务内取完；事务结束游标关闭。
- **GP 6.6 不支持从函数返回 `refcursor`**（GP `CREATE FUNCTION` 文档限制，`[GP-待验证]`）；
  需要返回集合时用 `SETOF` / `RETURNS TABLE`。
- 不要把 `refcursor` 当作跨事务分页机制；需要跨事务保留时用 SQL 层 `WITH HOLD` 游标，
  并确认驱动支持。

### PLS-24 `MUST` `WHERE CURRENT OF` 只用于可更新游标

`WHERE CURRENT OF cur` 依赖游标定位到可更新的行；以下情况不要使用：

- 查询含 `JOIN`、聚合、`DISTINCT`、`UNION`、`GROUP BY`；
- 游标不是简单的单表查询；
- 目标引擎/驱动不支持定位更新。

优先按主键显式 `UPDATE ... WHERE id = v_id`，语义更清楚，也更容易审查。

### PLS-25 `MUST` 游标生命周期跟随事务

- 游标默认在事务结束时关闭；不要假设 `COMMIT` 后还能继续 `FETCH`。
- 在过程里 `COMMIT` 时，循环游标可能被转为 holdable cursor 并在第一次提交时整体求值；
  这会改变锁持有与内存行为。属于 `static-risk` + `workload-required`，必须由用户侧验证。
- 非只读命令驱动的游标循环（如 `UPDATE ... RETURNING`）不允许事务控制命令。
- 忘记 `CLOSE` 会占用资源；用 `FOR ... IN` 可自动关闭。

## 6. 动态 SQL

### PLS-26 `MUST` `EXECUTE` 的基本形式

```sql
EXECUTE command_string
    [ INTO [STRICT] target ]
    [ USING expression [, ...] ];
```

- `command_string` 是 `text` 表达式；可以是拼接或 `format()` 的结果。
- `INTO` 在 `USING` 之前；`USING` 的值在命令字符串里用 `$1`、`$2` 引用。
- 没有 `INTO` 时，查询结果被丢弃。
- 命令字符串里不要再写 `SELECT INTO`；用 `EXECUTE ... INTO`。

### PLS-27 `MUST` `USING` 只绑定值，不绑定标识符

`USING` 只能用于数据值，且只在 `SELECT` / `INSERT` / `UPDATE` / `DELETE` 中有效；其他工具类语句
（DDL、`VACUUM` 等）即使只是数据值，也必须以文本形式拼入。

表名、列名、schema 名不能参数化；必须用 `format('%I', ...)`、`quote_ident()` 或白名单。

### PLS-28 `MUST` `format()` / `quote_*` 的职责分清

- `%I`：标识符引用（表、列、schema）。
- `%L`：字面量引用（字符串、日期等）。
- `%s`：不做任何引用，只做字符串插入；不得用于外部输入。
- `quote_ident()` / `quote_literal()` / `quote_nullable()` 是函数形式；`quote_literal` 是 `STRICT`，
  传入 NULL 返回 NULL，可能让整条 SQL 变成 NULL；值可能为 NULL 时用 `quote_nullable`。

`format()` 只解决引用，不解决 SQL 结构安全；不要把用户输入拼成关键字、`ORDER BY` 方向或表名后
只做 `%I` 就认为安全，仍需白名单。

### PLS-29 `MUST` `EXECUTE ... INTO STRICT` 的 0 行/多行语义与 `SELECT INTO` 一致

- 非 `STRICT`：0 行置 NULL，多行取第一行；
- `STRICT`：0 行 `NO_DATA_FOUND`，多行 `TOO_MANY_ROWS`。

动态查询需要“恰好一行”时显式写 `STRICT`，并在异常处理里区分“无数据”和“多数据”。

### PLS-30 `MUST` 动态 SQL 没有计划缓存，且文本要稳定

- `EXECUTE` 每次执行都重新规划；普通静态 SQL 可能缓存计划。不要把“动态 SQL 一定更慢”写成结论；
  它的成本取决于解析/规划开销与执行时间，属于 `plan-required` / `workload-required`。
- 动态 SQL 字符串里不要用 `--` 行注释；拼接或换行可能把后续内容注释掉。需要注释时用 `/* ... */`
  或不写。
- 如果日志、审计或下游解析依赖生成的 SQL 文本，保持文本稳定；格式化前后留一份生成文本对比。
- 动态 DDL 也要用 `%I` 引用标识符；`SECURITY DEFINER` + 动态 DDL 风险更高，需要白名单与权限复核。

## 7. 异常处理

### PLS-31 `MUST` `EXCEPTION` 只放在块末尾

```sql
BEGIN
    ...
EXCEPTION
    WHEN unique_violation THEN
        ...
    WHEN OTHERS THEN
        ...
END;
```

- 一个块只能有一个 `EXCEPTION` 段，且必须在 `END` 之前。
- 异常处理器覆盖整个块；只想包住一部分语句时，用嵌套 `BEGIN ... EXCEPTION ... END`。
- 处理器里再抛出的新异常不会被同一个 `EXCEPTION` 捕获，会向外传播。

### PLS-32 `MUST` 条件名、`SQLSTATE` 与 `OTHERS` 的边界

- 条件名：`unique_violation`、`foreign_key_violation`、`not_null_violation`、`check_violation`、
  `division_by_zero`、`no_data_found`、`too_many_rows`、`serialization_failure`、`deadlock_detected`、
  `lock_not_available`、`query_canceled` 等。
- `SQLSTATE` 形式：`WHEN SQLSTATE '23505' THEN ...`；与条件名等价。
- 条件名不区分大小写；不要用字符串拼错误码。
- 自定义错误用 `RAISE ... USING ERRCODE = '...'`，并保持 5 位码或合法条件名。
- `WHEN OTHERS` 匹配大多数错误，但 **不匹配 `QUERY_CANCELED`**；9.5+ 引入 `ASSERT` 后，
  `ASSERT_FAILURE` 也不被 `OTHERS` 捕获（以目标版本为准）。
- `WHEN OTHERS THEN NULL` 是反模式；至少 `RAISE;` 重抛，或带 `ERRCODE` 重抛。
- 先捕获具体条件，再考虑 `OTHERS` 兜底；不要用 `OTHERS` 做正常分支。

### PLS-33 `MUST` `GET STACKED DIAGNOSTICS` 只在异常处理器内使用

```sql
EXCEPTION
    WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS
            v_state = RETURNED_SQLSTATE,
            v_msg = MESSAGE_TEXT,
            v_detail = PG_EXCEPTION_DETAIL,
            v_hint = PG_EXCEPTION_HINT,
            v_context = PG_EXCEPTION_CONTEXT;
        RAISE EXCEPTION '%', v_msg
            USING ERRCODE = v_state, DETAIL = v_detail, HINT = v_hint;
END;
```

- 未设置的项返回空字符串，不是 NULL。
- `SQLSTATE` / `SQLERRM` 特殊变量也只在异常处理器内定义；处理器外不要引用。
- 需要保留原始错误码时，重抛必须显式 `USING ERRCODE = v_state`；否则新异常会变成默认 `P0001`。

### PLS-34 `MUST` `RAISE` 的级别与格式符正确

- 级别：`DEBUG`、`LOG`、`INFO`、`NOTICE`、`WARNING`、`EXCEPTION`。
- `RAISE NOTICE 'fmt %', v;`；字面量 `%` 写成 `%%`。
- `RAISE EXCEPTION 'msg' USING ERRCODE = '23505', DETAIL = '...', HINT = '...';`
- `RAISE;` 只能在没有参数的异常处理器内重抛当前异常。
- 生产路径不要 `RAISE INFO` 打印整段 SQL 或参数值；用 `DEBUG` 或只打印长度/谓词摘要。

### PLS-35 `MUST` 异常块是子事务，语义与成本都要记住

- 进入带 `EXCEPTION` 的块会建立子事务；块内已执行的数据库修改在捕获异常时全部回滚。
- 块之前的语句不受影响；块内局部变量保留异常发生时的值。
- PL/pgSQL 不支持 `SAVEPOINT` / `ROLLBACK TO SAVEPOINT` / `RELEASE SAVEPOINT`；异常块是替代。
- 官方文档明确指出：带 `EXCEPTION` 的块进入/退出显著更贵；不要无必要地包大段语句。
  这属于 `static-risk`；实际影响需要 `workload-required` 的调用频率与耗时数据。

### PLS-36 `MUST` 不要用异常做正常控制流

- 默认 PG 12+ 优先用 `WHERE` 谓词、`EXISTS`、`ON CONFLICT` 或先查后写处理可预期分支。
- 仅当显式声明目标为 PG 9.4 / GP 6.6（无 `ON CONFLICT`）时，`unique_violation` 重试才是可移植方案；但要在注释里
  写明“依赖异常做并发分支”，并区分是哪个唯一索引触发。
- 不要在循环里用异常块处理大量预期失败；异常块的子事务开销会累积。
- 异常信息要带上下文但不泄露敏感数据：带函数名、关键参数名、业务键；不要带连接串、口令、
  身份证号、手机号。错误文本是外部契约，改写时不要随意改文案。

## 8. 触发器函数

### PLS-37 `MUST` 触发器函数声明为 `RETURNS trigger`，返回值按时机区分

```sql
CREATE OR REPLACE FUNCTION demo.f_trg_touch()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
/*****************************************************************
*name       : demo.f_trg_touch
*function   : 演示函数
*input      : 无
*output     : NEW
*increment  : 不适用
*author     : <team>
*CreateDate : 2026-01-01
*UpdateDate : 2026-01-01
******************************************************************/
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;
```

触发器函数不能作为普通函数直接 `SELECT` 调用；它由 `CREATE TRIGGER` 绑定。

| 时机 | 返回值 | 效果 |
|---|---|---|
| `BEFORE` 行级 `INSERT` / `UPDATE` | `NEW` | 继续执行，使用修改后的行 |
| `BEFORE` 行级 `INSERT` / `UPDATE` | `NULL` | 跳过该行操作 |
| `BEFORE` 行级 `DELETE` | `OLD` | 继续删除 |
| `BEFORE` 行级 `DELETE` | `NULL` | 跳过删除 |
| `AFTER` 行级 | 忽略 | 返回 `NULL` 或 `NEW` 都不影响结果 |
| `INSTEAD OF` 行级 | `NEW` / `OLD` | 由函数自己执行底层 DML |
| 语句级 | 忽略 | 返回 `NULL` |

`AFTER` 触发器里不要再修改 `NEW` / `OLD`；赋值不会生效。`BEFORE` 行级触发器里才可以修改 `NEW`。

### PLS-38 `MUST` 使用 `TG_*` 变量而不是猜上下文

| 变量 | 含义 |
|---|---|
| `TG_OP` | `INSERT` / `UPDATE` / `DELETE` / `TRUNCATE` |
| `TG_WHEN` | `BEFORE` / `AFTER` / `INSTEAD OF` |
| `TG_LEVEL` | `ROW` / `STATEMENT` |
| `TG_NAME` | 触发器名 |
| `TG_TABLE_NAME` | 表名 |
| `TG_TABLE_SCHEMA` | schema 名 |
| `TG_NARGS` | 参数个数 |
| `TG_ARGV[]` | 触发器参数 |

`TG_RELID` / `TG_RELNAME` 是遗留形式；优先用 `TG_TABLE_SCHEMA` + `TG_TABLE_NAME`。

### PLS-39 `MUST` 触发器 DDL 使用目标版本支持的写法

- 默认 PG 12+（11+）：`CREATE TRIGGER ... EXECUTE FUNCTION demo.f_trg();`（`EXECUTE PROCEDURE` 仍被接受）
- 显式 PG 9.4 / GP 6.6 目标：只能写 `CREATE TRIGGER ... EXECUTE PROCEDURE demo.f_trg();`
- 省略 `FOR EACH` 时默认是 `FOR EACH STATEMENT`；行级触发器必须显式写 `FOR EACH ROW`。
- `INSTEAD OF` 只能用于视图，且只能是行级。
- 约束触发器（`CREATE CONSTRAINT TRIGGER`）是 `AFTER ROW` 的特殊形式，可延迟；普通业务触发器
  不要误用。

### PLS-40 `MUST` `WHEN` / `UPDATE OF` / 转换表的使用边界

- `WHEN (condition)` 只用于行级触发器；`INSERT` 触发器不能引用 `OLD`，`DELETE` 触发器不能引用
  `NEW`。需要跨操作判断时在函数体里用 `TG_OP`。
- `UPDATE OF col1, col2` 只对 `UPDATE` 事件有效；不能用于 `INSERT` / `DELETE`。
- 转换表 `REFERENCING OLD TABLE AS ... NEW TABLE AS ...` 在 PG 10+（含默认 PG 12+）支持、仅 `AFTER` 触发器、
  不能用于视图或约束触发器；显式 GP 6.6 / PG 9.4 目标不支持（可用语句级触发器 + 临时表或应用侧批处理替代）。

### PLS-41 `MUST` 触发器陷阱要显式防护

- **递归**：触发器修改同一张表会再次触发自身；用 `pg_trigger_depth()`（9.1+）或 `WHEN` 条件防护，
  并写清最大深度。
- **行级 vs 语句级**：行级触发器每行执行一次；大批量 DML 时成本随行数增长。语句级触发器只执行
  一次，但看不到每一行的 `NEW` / `OLD`。
- **`TRUNCATE`**：只有语句级触发器，且没有 `OLD` / `NEW`；不要假设行级逻辑会执行。
- **触发器顺序**：同类触发器按名称字母序执行；不要依赖顺序，合并为一个触发器或显式编排。
- **`RETURN NULL`**：在 `BEFORE` 行级触发器里会跳过该行操作；在 `AFTER` / 语句级里返回值被忽略。
- **`INSTEAD OF`**：必须自己执行底层 `INSERT` / `UPDATE` / `DELETE`，否则视图操作不会落表。

触发器函数默认 `SECURITY INVOKER`；如果改成 `SECURITY DEFINER`，必须按 PLS-11 固定 `search_path`、
限定对象名、收紧 `EXECUTE` 权限。不要因为“触发器只在本表运行”就省略。

### PLS-42 `SHOULD` 事件触发器与普通触发器分开

事件触发器（`RETURNS event_trigger`，PostgreSQL 9.3+）用于 DDL 事件，变量是 `TG_EVENT` / `TG_TAG`，
不是 `NEW` / `OLD`。不要把它与表触发器混在同一个函数或同一套审查规则里。

## 9. 过程（PostgreSQL 11+）

### PLS-43 `MUST` `CREATE PROCEDURE` 不带 `RETURNS`

以下为语法示例（节选，省略头部注释；过程命名按项目约定）：

```sql
CREATE OR REPLACE PROCEDURE demo.p_batch(p_from date)
LANGUAGE plpgsql
AS $procedure$
BEGIN
    ...
END;
$procedure$;

CALL demo.p_batch(date '2026-01-01');
```

美元标签按 `references/06-SQL排版规范.md` 的 F-26 与仓库约定保持一致；示例用 `$procedure$`
只是与函数体区分，不要求全库统一改成它。

- 过程可以有 `IN` / `OUT` / `INOUT` 参数，但没有 `RETURNS` 子句。
- 调用用 `CALL`，不能出现在 `SELECT` 表达式或 `FROM` 子句中。
- `CREATE OR REPLACE PROCEDURE` 不能改参数类型；改名/改类型等于新建。
- 默认 PG 12+ 可使用过程；仅显式声明目标为 GP 6.6 或 PG 9.4 时不支持过程，只能用函数 + 调用方事务或应用侧分批。

### PLS-44 `MUST` 过程的事务控制受调用上下文限制

- 只有通过顶层 `CALL`（或 PG 11+ 顶层 `DO`）调用时，过程才能执行 `COMMIT` / `ROLLBACK`。
- 在显式事务块内 `CALL` 过程时，过程不能执行事务控制。
- 调用链中若中间夹了其他命令（如 `CALL p1()` → `SELECT f()` → `CALL p2()`），`p2` 不能控制事务。
- `SECURITY DEFINER` 过程不能执行事务控制；带 `SET` 子句的过程也不能执行事务控制。
- 异常块内部不能结束事务（子事务）。
- 游标循环里 `COMMIT` 会把循环游标转为 holdable 并在第一次提交时整体求值；非只读游标循环不允许
  事务控制。

### PLS-45 `MUST` 函数改过程是破坏性变更

把函数改成过程会改变：

- 调用方式（`SELECT f()` → `CALL p()`）；
- 返回形态（过程没有返回值）；
- 事务边界（过程可能提交，函数不能）；
- 权限与依赖对象。

必须按 `references/05-重写协议.md` 的契约清单处理，不能当作“清理”。

## 10. 与性能的边界

语法层只能判断“代码形状”，不能证明快慢。下表把常见语法选择按三类证据拆开：

| 语法/形态 | 静态风险（`static-risk`） | 执行计划验证（`plan-required`） | 负载验证（`workload-required`） |
|---|---|---|---|
| 带 `EXCEPTION` 的块包大段语句 | 子事务进入/退出更贵；块内修改会被回滚 | 块内 SQL 的计划是否被异常结构影响 | 高频调用下的总耗时、子事务数量、锁持有 |
| 循环内逐行 DML | 往返次数与锁持有随行数增长 | 单条 DML 是否走索引、是否有嵌套循环 | 实际行数、批大小、锁等待、WAL |
| 动态 `EXECUTE` | 每次重规划、无计划缓存 | 生成语句的计划与参数敏感性 | 解析/规划占比、`pg_stat_statements` 文本增长 |
| 游标逐行 `FETCH` | 逐行处理、可能多次往返 | 游标查询的计划 | 行数、网络/进程往返、内存 |
| 集合返回函数 | 结果集先物化，可能落盘 | 查询本身的计划 | 结果行数、`work_mem`、临时文件、首行延迟 |
| 行级触发器 | 每行执行一次 | 触发语句的计划 | 批量 DML 的行数、触发器耗时、锁 |
| 多次 `SELECT INTO` | 多次查询/往返 | 每个查询是否可合并、是否走索引 | 调用频率、缓存命中、总耗时 |
| GP `EXECUTE ON MASTER` | 数据汇聚到 master 的瓶颈风险 | slice/motion 计划 | 数据量、segment 倾斜、网络 |
| GP `EXECUTE ON ALL SEGMENTS` | 结果 UNION ALL、重复执行 | slice 计划 | segment 数、数据分布、汇总成本 |

使用规则：

- 本文件没有任何实测性能结论。若引用用户提供的计划，必须同时给出：目标版本、
  参数、数据快照/行数、`EXPLAIN (ANALYZE, BUFFERS)` 输出；本技能不代为执行。GP 6.6 是否支持
  `BUFFERS` 需确认；不支持时用 `EXPLAIN ANALYZE` 并读 slice/segment。
- `workload-required` 需要并发、数据量、锁等待、WAL、临时文件、缓存命中等测量；没有这些数据时
  只能写“待验证”。
- 跨大版本（如 PG 12 ↔ PG 15+ 或 PG 9.4）与跨引擎（PG ↔ GP）的计划不可直接比较。
- 语法改写（集合化、去游标、拆 CTE）可能改变语义与计划，必须先过 `references/05-重写协议.md`。

## 11. 生成 / 改写 / 审查检查清单

- [ ] 目标引擎与版本已确认；现代特性已标版本或 `待验证`（PLS-01、PLS-02）。
- [ ] 对象类型（函数/过程/触发器/`DO`）与调用方式匹配（PLS-03）。
- [ ] 参数模式、默认值、`VARIADIC`、`OUT` 组合合法（PLS-04）。
- [ ] `SELECT INTO` 是否 `STRICT` 已决定；多行/0 行行为已知（PLS-05）。
- [ ] `FOUND` / `GET DIAGNOSTICS` 使用正确，未依赖 `EXECUTE` 后的 `FOUND`（PLS-06）。
- [ ] 返回形态、0 行/NULL 契约、错误契约已写明；未用 `text` 传结构化结果（PLS-07）。
- [ ] 集合返回函数用 `RETURN NEXT` / `RETURN QUERY`，并知道结果集会物化（PLS-08）。
- [ ] volatility / `STRICT` / `COST` / `ROWS` / `PARALLEL` / `EXECUTE ON` 与目标版本一致
      （PLS-09、PLS-10）。
- [ ] `SECURITY DEFINER` 有 `SET search_path`、对象限定与权限收紧（PLS-11）。
- [ ] `CREATE OR REPLACE` 未改签名/返回类型/参数名（PLS-12）。
- [ ] GP 函数执行位置与分布式数据限制已确认（PLS-13）。
- [ ] 块结构、标签、变量遮蔽处理正确（PLS-14～PLS-16）。
- [ ] 赋值用 `:=`，`SELECT INTO` 未误当建表（PLS-17）。
- [ ] `IF` / `CASE` / 循环有正确结束符与出口（PLS-18～PLS-20）。
- [ ] 循环内 SQL 的改写已过语义关（PLS-21）。
- [ ] 游标生命周期、`refcursor` 可用性、`WHERE CURRENT OF` 限制已确认（PLS-22～PLS-25）。
- [ ] 动态 SQL 值用 `USING`、标识符用 `%I`/白名单；无 `--` 行注释（PLS-26～PLS-30）。
- [ ] 异常块只捕获可恢复条件；`OTHERS` 有重抛；保留 `SQLSTATE`（PLS-31～PLS-36）。
- [ ] 触发器返回值、`TG_*`、`WHEN`/`UPDATE OF`/转换表边界正确（PLS-37～PLS-42）。
- [ ] 过程仅在支持的版本与调用上下文使用；事务控制合法（PLS-43～PLS-45）。
- [ ] 未把语法通过当作语义正确或性能证明；性能陈述已按 §10 分类。

## 12. 参考来源与不可支持的结论

### 12.1 参考来源

- supabase/agent-skills，`supabase-postgres-best-practices`：
  <https://github.com/supabase/agent-skills>
- github/awesome-copilot，`postgresql-code-review`：
  <https://github.com/github/awesome-copilot/blob/main/skills/postgresql-code-review/SKILL.md>
- claude-dev-suite，`skills/databases/plpgsql`：
  <https://github.com/claude-dev-suite/claude-dev-suite/tree/main/skills/databases/plpgsql>
- PostgreSQL 12 文档，PL/pgSQL：
  <https://www.postgresql.org/docs/12/plpgsql.html>
  - 基本语句：<https://www.postgresql.org/docs/12/plpgsql-statements.html>
  - 控制结构：<https://www.postgresql.org/docs/12/plpgsql-control-structures.html>
- PostgreSQL 当前文档，`CREATE PROCEDURE`：
  <https://www.postgresql.org/docs/current/sql-createprocedure.html>
- PostgreSQL 当前文档，事务管理：
  <https://www.postgresql.org/docs/current/plpgsql-transactions.html>
- Greenplum 6 文档，`CREATE FUNCTION`：
  <https://docs.vmware.com/en/VMware-Greenplum/6/greenplum-database/ref_guide-sql_commands-CREATE_FUNCTION.html>
- Greenplum 6 文档，`CREATE INDEX`：
  <https://docs.vmware.com/en/VMware-Greenplum/6/greenplum-database/ref_guide-sql_commands-CREATE_INDEX.html>
- damusix/skills，`postgres-writing-guidelines`（实际路径；独立仓库名不存在）：
  <https://github.com/damusix/skills/tree/main/postgres-writing-guidelines>
  - 只用于核对 PL/pgSQL 形态、异常/事务与连接池表述；未把其命名、类型体系或现代语法写成规则。

### 12.2 不可支持的结论

- 未在 PostgreSQL 12+ 或任何可选兼容目标（GP 6.6 / PG 9.4）上编译、执行或验证任何片段。
- 未验证 GP 6.6 对 `jsonb`、`FILTER`、`WITH ORDINALITY`、GIN、`GET STACKED DIAGNOSTICS`、
  `pg_stat_statements` 的具体支持；相关项标 `待验证`。
- 未运行 pgFormatter、SQLFluff 或其他外部工具；排版结论以 `references/06-SQL排版规范.md` 为准。
- 未采集 `EXPLAIN`、`EXPLAIN ANALYZE`、锁等待、WAL、临时文件或吞吐数据；本文不声称任何写法
  更快或更慢。
- 未对用户提供的输入做任何修改、执行或重新格式化；输入只读，完整性由用户自己的版本控制负责。
