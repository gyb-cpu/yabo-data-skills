# PostgreSQL 审查规则（参考来源整理）

本文件是「审查层」的规范来源接入，把公开社区审查清单整理成可执行的 `REV-*` 规则，供 `review`
模式与 `rewrite` 的自检使用。

- 规则性质：`normative`（规范要求）；来源类型：`reference`（外部参考）。
- 本文件**不针对任何个人或语料**，不产生 `observed` 结论，也不附带任何语料计数或置信度。
- 本文件**没有运行**任何数据库、`EXPLAIN`、`pgFormatter`、`SQLFluff` 或外部审查工具；
  不声称任何问题“已复现”、任何改写“已验证更快”。
- 与 `references/01-基线规范.md`、`references/02-反模式.md` 冲突时，以它们为准；本文件只补充
  “审什么、按什么级别、需要什么证据”。排版问题仍由 `references/06-SQL排版规范.md` 的 `F-xx`
  定义，本文只负责把它归入最低级别。

## 0. 使用边界

### 0.1 审查对象

- 主对象：`CREATE FUNCTION` / `CREATE PROCEDURE`（目标引擎支持时）/ 触发器函数，以及函数体内的
  SQL 与 PL/pgSQL。
- 附带对象：函数直接依赖的表 DDL、索引、权限、调用方式与并发假设。没有这些输入时，相关问题只能
  标为“待补输入”，不能下结论。
- 不审：业务口径是否正确、数据本身是否可信、未提供的调用方代码、未提供的负载与容量规划。

### 0.2 证据地位

| 结论类型 | 标记 | 本文件能否直接给出 |
|---|---|---|
| 用户当次输入中可见的事实 | `observed` | 能；只描述输入现状，不作为风格规则来源 |
| 规范要求 | `normative` | 能；本文规则默认属于此类 |
| 未验证 | `unverified` | 能；凡缺 schema、计划或负载证据的推断 |
| 外部参考 | `reference` | 能；但必须注明来源，不得伪装成样例证据 |

写法要求：审查意见里引用外部来源时写“参考来源建议”，不要写“个人习惯”“来源证明”。

### 0.3 版本前提

目标基线为 **PostgreSQL 9.4 / Greenplum 6.6**。审查时先确认引擎与版本；未确认时按 GP 兼容
处理，并把现代语法列为待确认项。版本标记沿用 `07-性能优化规则.md` §0.3：
`[9.4]`、`[9.5+]`、`[9.6+]`、`[10+]`、`[11+]`、`[12+]`、`[13+]`、`[14+]`、`[15+]`、
`[GP-待验证]`、`[待验证]`。

### 0.4 来源登记

| 编号 | 来源 | 取用内容 | 状态 |
|---|---|---|---|
| SRC-1 | supabase/agent-skills → `skills/supabase-postgres-best-practices` | 索引、统计、批量写入、锁、RLS 性能、监控 | 已读取；平台假设需降级 |
| SRC-2 | github/awesome-copilot → `skills/postgresql-code-review`、`skills/postgresql-optimization` | 审查领域清单、JSONB/数组、函数与触发器检查 | 已读取；示例含 11+ 语法 |
| SRC-3 | claude-dev-suite → `skills/databases/plpgsql`、`skills/databases/postgresql` | 函数形态、异常、动态 SQL、触发器、索引速查 | 已读取；示例与本技能基线有冲突 |
| SRC-4 | damusix/skills → `postgres-writing-guidelines` | 命名/类型体系、SARGability、索引、事务与锁、连接池、错误码、RLS 形态 | 已读取；位于 `damusix/skills` 仓库的 `postgres-writing-guidelines/` 子目录，非独立仓库；示例含现代 PG 语法 |

来源许可以各仓库 `LICENSE` 为准。本文件只提炼规则、改写表述，不整段复制原文；来源中的数字、
“最佳实践”与默认值不视为本技能已验证结论。

## 1. 审查流程与输出契约

### 1.1 顺序（不可交换）

1. **只读排版核对**：按 `06-SQL排版规范.md` 找 `F-xx` 偏差，记为 `STYLE-FMT`；只记录，不改写被审对象。
2. **安全**：`REV-S*`。确凿的注入、权限、`search_path` 问题直接 `BLOCKER`。
3. **正确性**：`REV-C*`。异常契约、NULL/空结果、删除范围、事务边界、触发器返回值。
4. **性能风险**：`REV-P*`，逐条落到 `PERF-xx` 与证据标签（五选一：`static-risk` / `inferred` /
   `plan-required` / `workload-required` / `not verified`）。
5. **结构与可维护性**：`REV-M*`。
6. **方言与版本**：`REV-D*`。放在最后是因为它决定前几步的规则是否适用（例如 RLS、`ON CONFLICT`）。
7. **结论**：问题表 → 结论 → 性能标签与未验证项 → 待补输入。

排版核对必须在最前，因为格式统一后行号才稳定；但排版通过不改变后续任何结论。

