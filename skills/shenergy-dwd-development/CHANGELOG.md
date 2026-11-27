# Changelog

申能 DWD 开发技能的版本变更记录。版本号与 `SKILL.md` frontmatter 的 `version` 保持一致。

## 0.4.0 — 2026-11-27

增加模式判定，把首次开发从完整 SOP 中拆出，缩短首次执行时间并固定首次产物。

- `SKILL.md`：开头新增「先判定模式」，分 `bootstrap`（首次开发，目标库尚无源表）、`full`（源表已同步）、`maintenance`（存量维护）；提示词与库内实况冲突时停止报告。
- 新增 `references/首次开发.md`：`bootstrap` 只执行 5 步（BI看口径 → 源端探查 → 建表工匠字段补录 → DDL 与 Spec → 函数初稿）；快照只读 `BI看` sheet；字段补录为必做；函数中源表必须写全限定名供平台解析血缘；限定读取范围与工作区边界（非空目录不扫描其他文件、已有省份业态目录先询问、不装依赖不写探针脚本不做 git 操作）；检查器每文件最多修 2 轮；固定产物清单与四段汇报。
- `scripts/check_shenergy_artifacts.py`：新增 `--kind bootstrap <省份业态目录>`，规则 `SH-BOOT-01`（必备产物缺失）、`SH-BOOT-02`（清单外或 full 阶段文件）、`SH-BOOT-03`（Spec 与函数一一对应）、`SH-BOOT-04`（README 写明模式与四个汇报键）。
- `scripts/verify_offline.py`：必备文件加入 `references/首次开发.md`。
- `references/流程与门禁.md`、`references/产物契约.md`：注明阶段 1–9 与完整目录适用于 `full` / `maintenance`。

## 0.3.0 — 2026-11-27

优化与 `pg-function-craft` 的协同接口：增加阶段 4→5 结构化 Function Spec、一键双检无重叠双层门禁、可移植相对脚本路径，并与 `pg-function-craft` 统一为原生 PostgreSQL 12+（`pg12+`）默认基线及单一规则归属分工。

- `scripts/check_shenergy_artifacts.py`：
  - 新增 `--kind spec`（`SH-SPEC-01`..`05`）校验阶段 4→5 的 `<目标表名>_spec.json` 交接规格；
  - 新增 `--spec <spec.json>` 支持：`--kind ddl` 校验目标表与全量 `insert_columns` 存在性（`SH-DDL-10`），`--kind func` 自动推断粒度与 `legacy` 状态并校验 `INSERT` 列清单顺序对齐（`SH-FN-10`）及全部 `driver` 源引用（`SH-FN-11`）；
  - 新增 `--with-pg-checker` / `--pg-checker` / `--comma-style` 一键双检模式，自动发现并调用同级 `pg-function-craft/scripts/check_sql_output.py`；
  - 完成单一规则归属消除重叠：`SH-FN-04` 收窄为仅检查 `INSERT` 列清单与 `SELECT` 投影（豁免 `WHERE` 过滤）并作为 `ext_1`–`ext_10` 的唯一检查实现；移除重复规则 `SH-FN-09`（逻辑删除变更日期推导统一由 `pg-function-craft` `INC-07` 检查）；清空 `OVERLAP_RULES` 并保留 `deduplicated: []` 兼容键。
- `scripts/generate_validation_sql.py`：新增 `--spec <spec.json>`，自动读取 `target_table`、`function_name`、`business_keys`、`metric_columns`、`grain`、`date_col`、`unit_col` 与 `blood_batch`（支持 CLI 参数局部覆盖）。
- `references/产物契约.md`、`references/函数与验收.md`、`references/流程与门禁.md`、`SKILL.md`：
  - 将文档中写死的 `skills/.../scripts/...` 仓库路径统一改为可移植的 `scripts/...`；
  - 接入 `<目标表名>_spec.json` 契约、一键双检门禁与 `pg-function-craft` 调用 Profile（默认 `target_engine: pg12+`、`return_contract: row_count`、`comma_style: leading`、`project_overrides: [ENG-11, ENG-26]`），并对 §2.4/§2.6/§2.8 中与 `pg-function-craft` 重复的通用 PG 规范改用规则编号引用去重；`SKILL.md` 版本升至 `0.3.0`。
