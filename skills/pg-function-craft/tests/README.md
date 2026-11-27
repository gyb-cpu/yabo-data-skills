# 验收场景

本文件定义 pg-function-craft 的静态验收检查。**没有数据库、没有断言框架、没有网络**；所有检查
都通过阅读文本、运行离线脚本或人工对照完成。需要执行计划或负载数据的项目一律标为“用户侧
待验证”。

## 1. 目录与文件完整性

- [ ] 目录内不存在 `samples/`、`metadata/`、`风格档案.md`、`conf.txt`、`.env`。
- [ ] 不存在数据库驱动依赖或连库脚本；Python 文件仅限 `scripts/verify_offline.py`、
      `scripts/check_sql_output.py`、`scripts/verify_output_contract.py` 与 `tests/test_*.py`。
- [ ] `python scripts/verify_offline.py` 退出码为 `0`。
- [ ] `SKILL.md` 的 frontmatter `name` 为 `pg-function-craft`，描述中不含个人姓名、项目私有
      schema/表名、语料数量或来源统计。
- [ ] 模式只有 `generate` / `rewrite` / `review` 三种；没有从输入重新学习风格的入口。
- [ ] 固定风格只以规则条文存在，出处不指向任何个人、数据库或历史语料。
- [ ] 所有文本为 UTF-8 无 BOM、LF 换行、文件尾单个换行。

## 2. 固定风格

- [ ] 函数名 `f_` 前缀、全小写 `snake_case`；参数 `p_`，局部变量 `v_`。
- [ ] 函数头为函数体内中文八字段块（`*name`、`*function`、`*input`、`*output`、`*increment`、`*author`、
      `*CreateDate`、`*UpdateDate`），位于 `AS $function$` 之后、`DECLARE`/`BEGIN` 之前。
- [ ] `*author` 写团队名或明确占位符，没有出现真实个人姓名、原属主姓名或可反查个人的标识。
- [ ] 缩进为 4 空格；函数参数与 `SELECT` 列表使用前置逗号，同一文件没有混用尾逗号。
- [ ] 关键字大写、类型与内置函数小写；`LANGUAGE` 大写、语言名 `plpgsql` 小写。
- [ ] 子句关键字独占一行，`DECLARE`/`BEGIN`/`EXCEPTION`/`END` 分段，段注释 `-- 1.` 与语句
      同列。
- [ ] 默认 `SECURITY INVOKER`；出现 `SECURITY DEFINER` 时，`search_path` 显式列出且 `pg_temp`
      在最后。
- [ ] 动态 SQL 的值走 `USING`，标识符走 `%I`，字面量走 `%L`。

## 3. `generate` 场景

输入：一个落表函数需求，目标表 DDL 不全，用户要求“顺便优化性能”。

期望输出：

- [ ] 先给 `Assumptions` 与缺失输入（DDL、索引、行数、版本、权限），再给 SQL。
- [ ] 每条性能陈述带标签，且只使用 `static-risk` / `inferred` / `plan-required` /
      `workload-required` / `not verified`；没有“更快”“已验证”“实测通过”一类断言。
- [ ] 若引入临时表，逐张说明：为什么必须物化、被引用几次、生命周期、清理与失败路径。
- [ ] 若中间结果只引用一次，使用子查询或 CTE，没有为此新增临时表。
- [ ] 日期过滤写成 `col >= p_start::date`，没有 `col::date >= ...`；列已是 `date` 时没有冗余
      `::date`。
- [ ] 动态 SQL 的值走 `USING`，标识符走 `%I`。

## 4. `rewrite` 场景

输入：一个已有函数，含多张临时表和 `q.riqi::date >= ...` 形式的日期谓词。

期望输出：

- [ ] 签名、返回类型、返回码、异常文本、volatility、权限属性保持不变，或单独列出并请求批准。
- [ ] 纯版式改动与语义/性能改动分开成组。
- [ ] 命名与头部按固定风格对齐；改函数名或参数名被单独标为接口变更并请求批准。
- [ ] 合并或删除临时表时，说明每张表原来的用途、为什么可以去掉、被引用次数与生命周期。
- [ ] 没有为了“结构更清晰”而无理由增加临时表数量。
- [ ] 日期谓词改为列侧裸露、右侧显式类型；说明这是否改变结果类型或边界（例如文本列存 ISO
      日期时，字符串比较与日期比较不等价）。