### 1.2 输出骨架

```markdown
| 级别 | 规则 ID | 位置 | 证据 | 后果 | 整改建议 |
|---|---|---|---|---|---|
| BLOCKER | REV-S01 | demo.sql:42 | ... | ... | ... |

【结论】
【性能标签与未验证项】
【需要 schema / 执行计划 / 负载 / 人工确认的事项】
```

- `位置` 用 `文件:行号` 或函数名 + 行号；动态 SQL 还要给生成文本的采集方式。
- `证据` 只写看得到的内容：语句、变量、DDL、目录查询结果。不要写“应该是”。
- `后果` 区分“确定的错误/风险”与“需要验证的风险”。
- `整改建议` 给最小改动；涉及契约变更时标注“需批准”。

### 1.3 没有项目风格说明时

只对照 `01-基线规范.md`、`02-反模式.md` 与本文件。不要评价“像不像某个人的写法”，也不要因为缺少
项目风格说明而放过安全与正确性问题。

## 2. 严重级别

| 级别 | 使用条件 | 典型例子 | 不能用于 |
|---|---|---|---|
| `BLOCKER` | 已确凿的安全/正确性缺陷，或已证实的严重性能问题（有 `EXPLAIN`/负载证据） | 值拼接进动态 SQL；definer 无 `search_path`；`WHEN OTHERS THEN NULL`；9.4 用了 `ON CONFLICT` | 仅凭代码形状猜测的慢；没有 schema 的删除范围推断 |
| `WARNING` | 需要 schema、计划、负载或人工确认的风险；契约可能不成立 | 缺索引；过滤列套函数；0 行语义不清；临时表残留 | 已确认会报错/丢数据的缺陷（应升 `BLOCKER`） |
| `INFO` | 可维护性、可读性、一致性建议，不影响正确性 | 函数职责过多；命名不统一；注释缺失 | 安全问题（不能降级为 INFO） |
| `STYLE-FMT` | 仅排版偏差（`F-xx`） | 缩进、关键字大小写、逗号位置 | 任何语义、性能、安全问题 |

升级/降级规则：

- `WARNING` → `BLOCKER`：拿到 schema/计划/负载证据，确认会丢数据、越权、报错或严重退化。
- `BLOCKER` → `WARNING`：只有确认该路径不可达或已被外部约束兜住，并写明理由；不得因为“以前一直这样”降级。
- 安全问题不得降为 `INFO`；性能问题不得因为“看起来更快”升为 `BLOCKER`。
- `STYLE-FMT` 永远最低，不与语义问题混排；也不因为格式整齐而放过语义缺陷。

## 3. 安全规则（REV-S）

| ID | 检查点 | 默认级别 | 证据要求 | 整改方向 |
|---|---|---|---|---|
| REV-S01 | 动态 SQL 把参数值拼进字符串 | `BLOCKER` | 展示拼接语句与进入文本的变量 | 值用 `EXECUTE ... USING`；字面量用 `%L` |
| REV-S02 | 标识符（表/列/schema）拼接未引用或未白名单 | `BLOCKER` | 展示 `format` 或字符串连接的标识符来源 | `format('%I', ...)`、白名单、系统目录校验 |
| REV-S03 | `SECURITY DEFINER` 未固定 `search_path` | `BLOCKER` | 函数头与 `pg_proc.proconfig` | `SET search_path = pg_catalog, <trusted>, pg_temp` |
| REV-S04 | `search_path` 含不可信 schema、顺序错误、只写“排除 pg_temp” | `BLOCKER` | 列出实际 `search_path` | 显式列受信 schema；`pg_temp` 放最后；对象全限定 |
| REV-S05 | definer 函数对 `PUBLIC` 开放 `EXECUTE` 或权限过宽 | `WARNING`（与 S03/S04 同现时 `BLOCKER`） | `pg_proc.proacl`、`GRANT` 记录 | `REVOKE ... FROM PUBLIC`；按角色最小授权 |
| REV-S06 | 应用使用 superuser/owner 连接，或 `GRANT ALL` 到宽范围 | `WARNING` | 角色与授权语句 | 拆分读写角色；只授必要对象与序列 |
| REV-S07 | 依赖 RLS 但目标不支持或策略缺失 | `WARNING`；9.4/GP 标“不适用” | 版本 + `pg_policies`（9.5+） | 9.5+ 才评估；9.4 用视图/权限/入口校验 |
| REV-S08 | 敏感值进入 `RAISE`、异常文本、注释、动态 SQL 日志 | `WARNING` | 展示输出语句与变量 | 改 `RAISE DEBUG`；只打印长度/谓词摘要；脱敏 |

补充判断：

- `REV-S01`/`REV-S02` 的关键不是“用了 `EXECUTE`”，而是“值/标识符是否与 SQL 文本分离”。
  静态上无法证明安全时，按 `BLOCKER` 处理，直到看到 `USING`/`%I`/白名单。