- 新增 `tests/test_skill_handoff_contract.py`：覆盖 `--kind spec`、DDL/函数 `--spec` 校验、一键双检无重叠分工、`generate_validation_sql.py --spec` 及跨技能路径/Profile 文档契约。

## 0.2.0 — 2026-11-27

统一函数返回与逻辑删除契约，声明与 `pg-function-craft` 的优先级边界，并补齐四套纯标准库离线确定性脚本。

- `references/函数与验收.md`：
  - 统一 §2.3、§2.6、§2.8 返回契约：新建 DWD 函数一律使用 `RETURNS integer` 返回 `v_rows integer`（`>= 0`，`0 行也算正常`；参数非法 `RETURN -1`），§2.8 模板 `*output` 更新为 `-1参数异常, >=0影响行数`，既有保留状态码 `0` 的函数按 §2.5 保留 `-1参数异常, 0正常`。
  - §2.4 明确 `v_changed_dates` / `v_changed_months` 从 `update_time` 推导时禁止过滤 `deleted = 0`（`deleted = 0` 仅写在 `INSERT ... SELECT` 抽取阶段）。
  - 新增 §2.10「与 `pg-function-craft` 的优先级与覆盖声明」，将本技能定位为 `pg-function-craft` `00-风格与边界.md` §6 第 2 层「项目已确认的书面约定」，明示 §2.6 对 `ENG-11`/`ENG-26` 及 §2.3 `v_rows` 对 `0正常` 的覆盖边界，且不得降低 `01`/`02` 安全与正确性基线。
  - 在「静态检查」与「授权执行与验收」接入 `check_shenergy_artifacts.py --kind func --json`（与 `pg-function-craft` `check_sql_output.py --json` 并列留痕）及 `generate_validation_sql.py`。
- `references/流程与门禁.md`、`references/产物契约.md`、`SKILL.md`：
  - 分别在阶段 1/4/5/7/8/9 接入 `parse_bi_snapshot.py`、`check_shenergy_artifacts.py`（`ddl`/`func`/`csv`/`report`）、`generate_validation_sql.py` 与 `verify_offline.py`；在 `SKILL.md` 增加「阶段硬约束与脚本速查表」，`version` 升至 `0.2.0`。
- 新增离线脚本（纯 Python 3.10+ 标准库，零数据库驱动、零网络调用）：
  - `scripts/parse_bi_snapshot.py`：离线解析 `BI看`（物理忽略 I/J/K、传播合并单元格、分类 L 列、输出 JSON 与 12 列无 BOM CSV 骨架）。
  - `scripts/check_shenergy_artifacts.py`：统一静态校验 DDL（`SH-DDL-01`..`09`）、函数（`SH-FN-01`..`09`）、字段对照 CSV（`SH-CSV-01`..`04`）与报告留痕（`SH-RPT-01`..`02`）。
  - `scripts/generate_validation_sql.py`：生成 `compile`、`reconcile`、`sample`、`missing`、`blood` 与 `all` 标准验证 SQL 模板。
  - `scripts/verify_offline.py`：技能包离线完整性与零凭据/零网络导入自检。
- 新增 `tests/test_shenergy_scripts.py`：覆盖四个新脚本的全部核心规则与正反例测试。

## 0.1.1 — 2026-11-26

明确 `ext_1`–`ext_10` 只是目标表的平台/DDL 预留扩展列，不进入计算脚本。

- `SKILL.md`、`references/函数与验收.md`、`references/流程与门禁.md`、`references/产物契约.md` 同步：计算脚本的 `INSERT`/`SELECT`、字段映射和来源登记不写扩展字段，也不生成 `NULL` 占位。
- 新增测试，锁定扩展字段只能在 DDL 结构检查中出现，避免为了列数对齐而写入无业务来源的扩展列。

## 0.1.0 — 2026-11-25

将申能 DWD 的函数头规范收敛为部署后可导出的八字段格式。

