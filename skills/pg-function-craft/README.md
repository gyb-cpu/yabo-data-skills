# pg-function-craft

![pg-function-craft Hero](assets/pg-function-craft-hero.svg)

面向 PostgreSQL / Greenplum 函数、存储过程和触发器函数的生成、改写与审查 Skill。
它固定使用一套已脱敏的 SQL 编码风格，并在不连接数据库的前提下完成静态检查。

## 安装

本 Skill 不绑定特定 Agent。默认安装到执行安装命令时所在的项目，仅当前项目可见；仓库级说明见根目录 `README.md`。

### 通过 skills CLI

```bash
npx skills add gyb-cpu/yabo-data-skills --skill pg-function-craft
```

CLI 支持仓库自动发现时，可省略 `--skill`，再由提示选择 `pg-function-craft`：

```bash
npx skills add gyb-cpu/yabo-data-skills
```

仓库为公有仓库，匿名拉取不需要 GitHub 登录；安装时不要添加 `-g`，除非明确需要所有项目共用。

### 手动复制

不使用 CLI 时，把本目录整体复制到目标 Agent 的 Skill 目录，路径以该 Agent 的文档为准。安装目录中必须包含 `SKILL.md`、`references/`、`scripts/`、`tests/` 和 `assets/`。

### 手动验证安装

在 Skill 根目录执行：

```bash
python scripts/verify_offline.py --json
```

预期结果：`ok: true`、`database_connected: false`、`issues: []`。版本号和变更记录由 `SKILL.md` 与 `CHANGELOG.md` 提供。

## 使用

直接描述任务即可，Skill 会进入对应模式：

| 需求 | 模式 | 示例 |
|---|---|---|
| 新写函数、过程或触发器函数 | `generate` | “写一个按日期范围落表的 PG 函数” |
| 优化或重写已有函数 | `rewrite` | “按 pg-function-craft 重写这个函数，保持行为不变” |
| 检查安全、正确性、性能和风格 | `review` | “审查这个函数的性能和 SQL 写法” |

建议同时提供：

- 函数完整定义；
- PostgreSQL / Greenplum 版本；
- 目标表 DDL、索引、分区和分布键；
- 参数、返回值和错误契约；
- 数据量、日期范围和并发场景；
- 如需性能结论，提供用户在目标库执行的计划文本。

没有这些信息时，Skill 会把缺口列为 `Assumptions` 或“待确认项”，不会猜列类型、索引或业务规则。

## 固定风格

生成和改写默认遵循：

- 函数名：`f_` + 小写 `snake_case`；参数：`p_`；局部变量：`v_`；
- 在 `AS $function$` 之后、`DECLARE`/`BEGIN` 之前放中文八字段头：`name / function / input / output / increment / author / CreateDate / UpdateDate`；
- 前置逗号、4 空格缩进、关键字大写、显式列清单；
- 集合式 SQL 优先；循环必须有明确理由、行数上界和批量策略；
- 单条语句使用 CTE 或子查询；临时表只有在跨语句复用、昂贵计算复用、隔离/分批等情况下才物化；
- 日期过滤保持列侧裸露：`col >= p_start::date`，不写 `col::date >= ...`；
- 默认 `SECURITY INVOKER`；动态值使用 `USING`，标识符使用 `%I` 或白名单；
- 保持原函数的签名、返回值、异常文本、事务边界和外部行为，除非用户明确批准变更。

完整规则见：

- `references/04-固定风格.md`
- `references/05-重写协议.md`
- `references/06-SQL排版规范.md`
- `references/09-工程与函数结构规范.md`
- `references/10-PLpgSQL语法与函数形态.md`

## 性能边界

本 Skill 默认：

- 不读取 `conf.txt`、`.env` 或连接凭据；
- 不连接数据库；
- 不执行 SQL、函数、DDL、DML、`ANALYZE`、`VACUUM` 或 `EXPLAIN`；
- 只根据 SQL 文本、用户提供的 DDL 和用户提供的计划文本做静态分析。

因此性能结论只能使用：

```text
static-risk | inferred | plan-required | workload-required | not verified
```

不得仅凭 SQL 文本声称“更快”。重点检查：