- `REV-S03`/`REV-S04` 只在 `SECURITY DEFINER` 下是安全问题；`SECURITY INVOKER` 下同样的
  `search_path` 问题降为 `WARNING`（仍可能影响解析与性能）。
- `REV-S05` 需要实际 ACL；`pg_get_functiondef` 不导出 `GRANT`/`REVOKE`，文本里没有授权语句
  不能证明未授权。
- `REV-S07`：RLS 是 `[9.5+]`；Greenplum 6.6 的支持情况 `[GP-待验证]`。不要把 Supabase 的
  `auth.uid()` 策略照搬到本技能；本技能没有该函数。
- `REV-S08`：`RAISE INFO '%', v_sql` 会打印参数值（见 `AP-09`）；生产路径不得保留。

## 4. 正确性规则（REV-C）

| ID | 检查点 | 默认级别 | 证据要求 | 整改方向 |
|---|---|---|---|---|
| REV-C01 | `WHEN OTHERS` 把错误变成 NULL/空结果/提示/假成功 | `BLOCKER` | 展示 handler 与返回路径 | 只捕获可恢复条件；兜底用 `RAISE;` 重抛 |
| REV-C02 | 捕获后丢失 `SQLSTATE`、出错语句、参数上下文 | `WARNING` | handler 文本 | `GET STACKED DIAGNOSTICS`；`RAISE ... USING ERRCODE` |
| REV-C03 | volatility 与实际行为不符（读表/时间/随机却 `IMMUTABLE`） | `BLOCKER`（确定误标）；否则 `WARNING` | 函数体依赖 + 声明 | 改 `VOLATILE`/`STABLE`；`IMMUTABLE` 仅在可证明时 |
| REV-C04 | 参与谓词的参数未校验 NULL/空串/区间倒置 | `WARNING` | 入口分支 + 头部契约 | 显式校验；失败返回约定错误码并说明原因 |
| REV-C05 | 把 0 行当成功或失败条件 | `WARNING` | `ROW_COUNT`/返回路径 | 用 `GET DIAGNOSTICS` 或落表后计数；0 行可合法 |
| REV-C06 | `DELETE`/`TRUNCATE` 范围大于可重建范围 | `BLOCKER` | 删除谓词 + 插入来源 + 业务键 | 带谓词；整表刷新显式声明范围与恢复边界 |
| REV-C07 | 临时表同会话重入/残留/命名冲突 | `WARNING` | 建表/清理路径 + 调用模式 | `ON COMMIT DROP` 或显式 `DROP`；业务前缀 |
| REV-C08 | 函数内使用 `COMMIT`/`ROLLBACK`，或假设自治事务 | `BLOCKER`（9.4 语法错误） | 函数体 | 事务交给调用方；过程 `[11+]` 才能控制事务 |
| REV-C09 | 触发器函数返回值错误（`BEFORE` 行级未返回 `NEW`/`OLD`） | `BLOCKER` | `RETURN` 路径 + 触发器类型 | 按 `TG_OP` 返回 `NEW`/`OLD`；跳过操作用 `RETURN NULL` |
| REV-C10 | 幂等/重跑声明不成立（日期窗、序列、外部副作用） | `WARNING` | 整次调用的输入与副作用 | 按整次调用声明可重跑性；列出不可回滚项 |
| REV-C11 | 异常文本/函数名与自身不符，副本未改名 | `WARNING` | 重抛文本 + 函数名 | 同步改名；用 `SQLSTATE` 而非文本分支 |
| REV-C12 | 改写改变了签名、返回类型、错误文本形状或返回码语义 | `BLOCKER`（未获批时） | 前后对照 | 保持外部契约；变更需批准并给迁移方案 |
| REV-C13 | 时间语义混用：`now()`/`transaction_timestamp()` 与 `clock_timestamp()` 不分，`timestamp` 与 `timestamptz` 混用，`date` 与午夜时间戳互转 | `WARNING` | 列类型 + 取值语句 + 比较谓词 | 写明“事务开始时间/真实时钟/日期”的意图；改类型需批准（`REV-C12`） |
| REV-C14 | 错误靠消息文本分支，或自定义 `SQLSTATE` 未目录化 | `INFO`（调用方依赖文本时 `WARNING`） | 异常文本 + 调用方匹配方式 | 用 `SQLSTATE` 目录（如 `P0001`～`P0999`）；文本只作人类可读信息 |
| REV-C15 | 无指标文档依据的备用源仍残留在增量推导、临时表、驱动键或注释路径 | `WARNING`；确认会改变结果时 `BLOCKER` | 指标文档、源表引用、驱动键和增量路径对照 | 删除备用源的整条血缘链，不只删最终 `SELECT` |
| REV-C16 | 合同基础信息未按交易单元和有效期关联/聚合，只按 `contract_id` 全表取最大周期 | `WARNING`；确认跨主体/跨期间串值时 `BLOCKER` | 关联键、有效期列、聚合粒度 | 使用交易单元等值关联和目标日期落在合同有效期内 |
| REV-C17 | 删除稀疏增量必需的 `v_changed_dates date[]`，或用过度格式校验替代既定日期契约 | `WARNING`；确认漏删/漏建时 `BLOCKER` | `p_flag` 分支、数组使用点、参数契约 | 保留实际变更日期集合；只做必要转换和区间顺序校验 |