- `references/函数与验收.md` 新增 §2.8：函数头位于 `AS $function$` 之后、`DECLARE`/`BEGIN` 之前；说明 `pg_get_functiondef` 只保留函数体内注释。
- `SKILL.md`、`references/流程与门禁.md` 与 `references/产物契约.md` 同步函数头位置、八字段要求、返回契约和导出验收条件。
- 明确 `*name` schema 全限定、`*input` 参数业务含义、`*output` 行数契约、`*increment` 不适用时仍需保留、日期格式和分隔线要求。

## 0.0.6 — 2026-11-25

补回《售电4表_迁移SOP》里有、但整理成技能时丢失的规则，并解决 SOP 模板与 0.0.3 增量规则的正面冲突。

- `references/函数与验收.md` 新增 §2.6「参数校验与返回码」：`p_flag` 非 0/1、`p_lookback_days` 为负、显式区间日期为空或格式不符、区间倒置一律 `RETURN -1`；日表跨度 `> 92` 天抛 `22023` 并要求改用 `p_flag = 1` 分批；返回码 `0` 正常（含 0 行）、`-1` 参数非法；`p_flag = 0` 不得当全量。
- `references/函数与验收.md` 新增 §2.7「数值、空值与无源列」：电量/电费 `round(coalesce(x, 0), 6)`、电价不补 0、加权均价 `sum(e*p)/NULLIF(sum(e),0)`、无源列 `NULL::numeric(20,6)` 带 `-- 无源` 且不得从 `INSERT` 列清单注释掉、月表 `target_yearmonth` 只用 `YYYY-MM` 比较。
- `references/函数与验收.md` §2.4 末尾补「与 SOP §5.3 模板的关系」：`min/max` 反推区间只保证不漏、不保证不重写，日常稀疏增量默认用 `v_changed_dates date[]`；既有多数线上函数已用该写法，改造时不要为贴合模板而改回区间。
- `references/流程与门禁.md` §3 补五道闸、命名规范、长度 ≤58/63、拆词查重先于格式、字段库覆盖才算完成；§4 补字段清单来源、类型判定表、`numeric(20,6)` 等硬规则、MySQL→PG 机械转换、主键索引与建表自检；§5 补参数校验与数值空值两段；§7 补三层对账、三类抽样与 `SAMPLE_NOT_READY`、字段缺失五种状态、验收签收单；§8 补登记规则、8 条登记后校验、回滚；§9 补五维审查、等价性验证、变更分离、P0 清单、交付物与已回退列。
- `SKILL.md` 阶段 3/4/5/7/9 正文同步上述要求，避免规则只写在参考文档里不被引用。
- 新增 `tests/test_sop_coverage_rules.py`：锁定参数校验、数值空值、命名、DDL 类型、验收三层对账、血缘 8 条校验、交付 P0 清单等条目文本，并断言 `min/max` 与 `date[]` 的取舍规则存在。

### 缘起

2026-11-25 按 SOP 逐条检索仓库版技能，发现参数校验、五道闸、DDL 类型转换、加权与空值规则、三层对账、抽样校验、血缘 8 条校验、交付 P0 清单等在技能中检索为 0（0.0.5 版 `流程与门禁.md` 9.4KB，SOP 为 2,400 余行）。同时暴露两处正面冲突：SOP §5.3 模板用 `min/max` 反推区间并按区间删除，而 0.0.3 的 §2.4 明令禁止该写法；SOP §5.2 模板 `RETURNS smallint`，而 0.0.2 的 §2.3 判定其为模板缺陷。增量冲突按场景分工解决，返回类型以 §2.3 为准。

## 0.0.5 — 2026-11-24

补入「存量表列名优先」规则，堵住「按快照原文重定平台条目、把已上线列名改掉」这条路。

- `references/流程与门禁.md` §3 新增同名段落：目标表已存在时业务列名以现库既有列名为准，平台字段库只用于新增列定名；同一中文名在平台有多条条目时选既有列名，并记录「平台另一条目 / 最终采用 / 原因」；改名属破坏性变更，须单独列出影响面（下游取数、血缘 `en_column`、BI 配置、`RENAME COLUMN` 计划）并获授权，不得与口径变更混在一起交付。
- `references/流程与门禁.md` §4 DDL 补一句：既有对象的列名不因平台条目不同而更换。
- `SKILL.md` §3 正文同步该规则。
- `tests/test_function_contract_rules.py` 增加 3 项断言（共 21 项），锁定「存量表列名优先」「改名须授权」「DDL 不得换名」三处措辞。