- [ ] 行为等价声明覆盖 NULL、空区间、右开/闭区间与删除范围。

## 5. `review` 场景

输入：一个动态 SQL 落表函数，用户问“有没有性能问题”。

期望输出：

- [ ] 顺序为 安全 → 正确性 → 性能风险 → 风格；排版偏差单独记为 `STYLE-FMT`。
- [ ] 每条问题有级别、规则 ID、位置、证据、后果与整改建议。
- [ ] 过滤列上的 `::date`、只引用一次的临时表、无物化理由的 staging 被标为
      `WARNING` / `plan-required`，不是 `BLOCKER`（除非有计划或负载证据）。
- [ ] 没有声称已执行 `EXPLAIN` 或已确认性能。
- [ ] 需要 schema、计划或负载的事项单独列出。
- [ ] 风格问题引用固定风格或项目书面约定，没有评价“像不像某个人的写法”。

## 6. 负例：应当被拒绝或纠正的输出

- [ ] 写“已用 `EXPLAIN` 验证/已实测更快”，但用户没有提供计划或负载数据 → 纠正为
      `plan-required` / `not verified`。
- [ ] 把 `q.riqi::date >= p_start` 当作“标准写法”推荐 → 纠正为 `q.riqi >= p_start::date`，
      并说明列类型前提。
- [ ] 为拆短 SQL 新增多张临时表，却说不出引用次数与物化理由 → 要求合并或改用 CTE。
- [ ] 把真实姓名、内网主机、库名、账号写进头部或示例 → 要求改为占位符。
- [ ] 试图恢复“从输入提炼风格”的模式，或声称某写法来自“原属主习惯/历史语料” → 纠正为
      固定通用风格；用户自己的函数只作为改写或审查输入。
- [ ] 在生成或改写中擅自改函数名、参数名或返回码 → 标为接口变更并请求批准。

## 7. 交付前输出检查

- [ ] 标明当前模式（`generate` / `rewrite` / `review`）。
- [ ] 规则引用使用既有编号（`F-xx` / `STYLE-xx` / `PERF-xx` / `REV-xx` / `ENG-xx` / `PLS-xx` /
      `AP-xx` / `B-xx`），不自造；`00`/`01`/`05` 无编号条目按“文件名 + 小节名”引用。
- [ ] 性能结论带证据标签；没有计划或负载时明确写“未验证”。
- [ ] 临时表有理由清单；日期谓词符合“列侧裸露、右侧显式类型/参数”。
- [ ] 固定风格逐条自检，未过项说明原因。
- [ ] 说明实际查阅了哪些参考文件，没有整目录加载。
- [ ] 没有创建或修改任何输入、元数据、连接配置。

## 8. 输出检查器

两个检查器都只使用 Python 标准库，不连接数据库、不访问网络、不执行 SQL；退出码统一为
`0` 通过 / `1` 发现问题 / `2` 用法或读取错误。

- [ ] SQL 输出：`python scripts/check_sql_output.py --json <file.sql>`。JSON 含
      `ok`、`database_connected: false` 与 `violations`（`rule` / `line` / `message`）；
      覆盖 `F-06`、`F-12`、`F-21`、`F-32`～`F-41`（`F-40` 支持 `*UpdateDate` 逗号追加或多行追加）、`STYLE-01`（仅函数）、`PERF-29`（仅过滤/比较上下文）、`INC-05`、`INC-07`（禁止在 `update_time` 变更日期推导中过滤 `deleted = 0`/`is_deleted = 0`）、`REV-S01`～`REV-S04`、`REV-C01`，并支持单文件多函数/过程逐个检查；输出包含 `violation_count` 与实际命令。
- [ ] 默认目标基线为原生 PostgreSQL 12+；仅当显式指定 GP 6.6 或 PG 9.4 时按低版本门槛核对。
- [ ] 仓库书面约定用尾逗号时，加 `--comma-style trailing`；否则 `F-12` 会按前置逗号误报。
      `CREATE INDEX ... ((col::date))` 属于表达式索引，不报 `PERF-29`。