补充判断：

- `REV-C01` 与 `REV-C02` 的区别：前者是“吞掉/伪造成功”，后者是“重抛但丢上下文”。常见的
  `WHEN OTHERS THEN RAISE EXCEPTION '<fn>: %', SQLERRM` 属于后者（`AP-02`），不要误判为 `C01`。
- `REV-C03`：只读函数保持默认 `VOLATILE` 不是缺陷；`STABLE` 是优化器提示，不要仅因“只读”强制改。
- `REV-C05`：0 行可以是合法结果（空日期区间、源表无增量）；只有业务契约要求区分“无数据/失败”时
  才需要行数校验。
- `REV-C06`：判断依据是“删除范围 vs 可重建范围”，不是“有没有显式事务”。函数体的 `DELETE` 与
  `INSERT` 在调用方事务（或异常块子事务）内，未捕获异常会回滚；真正风险是范围不一致，或把
  `DELETE` 放块外、把易失败的 `INSERT` 放块内吞掉异常后返回成功。
- `REV-C09`：`BEFORE` 行级触发器返回 `NULL` 会跳过该行操作；`AFTER` 行级返回值被忽略，但仍应
  返回 `NEW`/`OLD` 以保持一致；语句级触发器返回值被忽略，不要依赖它。

## 5. 性能规则（REV-P）

本组规则只给“检查点 + 证据档”，具体判据与版本门槛见 `07-性能优化规则.md` 的 `PERF-xx`。

| ID | 检查点 | 对应 PERF | 默认级别 | 默认证据档 |
|---|---|---|---|---|
| REV-P01 | 循环内逐行查询/DML/DDL | `PERF-12`、`PERF-11` | `WARNING` | `workload-required` |
| REV-P02 | 过滤/连接列上套函数或隐式 cast，索引可能失效 | `PERF-29`、`PERF-04` | `WARNING` | `plan-required` |
| REV-P03 | 缺索引、复合索引列序错误、部分/表达式索引不匹配 | `PERF-01`～`PERF-05` | `WARNING` | `plan-required` |
| REV-P04 | `SELECT *`、无界结果、集合返回未限制 | `PERF-22` | `WARNING` | `plan-required` + `workload-required` |
| REV-P05 | 临时表 staging 无统计、无清理、分布不当 | `PERF-23` | `WARNING` | `workload-required` |
| REV-P06 | 深 `OFFSET` 分页 | `PERF-13` | `WARNING` | `plan-required` |
| REV-P07 | 动态 SQL 未参数化、计划/文本膨胀 | `PERF-19` | `WARNING` | `plan-required` |
| REV-P08 | 审查意见或改动说明声称“更快”但无证据 | `PERF-28` | `WARNING` | 报告级 |
| REV-P09 | 行级触发器内做查询/写入，批量写入放大 | `PERF-25` | `WARNING` | `workload-required` |
| REV-P10 | 把 PG 的计划/索引结论套到 GP，或反向 | `PERF-26` | `WARNING` | `plan-required` + `workload-required` |
| REV-P11 | 稀疏增量用连续 `min/max` 区间，或删除/重建集合不一致 | `PERF-47`、`INC-14` | `WARNING`；确认丢行时 `BLOCKER` | `static-risk` + `plan-required` |
| REV-P12 | 同源同窗口重复过滤/关联/聚合，或公共关联在高粒度重复展开 | `PERF-48` | `WARNING` | `static-risk` + `plan-required` |
| REV-P13 | 主源真实 `0` 未阻断备用聚合，或主备短路后丢失备用独有键/冲突规则 | `PERF-49` | `WARNING`；确认结果错误时 `BLOCKER` | `static-risk` |
| REV-P14 | 单次引用的暂存无物化理由，或可复用结果被重复转存 | `PERF-50` | `WARNING` | `static-risk` + `plan-required` |
| REV-P15 | 可独立提供目标业务键的源只出现在 `LEFT JOIN` 补列侧，未进入驱动键集合 | `PERF-52` | `WARNING`；确认漏行时 `BLOCKER` | `static-risk` |
| REV-P16 | 目标粒度转换留到最终层，或最终 `SELECT` 重复执行 24→96 等展开 | `PERF-53` | `WARNING`；确认重复计算或结果异常时 `BLOCKER` | `static-risk` + `plan-required` |
| REV-P17 | 合同派生表先全表按 `contract_id` 聚合，日期窗口和业务域交易单元过滤只在外层 `ON` 中出现 | `PERF-54` | `WARNING`；确认无关合同被聚合或结果串值时 `BLOCKER` | `static-risk` + `plan-required` |
| REV-M10 | ETL 审查缺少函数/执行模式/源表/粒度/物化路径或离线边界核对 | `PERF-51`、`INC-14` | `INFO`；阻碍行为判断时 `WARNING` | `not verified` |
| REV-M11 | 为 SQL 可直接表达的源存在性检查增加 `to_regclass` 变量，或为简单无映射告警增加无必要计数变量 | `ENG-25` | `INFO` | `static-risk` |
| REV-M12 | 临时表上方缺少数据类型、物化理由/复用位置或生命周期说明 | `ENG-27` | `INFO`；影响复用或清理判断时 `WARNING` | `not verified` |
| REV-M13 | 宽表 `INSERT` 的目标列与 `SELECT` 列缺少逐列对应注释，难以审查字段顺序 | `ENG-30` | `INFO` | `not verified` |