- 列侧函数或类型转换是否破坏可搜索性；
- 临时表是否有明确物化理由；
- 是否重复扫描、重复聚合或循环内执行 SQL；
- 多源宽表的驱动键是否覆盖所有能独立提供目标业务键的源，是否把纯补列源误当作驱动源；
- 是否先列出函数、执行模式、源表、业务粒度和读取/物化路径；
- 合同派生表是否在聚合前下推日期窗口和业务域交易单元过滤，并保留外层交易单元与有效期精确匹配；
- 稀疏变更是否按实际日期/月集合覆盖，DELETE 与重建是否共用集合；
- 主源有效值（含真实 0）是否阻断对应备用聚合，是否保留备用独有键与冲突规则；
- 是否在低粒度复用公共关联；固定高粒度目标表是否由各源先产出目标粒度，最终只做统一关联且不重复 24→96 展开；单次转存的临时表是否有物化理由；
- 是否为 SQL 可直接表达的源存在性检查增加 `to_regclass` 变量或无必要计数变量；是否保留 `v_changed_dates date[]`；
- 无指标文档依据的备用源是否从增量推导、临时表、驱动键和注释中整链删除；合同是否按交易单元与有效期关联；宽表目标列与 `SELECT` 列是否逐列注释对应；
- DELETE 范围是否与重建范围一致；
- 动态 SQL 是否可参数化；
- PostgreSQL 9.4 / Greenplum 6.6 是否支持所用语法。

性能规则见 `references/07-性能优化规则.md`，审查分级见 `references/08-PostgreSQL审查规则.md`。

## 输出格式

### generate

```text
假设与缺失输入 → SQL → 静态验证 → 风险与未验证项 → 规则自检
```

### rewrite

```text
假设与缺失输入 → diff/改写后 SQL → 改动表 → 行为等价声明 → 性能风险
```

### review

```text
问题表（级别/规则/位置/证据/后果/建议）→ 结论 → 未验证项 → 待补输入
```

## 文件说明

```text
SKILL.md                         主规则与触发入口
assets/pg-function-craft-hero.svg 仓库图示
references/00-风格与边界.md      安全边界、输入边界和静态分析限制
references/01-基线规范.md        安全、正确性和事务底线
references/02-反模式.md          常见安全、正确性和性能风险
references/04-固定风格.md        固定命名、结构和 SQL 写法
references/05-重写协议.md        改写和行为等价规则
references/06-SQL排版规范.md     缩进、换行、关键字和注释
references/07-性能优化规则.md    静态性能检查
references/08-PostgreSQL审查规则.md 审查分级和证据格式
references/09-工程与函数结构规范.md 权限、事务和工程结构
references/10-PLpgSQL语法与函数形态.md 语法和版本边界
references/11-增量与水位线.md    按更新时间增量、回看窗、稀疏变更集合与水位线
scripts/verify_offline.py        离线完整性、版本与结构检查
scripts/check_sql_output.py      SQL 输出规则检查
scripts/verify_output_contract.py 模式输出契约校验
CHANGELOG.md                     版本变更记录
tests/README.md                  验收场景
tests/test_output_contract_modes.py 输出契约回归测试
```

本目录不携带个人样例、风格档案、数据库连接信息或导出元数据。

当前技能版本：`0.5.0`。变更记录见 `CHANGELOG.md`。

`00`、`01` 与 `05` 的条目没有编号，按“文件名 + 小节名”引用（如“`00-风格与边界.md` 的
冲突优先级”）；`04` 的条目使用 `STYLE-01`…`STYLE-10`。

## 证据标签

本技能自身不产生实测性能结论。所有性能陈述只能使用下面五个标签之一，不得自造标签，
也不得用“静态检查通过”暗示性能已确认：

| 标签 | 含义 |
|---|---|
| `static-risk` | 仅凭 SQL 文本即可判定的风险 |
| `inferred` | 按通用规则推断，缺少本环境证据 |
| `plan-required` | 需要用户侧执行计划才能判定 |
| `workload-required` | 需要真实负载与统计信息才能判定 |
| `not verified` | 尚未验证，不下结论 |

## 排版速查表

完整规则见 `references/06-SQL排版规范.md`，这里只列默认值速查。

| 项目 | 默认值 |
|---|---|
| 缩进 | 4 空格，禁用 tab |
| 行宽 | 80–100 列，默认不超过 100；中文按 2 列计 |
| 关键字 | SQL 与 PL/pgSQL 关键字大写（含 `LANGUAGE`）；类型、内置函数、语言名 `plpgsql` 小写 |
| 逗号 | 前置逗号（`,col`），列表最后一项不带逗号；CTE 之间用 `),` |
| 对齐 | 单个空格分隔，不用多空格做列对齐 |
| 语句 | 一条语句一个 `;`，语句之间最多 1 个空行 |
| 函数体 | 统一 `$function$` 标签，`DECLARE`/`BEGIN`/`EXCEPTION`/`END` 分段 |
| 头部 | 放在 `AS $function$` 之后、`DECLARE`/`BEGIN` 之前的中文八字段块注释 |
| 日期谓词 | 列侧裸露：`col >= p_start::date`，不写 `col::date >= ...` |

模板：

```sql
CREATE OR REPLACE FUNCTION demo.f_demo(p_start date)
RETURNS bigint
LANGUAGE plpgsql
AS $function$
/*****************************************************************
*name       : demo.f_demo
*function   : 演示函数
*input      : p_start 起始日期
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