- [ ] 模式输出：`python scripts/verify_output_contract.py --mode generate --file <output.md> --json`。
      按 `SKILL.md`「输出契约」校验段落缺失（`OUT-SEQ-01`）、顺序（`OUT-SEQ-02`）、
      证据标签（`OUT-LABEL-01`）与未实测断言（`OUT-EVID-01`，豁免代码围栏、反引号引用与否定句式）。
- [ ] 非法模式（`generate` / `rewrite` / `review` 之外）按用法错误返回 `2`。

## 9. 增量更新场景

输入：一个按更新时间增量的落表函数，源表有 `update_time` 与 `deleted` 列。

- [ ] 头部或契约里写明增量模式（`date_slice` / `update_time` / `full`）、增量键与回看窗依据。
- [ ] 回看窗是参数或配置，不是一个散落的 `CURRENT_DATE - INTERVAL 'N days'` 常量。
- [ ] 回看条件有上界：`update_time >= v_lookback AND update_time < v_batch_ts`；上界取一次，
      使用 `clock_timestamp()` 而不是 `now()`。
- [ ] 稀疏增量优先用 `array_agg(DISTINCT ...)` 收集 `v_changed_dates date[]`（`min/max` 仅用于连续区间/显式回溯），空结果用 `IS NULL` 判断，没有 `2099-01-01`
      一类哨兵日期。
- [ ] `DELETE` 的日期条件与 `INSERT ... SELECT` 的条件来自同一集合或同一对变量，没有一边用推导值、
      一边用原始参数。
- [ ] 源表有 `deleted` 列时，变更日期推导查询不过滤 `deleted = 0`，`AND a.deleted = 0` 只写在 `INSERT ... SELECT` 抽取中；契约或审查报告里声明物理删除不捕获，
      并给出全量对账兜底。
- [ ] 落表是按业务区间覆盖而不是追加；回看窗重叠时结果仍幂等。
- [ ] `update_time` 的维护方式（默认值、触发器或显式写入）与时钟源已确认；不成立时降级为
      业务日期切片。
- [ ] 首次全量到增量的切换方式写在部署说明里。
- [ ] 多源宽表中，能独立提供日期/主体/交易单元等目标键的源必须进入驱动集合；仅在 `LEFT JOIN` 补列侧出现时，反例应报 `REV-P15` / `PERF-52`。
- [ ] 单源表或不含目标业务键的纯补列源，即使存在 `LEFT JOIN` 也不应被规则误报。
- [ ] 驱动键源清单与 `update_time` 增量日期源清单一致；新增驱动源未同步进水位线推导时，报 `INC-15`。
- [ ] 固定 96 点目标表中，各源先完成 24→96 后，最终层只做业务键与 96 时段关联；最终 `SELECT` 不再重复 `CASE`/四拆分或 `CROSS JOIN` 时间维表。
- [ ] 负例“最终层 24→96”报 `REV-P16` / `PERF-53`；正例“源端已是 96 点”不报该规则。
- [ ] 合同派生表在 `GROUP BY`/`max(contract_cycle)` 前下推日期窗口和业务域交易单元过滤，外层仍保留交易单元与合同有效期精确匹配。
- [ ] 负例“先全表按 `contract_id` 聚合、只在外层 `ON` 过滤”报 `REV-P17` / `PERF-54`；正例在聚合前过滤。
- [ ] SQL 可直接表达的源存在性检查不引入 `to_regclass` 局部变量；简单无映射告警不引入无必要计数变量。
- [ ] 生产日期参数只做必要转换与区间顺序校验；稀疏增量的 `v_changed_dates date[]` 不得误删。
- [ ] 每张临时表说明数据类型、物化理由/复用位置和生命周期。
- [ ] 无指标文档依据的备用源从增量推导、临时表、驱动键和注释中整链删除；不能只删最终 `SELECT`。
- [ ] 合同关联包含交易单元和有效期；宽表 `INSERT` 目标列与 `SELECT` 列逐列注释对应。