写法要求：

- `REV-P01`、`REV-P02`、`REV-P03` 只能写“风险 + 待验证”，不能写“慢”。
- 要升级为 `BLOCKER`，必须有 `EXPLAIN (ANALYZE, BUFFERS)` 或负载证据，并写明快照。
- 性能问题不因“既有代码一直这样写”而降级；也不因“新写法更现代”而升级。
- `REV-P08` 针对的是结论，不是代码：任何“优化”说明都必须带 `README.md` §7 的标签。
- 多源宽表审查时必须自问：**如果除这张表以外的源在该日期全空，目标表还出数吗？** 对每个仅出现在 `LEFT JOIN` 侧的源，先确认它是否能独立提供完整目标业务键；能提供且未进入驱动集合时，报 `REV-P15`。纯补列源不适用该规则。
- 固定高粒度目标表还要自问：**24→96 是否已经在各源路径完成，最终层是否只剩统一关联？** 若最终 `SELECT` 仍对多个字段重复 `CASE`/四拆分或再次关联时间维表，报 `REV-P16`。
- `07-性能优化规则.md` 的规则集可继续扩展（当前已到 `PERF-54`）；`REV-P*` 是最小审查映射，
  不要求为每条 `PERF-xx` 单列一条审查规则。引用新增 `PERF` 规则时，按同类的证据档处理。

## 6. 结构与可维护性（REV-M）

| ID | 检查点 | 默认级别 | 说明 |
|---|---|---|---|
| REV-M01 | 单个函数承担过多职责（巨型 `p_type` 分派、多个目标表） | `INFO` | 可拆则拆；不能拆时写明分支契约与测试边界 |
| REV-M02 | 命名不一致（函数/参数/变量/游标在同一仓库内不统一） | `INFO` | 只判一致性，不判前缀；前缀缺失属 `STYLE-01`，无项目约定时按 `04-固定风格.md` |
| REV-M03 | 头部注释缺失、字段漂移、与代码不符 | `INFO`（契约字段不符时 `WARNING`） | 头部承诺的返回码/参数必须与实现一致 |
| REV-M04 | 硬编码 schema/库名（`db_<省>`、`dw_<省>`） | `WARNING` | 换环境即失效；集中配置或参数化（`AP-07`） |
| REV-M05 | 复制副本残留（`_copyN`、重复函数体、异常文本未改） | `WARNING` | 与 `REV-C11` 联动 |
| REV-M06 | 排版偏差 | `STYLE-FMT` | 只记 `F-xx`，不与语义问题混排 |
| REV-M07 | 依赖未声明（扩展、schema、外部表） | `WARNING` | 9.4 上扩展可用性需确认；GP `[GP-待验证]` |
| REV-M08 | 只授对象权限、未授 schema `USAGE`，或未来对象未设默认权限 | `WARNING` | `USAGE` 与 `SELECT`/`EXECUTE` 必须同时具备；`ALTER DEFAULT PRIVILEGES` 按需 |
| REV-M09 | 命名与项目约定冲突（外部来源建议 `fn_*`/`pr_*`，本技能可能用 `f_*`/`p_*`） | `INFO` | 命名是风格，不是安全；以项目书面约定为准，不因外部来源改名 |

## 7. 方言与版本（REV-D）

| ID | 检查点 | 默认级别 | 说明 |
|---|---|---|---|
| REV-D01 | 使用 9.4 不支持的语法 | `BLOCKER` | 见 §7.1 门槛表 |
| REV-D02 | 触发器写成 `EXECUTE FUNCTION` | `BLOCKER`（9.4/GP 6.6） | 9.4 用 `EXECUTE PROCEDURE`；`EXECUTE FUNCTION` 为 `[11+]` |
| REV-D03 | `ON CONFLICT`、`SKIP LOCKED`、`GROUPING SETS`、`GENERATED AS IDENTITY`、`CREATE PROCEDURE` | `BLOCKER` | 分别 `[9.5+]`、`[9.5+]`、`[9.5+]`、`[10+]`、`[11+]` |
| REV-D04 | GP 专属语法混入通用模板 | `WARNING` | `DISTRIBUTED BY`、`SPLIT DEFAULT PARTITION`、`EXCHANGE PARTITION`、`WITH (appendonly=...)` |
| REV-D05 | PG ↔ GP 结论互推（索引、分区裁剪、CTE、并行、统计） | `WARNING` | 见 `07` §7.5 |
| REV-D06 | 版本相关列名/函数照抄现代示例 | `WARNING` | 如 `total_exec_time`、`wait_event`、`pg_stat_progress_vacuum` |

