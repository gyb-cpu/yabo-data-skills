# 仓库级回归测试

本目录锁定 `skills/pg-function-craft/` 与 `skills/shenergy-dwd-development/` 的规则文本、脚本契约与发布形态。测试只使用 Python 标准库，
**不连接数据库、不访问网络、不执行 SQL**——被检查的对象是技能包本身和检查/解析/生成脚本，不是生产库执行结果。

## 运行

在仓库根目录执行：

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

单文件运行：

```bash
python -m unittest tests.test_reference_consistency_red -v
```

当前基线：`208 passed`（仓库根 `tests/`；另有 `skills/pg-function-craft/tests/` 12 passed，Python 3.12）。

## 各文件职责

| 文件 | 锁定内容 |
|---|---|
| `test_reference_consistency_red.py` | `references/00`–`11` 之间的口径一致：冲突优先级只在 `00` 定义一次、`search_path` 写法统一、返回码契约不越界套用、`*author` 不写真实个人 |
| `test_release_contract_red.py` | 两个 `SKILL.md` 的 semver、`CHANGELOG.md` 契约、README 技能表版本同步，以及 `verify_offline.py` 的版本检查 |
| `test_structure_deploy_red.py` | 安装形态：必备目录齐全、文档内引用可解析、`description`/目录名/`name` 三者一致 |
| `test_sql_output_rules_red.py` | `check_sql_output.py` 的基础规则、输出契约、退出码与原有回归 |
| `test_function_header_contract.py` | 函数头必须位于 `AS $function$` 之后；验证八字段、名称、输入、返回契约、增量、日期和分隔线 |
| `test_rewrite_minimal_change.py` | 改写纪律：最小改动、保留导出形态（引号标识符、`pg_catalog.int2`、`$BODY$`）、保留原署名 |
| `test_etl_path_rules.py` | ETL 路径盘点契约：稀疏日期、显式区间、主源为 0、备用源独有键、冲突优先级 |
| `test_incremental_module_red.py` | 增量模块 `INC-01`–`INC-14` 的存在性、路由登记与哨兵日期识别 |
| `test_function_contract_rules.py` | 申能技能契约规则（时段维表、稀疏 `date[]`、保留既有契约、必调 `pg-function-craft`、`ext_1`–`ext_10` 隔离） |
| `test_sop_coverage_rules.py` | 申能技能 SOP 覆盖度（参数校验、数值空值、五道闸、DDL 类型、三层对账、血缘 8 项校验、P0 清单） |
| `test_timeperiod_conversion_rules.py` | 申能 24→96 时段换算方向、日量守恒与 `RETURNS integer` |
| `test_pg_checker_v2.py` | `check_sql_output.py` 与 `verify_output_contract.py` 的误报/漏报修复及高危安全/正确性规则（`REV-S01`–`S04`、`REV-C01`、`INC-07`） |
| `test_shenergy_scripts.py` | 申能 4 个离线脚本（`verify_offline.py`、`check_shenergy_artifacts.py`、`parse_bi_snapshot.py`、`generate_validation_sql.py`） |
| `test_skill_handoff_contract.py` | 双技能协同契约（`--kind spec`、DDL/函数 `--spec` 对齐、`--with-pg-checker` 无重叠双层合并、`generate_validation_sql.py --spec`、可移植路径与 Profile） |

文件名里的 `_red` 是历史命名，表示这些测试最初写在功能实现之前；现在全部为 GREEN。

## 修改规则时

改 `SKILL.md` 或 `references/` 后必须重跑全量测试，再在 `pg-function-craft` 与 `shenergy-dwd-development` 技能根目录分别执行
`python scripts/verify_offline.py --json`。两者都通过才能提交：前者防口径漂移，后者防打包缺件。