### 缘起

2026-11-24 安徽售电实验组重跑时，已按「英文字段名走建表工匠字段库」的规则查了平台，但遇到同一中文名对应多条条目的岔路（如「日前统一结算点均价」→ `dayahead_unified_settlement_price`，而目标表已上线列名取自另一条「用户侧日前市场统一结算点电价」→ `consumption_dayahead_market_unified_settlement_price`）。当时自行选择了「平台条目更贴快照原文」这条判据，把 8 列改成平台另一条目，并把它当成正常差异写进结论；用户指出这是把已经定义好的字段改错。回查发现 §3 只写了「优先沿用已有同义字段和平台唯一词条」，没有指明「已有」指现库列名还是平台词条，§4 也只提表结构兼容性、未提列名，属规则缺位；但选择该判据本身是执行者的越界判断，规则补位后仍需按此约束。

## 0.0.4 — 2026-11-24

消除「pg-function-craft 到底是必调还是可选」的内部矛盾，并把调用留痕变成验收硬项。

- `references/函数与验收.md` §静态检查：删掉「引用外部工具是可选的」这句孤立豁免，改为按类别区分——本包配套技能 `pg-function-craft` **必调**，包外 `sqlglot`/`sqlfluff`/`pg_format` 才可选。补两句边界：检查器 `ok: true` 不代表语法正确（它不做 SQL 解析），必须再做事务内编译验证。
- `references/函数与验收.md` §授权执行与验收：验收清单新增首项「技能调用留痕」，要求附 `check_sql_output.py --json` 实际输出；只有人工对照、没有检查器输出时本项记为未完成，不得写「已完成静态检查」。
- `references/流程与门禁.md` §5 同步必调措辞，明确「外部工具可选」不能当作跳过本包技能的借口；§7 新增同名的留痕核对段。
- `SKILL.md` §5 正文写明必调、需留检查器输出、通过后仍须编译验证。
- `tests/test_function_contract_rules.py` 增加 5 项断言（共 18 项），锁定「必调」措辞、包外工具清单、检查器输出要求、编译验证、验收留痕项，并断言旧句「引用外部工具是可选的」不再出现。

### 缘起

2026-11-23 首次用本技能产出四张函数，全程未调用 `pg-function-craft`。回查发现技能在 `SKILL.md` 描述、`SKILL.md` §5、`流程与门禁.md` §5、`连接配置.md` §6 四处都写了要调用，措辞是「阻塞」「不得声称已使用」，属执行遗漏。但 `函数与验收.md` 又写着「引用外部工具是可选的」，而 `SKILL.md` 正是要求「开发函数时读取 `函数与验收`」，这句成了把遗漏合理化的依据。仅靠措辞不足以约束，因此在验收清单里加了可核对的留痕项。

## 0.0.3 — 2026-11-23

补三条在干净环境复现过的遗漏：规则本来分散在段落里，没有形成「不做就错」的条目。

- `references/函数与验收.md` §2.1 新增**禁止自造时段骨架**：不得用 `generate_series(1, 96)` 拼 `lpad` 字符串构造 96 点编码，`dim.dim_timeperiod_change` 是唯一时段来源（96 行，含 `time_part`/`time_24`/`time_48`），缺失即阻塞。
- `references/函数与验收.md` 新增 §2.4「增量必须按变化集合」：`update_time` 增量收 `date[]`，删除与重算都 `= ANY(...)`；禁止扩成 `min/max` 区间再 `BETWEEN`；水位线半开区间，推导与抽取过滤一致。
- `references/函数与验收.md` 新增 §2.5「保留既有函数的外部契约」：参数校验返回方式、`EXCEPTION` 包装与 `ERRCODE`、头部既有字段、观测点、临时表命名成对保留。
- `references/流程与门禁.md` §5 同步上述三条，阶段流程可直接读到。
- `SKILL.md` 入口段列出三条不可自行发挥项，并说明 `pg-function-craft` 的 F-32 只校验同层列表项，不要为过检把表达式压成超长单行。
- 新增 `tests/test_function_contract_rules.py`：14 项断言锁定上述条目文本。