### 7.1 9.4 / GP 6.6 语法门槛

**版本事实只有一份：`10-PLpgSQL语法与函数形态.md` §1.1。** 本节不重复特性清单，只定义
“查到了之后怎么定级”。

- 目标版本不支持、且代码已使用该特性 → `BLOCKER`（`REV-D01`）。
- 只影响诊断脚本或统计列名（如 `pg_stat_progress_vacuum`、`wait_event`、`EXPLAIN (WAL)`、
  `total_exec_time`）→ `WARNING`。
- `[GP-待验证]` 的项（GIN/GiST、`BUFFERS` 实际输出、`pg_stat_statements`、RLS、AO 表维护、
  `CREATE INDEX CONCURRENTLY`）不得按社区 PG 直接判 `BLOCKER`；先确认目标集群，再定级。
- 版本未声明时，按 9.4 / GP 6.6 保守判定，并在结论里写明这是假设。

`CREATE INDEX CONCURRENTLY`：PG 9.4 可用，GP 6.6 文档明确不支持，且在 PG 中也不能放进
事务块/函数内（与 `07` §2.4 一致）。审查时按“PG 9.4 可用、GP 待确认”处理。

## 8. 参考来源的已知偏差（必须纠正）

以下不是“来源错了所以整体不可用”，而是“来源假设了更新的 PG 或特定平台”，移植时必须降级。

### 8.1 SRC-1（Supabase）

| 来源写法/假设 | 偏差 | 本技能处理 |
|---|---|---|
| `auth.uid()`、`auth.role()`、`service_role` | Supabase 平台函数/角色 | 本技能没有；用调用方身份参数或 `current_user` |
| `CREATE POLICY ... USING ((select auth.uid()) = user_id)` | RLS 为 `[9.5+]` | 9.4/GP 6.6 不适用；不要写进通用模板 |
| `SET search_path = ''` | 需要全限定对象；与基线不同但可接受 | 二选一：空 `search_path` + 全限定，或 `pg_catalog, <trusted>, pg_temp` |
| `CREATE INDEX ... INCLUDE` | `[11+]` | 9.4 用多列索引 |
| BRIN 索引 | `[9.5+]` | 9.4 不可用 |
| `ON CONFLICT` | `[9.5+]` | 9.4 不可用 |
| `SKIP LOCKED` | `[9.5+]` | 9.4 不可用 |
| `total_exec_time`/`mean_exec_time` | `[13+]` | 9.4 用 `total_time`/`mean_time` |
| `pg_stat_progress_vacuum` | `[9.6+]` | 9.4 不可用 |
| “快 100–1000 倍”等数字 | 来源主张 | 不写进结论；只作为待验证假设 |
| RLS 策略里 `SECURITY DEFINER` 辅助函数 | 需要 `search_path` + `REVOKE EXECUTE` | 与 `REV-S03`/`REV-S05` 一致；不要省略 |

### 8.2 SRC-2（awesome-copilot）

| 来源写法/假设 | 偏差 | 本技能处理 |
|---|---|---|
| `CREATE TRIGGER ... EXECUTE FUNCTION` | `[11+]` | 9.4 用 `EXECUTE PROCEDURE`（`REV-D02`） |
| `BIGSERIAL` | 可用，但不是唯一方案 | 既有契约优先；不要为“现代”改 identity（`[10+]`） |
| `CITEXT` | 需要扩展；GP 可用性 `[GP-待验证]` | 不在通用模板默认启用；先确认扩展 |
| `ENUM` / `DOMAIN` | 9.4 可用，但变更成本高 | 可作为建模建议，不作为函数审查的阻断项 |
| `data @> '{"status": "shipped"}'` + GIN | jsonb/GIN 在 9.4 可用；GP `[GP-待验证]` | 先确认 GP 支持，再评估 |
| `CREATE INDEX ... USING gin((data->'status'))` | 表达式 GIN 的可用性依赖操作符类 | 优先 `@>` 包含查询；表达式索引需 `plan-required` |
| `WHEN (OLD.* IS DISTINCT FROM NEW.*)` | 9.4 可用；逐行求值有成本 | 可作为触发器优化建议，需 `workload-required` |
| `PARALLEL SAFE` | `[9.6+]` | 9.4 不写 |
| RLS 示例 | `[9.5+]` | 9.4 标“不适用” |

### 8.3 SRC-3（claude-dev-suite）

| 来源写法/假设 | 偏差 | 本技能处理 |
|---|---|---|
| `AS $$ ... $$` | 与 `F-26` 冲突 | 统一 `$function$`；迁移需单独批准 |
| `SET search_path = public, pg_temp` | `public` 不可信、未显式列 `pg_catalog`、顺序不完整 | 用 `pg_catalog, <trusted>, pg_temp`；`public` 仅在受控时纳入 |
| `CREATE PROCEDURE ... COMMIT` | `[11+]` | 9.4 用函数；事务交给调用方 |
| `PARALLEL SAFE` | `[9.6+]` | 9.4 不写 |
| `ASSERT` | `[9.5+]` | 9.4 不写；用显式 `IF ... RAISE` |
| `ON CONFLICT` 示例 | `[9.5+]` | 9.4 不写 |
| `GENERATED AS IDENTITY` 相关 | `[10+]` | 9.4 用 `serial`/序列 |
| `EXECUTE` 字符串与 `quote_ident(...)` 直接拼接 | 标识符可用 `quote_ident`，值仍须绑定 | 值用 `USING`；标识符优先 `%I` |
| `SELECT INTO` 不写 `STRICT` | 可能吞掉 0 行/多行 | 需要“恰好一行”时用 `STRICT`（`REV-C05`/`PLS-05`） |
| `RETURNS SETOF users` + `SELECT *` | 列依赖与宽扫描 | 显式列或说明契约（`REV-P04`） |

### 8.4 SRC-4（damusix/skills）

上游实际位置是 `damusix/skills` 仓库根目录下的 `postgres-writing-guidelines/`，不是独立仓库
`damusix/postgres-writing-guidelines`（该路径返回 404）。本文件读取的是上游的 `SKILL.md` 与
`postgres-writing-guidelines/references/` 下的 `indexing.md`、`query-patterns.md`、
`procedure-structure.md` 等文件。它是一份
**应用数据库写作指南**，覆盖面比函数审查更宽；下表只取与函数/审查有关的部分。

| 来源写法/主张 | 偏差或风险 | 本技能处理 |
|---|---|---|
| 全部标识符 `snake_case`；函数 `fn_*`、过程 `pr_*`、触发器 `tg_*` | 与本技能可能使用的 `f_*`/`p_*`/`v_*` 命名不同；命名属于风格，不是安全规则 | 只作参考建议；以项目书面约定为准，不因外部来源改名 |
| 每列都用 `CREATE DOMAIN`，默认 `NOT NULL` | 9.4 支持 DOMAIN，但既有项目可能未使用；改类型体系是结构迁移 | 不在函数审查中强制；仅当用户要求类型治理时评估 |
| 一律用 `timestamptz`，不用 `timestamp` | 9.4 支持；但改既有列类型会改变契约与索引 | 只作为新表建议；既有函数改类型需批准（`REV-C12`） |
| `clock_timestamp()` 取真实时钟，`now()`/`transaction_timestamp()` 取事务开始时间 | 两者语义不同；混用会让同一次调用内的“现在”不一致 | 新增 `REV-C13`：要求写明时间语义，不强制换函数 |
| `GENERATED ALWAYS AS (...) STORED` | `[12+]` | 9.4/GP 6.6 不可用；用触发器或普通列 |
| `INSERT ... ON CONFLICT DO NOTHING` 播种参考表 | `[9.5+]` | 9.4 不可用；用 `DELETE`+`INSERT` 或捕获冲突 |
| `MERGE` | `[15+]` | 9.4 不可用；不要写进模板 |
| `FOR UPDATE SKIP LOCKED` 队列表 | `[9.5+]` | 9.4 不可用；用 `NOWAIT` + 重试（`REV-D03`） |
| `FOR NO KEY UPDATE` | 9.3+，9.4 可用 | 可作为减少锁强度的建议；需 `workload-required` 验证 |
| `pg_advisory_xact_lock` 替代会话锁 | 9.4 可用；事务级自动释放，池化更安全 | 与 `ENG-10` 一致；会话级锁在事务池下会泄漏 |
| `SET LOCAL app.user_id = ...` 传身份 | 9.4 可用；transaction 池化下会话 `SET` 会丢 | 审计时必须确认池化模式与身份来源 |
| `CREATE PROCEDURE`、过程内 `COMMIT` | `[11+]` | 9.4 不可用；事务交给调用方 |
| `CREATE TRIGGER ... EXECUTE FUNCTION` | `[11+]` | 9.4 用 `EXECUTE PROCEDURE`（`REV-D02`） |
| “没有显式 `SAVEPOINT` 就没有子事务” | 与 PL/pgSQL 行为不符：带 `EXCEPTION` 的块会建立子事务 | 以 `PLS-35`/`ENG-09` 为准；本文件不采纳该表述 |
| RLS + `CREATE POLICY` + `FORCE ROW LEVEL SECURITY` | `[9.5+]`；GP `[GP-待验证]` | 9.4/GP 6.6 标“不适用”；不要照抄 `fn_current_app_user_id()` |
| `citext`、`pg_trgm`、`pgcrypto`、`pg_cron`、`pgvector` | 扩展可用性依赖版本与安装；`pg_cron`/`pgvector` 不是 9.4 自带 | 先确认扩展清单；GP `[GP-待验证]` |
| UUID v7、生成列、`MERGE` | 现代特性 | 9.4 不可用；UUID 用 `uuid` 类型 + `gen_random_uuid()`（`pgcrypto`） |
| “测试用事务回滚” | 方法本身可借鉴 | 本文件不声称已运行测试；只作为验证建议 |
| 用 `pg_stat_user_indexes`/`EXPLAIN` 证明索引必要性 | 方向正确 | 与 `PERF-01`/`PERF-07` 一致；仍需快照与证据档 |