### 缘起

2026-11-23 在干净环境按本技能独立推导安徽售电四表函数，与目标库既有实现比对后发现：

- 时段展开没用 `dim.dim_timeperiod_change`，自造了 `generate_series` + `lpad` 骨架，与同项目其他省份脚本口径分叉。
- 增量写成了 `DELETE ... BETWEEN v_start AND v_end`，把水位线增量退化成区间全量重算；既有实现用 `v_changed_dates date[]`。
- 参数非法时 `RAISE EXCEPTION`，而既有实现返回 `-1`；`EXCEPTION` 包装、`RAISE DEBUG`、头部 `*increment` 字段全部缺失。

三项都不属于业务口径分歧，是技能没把要求写成条目导致的执行力差距。

## 0.0.2 — 2026-11-23

- `references/函数与验收.md` 新增 §2.3「返回类型必须能装下行数」：SOP §5 模板的 `RETURNS smallint` 是模板缺陷，上限 32767，96 点表季度级分区必然溢出。
  - 报错 `NumericValueOutOfRange: smallint out of range` 发生在函数末尾 `RETURN` 处，前面的 `DELETE`+`INSERT` 已执行完毕，表现为「像跑成功但报错」，极易误判为数据问题。
  - 一律用 `RETURNS integer`、`v_rows integer`、`RETURN v_rows;`。
- `tests/test_timeperiod_conversion_rules.py` 增加 1 项断言，锁定 §2.3 必须同时出现 `RETURNS integer`、`smallint` 与 `32767`。

### 缘起

0.0.1 规则生效后按季度分段重跑安徽出清影子表，10 段中 7 段报 `smallint out of range`（季度行数 51,264~52,992）。修正返回类型后 10 段全部成功，写入 428,544 行。

## 0.0.1 — 2026-11-23

- `references/函数与验收.md` 新增 §2.1「时段换算方向」：补回原始《售电4表_迁移SOP》§2.6 中已有、但整理成技能时遗漏的明文规定。
  - 24 → 96：电量 `energy / 4.0` 均分到 4 个槽，电价**原值沿用**（同一小时 4 槽取相同值）。
  - 96 → 96：原值；源为功率（MW）时 `/4`。
  - 96 → 24、24 → 24：**均不允许**。目标表只要有 `timeperiod` 列就只能存 96 点，不得建 `_d24`。
  - 展开写法：主体清单 `CROSS JOIN dim.dim_timeperiod_change`，按 `源.time_part = t.time_24` 关联。
  - 展开后必须验算日合计不变；差 4 倍即 `/4` 用错或漏用。
  - `/4` 必须写注释区分「24 点均分」与「MW×0.25h」，两者数值相同、含义不同。
- `references/函数与验收.md` 新增 §2.2「日粒度指标在 96 点表中的存放」：SOP 未对该项给出统一规定，标为待确认；明确不得默认把日值复制到全部 96 槽（会使该列 `SUM` 放大 96 倍）。
- `references/流程与门禁.md` §5 补「时段方向」段，使阶段流程可直接读到该约束。
- `SKILL.md` 入口段补一句：涉及 `timeperiod` 的目标表，时段换算方向不是可选项。
- 新增 `tests/test_timeperiod_conversion_rules.py`：9 项断言锁定上述规则文本，防止再次在整理过程中遗漏。

### 缘起

2026-11-23 在干净环境验证本技能时，仅依据快照与源库独立推导安徽售电出清函数。因技能未写明换算方向，推导时按字面理解把 96 点源 1:1 落库，与目标库既有实现（先加权合成 24 点再复制回 4 槽）产生 1.5 倍差异。回查原始 SOP 第 89、288、290、1343 行，确认方向早有明文且明确禁止 96→24 —— 属整理成技能时的遗漏，非业务分歧。