## 9. 问题表示例

以下示例只演示格式与级别，不含真实表名、人名、连接信息或生产数据。

| 级别 | 规则 ID | 位置 | 证据 | 后果 | 整改建议 |
|---|---|---|---|---|---|
| BLOCKER | REV-S01 | `demo/1001_f_demo.sql:57` | `v_sql` 用字符串连接把 `p_start` 拼进日期字面量 | 参数值进入 SQL 文本，存在注入与转义错误 | 改 `EXECUTE v_sql USING p_start`；日期用类型化参数 |
| BLOCKER | REV-S03 | 同文件 `:1-8` | `SECURITY DEFINER`，无 `SET search_path` | 调用方 `search_path` 可劫持对象解析 | 固定 `pg_catalog, demo, pg_temp`，对象全限定 |
| WARNING | REV-C04 | 同文件 `:22` | 头部承诺 `-1 参数异常`，无 `IS NULL` 校验 | `NULL` 会静默跑成空结果或全量 | 入口校验并返回 `-1`，说明原因 |
| WARNING | REV-P01 | 同文件 `:88-96` | `LOOP` 内逐行 `EXECUTE` | 往返与锁持有随行数放大 | 集合化到临时表；确需逐行时写明上界与批大小 |
| WARNING | REV-P03 | 同文件 `:40` | 过滤列 `created_at::date` 无表达式索引 | 可能全表扫描 | 用 `EXPLAIN` 验证；必要时建表达式索引 |
| STYLE-FMT | F-06 | 同文件 `:12` | 关键字小写 | 排版不一致 | 按 `06` 统一；仅记录，不改写被审对象 |

## 10. 审查完成检查清单

- [ ] 已确认目标引擎与版本（PG 9.4 / GP 6.6 / 其他），并标注 `[待验证]` 项。
- [ ] 已做只读排版核对，`STYLE-FMT` 单独成组，未改写被审对象。
- [ ] 安全问题逐条落到 `REV-S01`～`REV-S08`，`BLOCKER` 有可指认的语句/ACL/`proconfig` 证据。
- [ ] 正确性问题区分“吞异常”与“重抛丢上下文”，没有把 `AP-02` 误判为 `REV-C01`。
- [ ] `DELETE`/`TRUNCATE` 问题按业务范围判断，没有简化为“缺事务”。
- [ ] 性能问题全部带 `PERF-xx` 与五档证据标签（见 `README.md` 第 7 节）标签；没有“更快/更慢”的无证据结论。
- [ ] 9.4/GP 6.6 门槛表逐项核对：`ON CONFLICT`、`EXECUTE FUNCTION`、RLS、BRIN、`INCLUDE`、
      `SKIP LOCKED`、`CREATE PROCEDURE`、`ASSERT`、`PARALLEL`。
- [ ] 引用外部来源时写明“参考来源”，没有写成 `observed` 或个人习惯。
- [ ] 结论区分：已确认缺陷 / 需 schema / 需计划 / 需负载 / 需人工批准。
- [ ] 没有声称已运行工具或已验证性能。

## 11. 参考

- `references/01-基线规范.md`：安全、正确性、事务、临时表、性能默认值。
- `references/02-反模式.md`：`AP-01`～`AP-10`、`B-01`～`B-08`。
- `references/06-SQL排版规范.md`：`F-01`～`F-31`。
- `references/07-性能优化规则.md`：`PERF-xx`（当前 `PERF-01`～`PERF-51`）与五档证据标签（见 `README.md` 第 7 节）。
- `references/09-工程与函数结构规范.md`：`ENG-xx`。
- `references/10-PLpgSQL语法与函数形态.md`：`PLS-xx` 与版本门槛。
- supabase/agent-skills：<https://github.com/supabase/agent-skills>
- github/awesome-copilot：<https://github.com/github/awesome-copilot>
- claude-dev-suite：<https://github.com/claude-dev-suite/claude-dev-suite>
- damusix/skills，`postgres-writing-guidelines`：
  <https://github.com/damusix/skills/tree/main/postgres-writing-guidelines>
- PostgreSQL 9.4 文档：<https://www.postgresql.org/docs/9.4/>
- Greenplum 6.6 文档：<https://docs.greenplum.org/6-6/>

本文件的规则是审查提示，不是自动化断言。定级前必须看被审对象、DDL、权限与版本；没有证据时
写“待验证”，不要写“已确认”。
