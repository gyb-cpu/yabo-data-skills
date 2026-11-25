# yabo-data-skills

![yabo-data-skills](assets/yabo-data-skills-hero.svg)

可复用的 Agent Skills 集合，通过通用 skills CLI 分发，不绑定特定的 Agent 或 IDE。

当前收录两个技能：

| Skill | 版本 | 适用任务 | 依赖 |
|---|---:|---|---|
| `pg-function-craft` | 0.5.0 | 生成、改写、审查 PostgreSQL / Greenplum 函数、存储过程和触发器函数 | Python 3.10+，只做离线静态检查 |
| `shenergy-dwd-development` | 0.1.0 | 按省份、业态开展申能 DWD 口径、探源、DDL、计算、验收和交接 | 同时安装 `pg-function-craft`；按任务需要访问建表工匠、源库和目标库 |

如果只处理 SQL 函数，安装 `pg-function-craft` 即可。要做申能 DWD 开发，两个技能都要安装；`shenergy-dwd-development` 负责业务流程和证据，`pg-function-craft` 负责函数工程与静态检查。

## 5 分钟接入

1. 进入目标业务项目根目录。
2. 确认本机可以使用 `npx` 和 Python 3.10+。
3. 安装需要的技能。默认只安装到当前项目，不添加 `-g`。
4. 运行离线自检，确认技能目录完整。
5. 按任务准备业务资料和授权，再让 Agent 开始工作。

把下面这段提示词直接发给 Agent。它只负责安装和验证，不检查业务资料：

```text
在当前项目根目录安装并验证 yabo-data-skills 的两个技能：
1. 检查 npx、Python 3.10+ 和网络；缺失时直接告诉我。
2. 不加 -g，执行：
   npx skills add gyb-cpu/yabo-data-skills --skill pg-function-craft
   npx skills add gyb-cpu/yabo-data-skills --skill shenergy-dwd-development
3. 确认两个安装目录名与 SKILL.md 的 name 一致，并记录 version。
4. 在 pg-function-craft 目录运行 python scripts/verify_offline.py --json。
5. 汇报安装路径、版本和自检 ok/issues；失败时附实际命令和错误，不要伪造成功。
```

安装成功的标准只有三条：两个技能默认安装到当前项目且目录名正确；`pg-function-craft` 自检返回 `ok: true` 且 `issues` 为空；最终报告包含可复核的路径、版本和命令结果。

安装提示词不处理业务准备。业务快照、目标表、字段映射、`.env.shenergy` 和授权范围由安装成功后的任务提示词处理。

### 安装失败与恢复

| 情况 | 处理 |
|---|---|
| 仓库返回 404 | 检查仓库地址、网络和 CLI 版本后重试；不要改用来源不明副本 |
| 当前 Agent 不支持 skills CLI | 手动复制两个技能目录到当前项目，目录名必须与 `SKILL.md` 的 `name` 一致 |
| 自检返回 `ok: false` | 原样报告 `issues`，修正安装或文件问题，不要修改检查器绕过 |
| 安装后业务资料不全 | 重新发送业务任务提示词，不在安装阶段继续检查 |

安装阶段只允许因为缺少工具、网络或验证失败而暂停。业务资料缺失属于后续任务准备，不是安装失败。


## 安装

### 前置条件

| 项目 | 要求 | 用途 |
|---|---|---|
| Node.js / npm | 建议使用当前 LTS，能够运行 `npx` | 安装和更新 skills |
| Python | 3.10+；仓库测试在 3.12 下验证 | 运行离线检查器和回归测试 |
| Git / 网络 | 能访问公有仓库 `gyb-cpu/yabo-data-skills` | skills CLI 拉取仓库；安装不需要 GitHub 登录 |
| Agent | 支持读取 `SKILL.md` 形式的技能目录，或支持 skills CLI | 发现和加载技能 |
| 业务环境 | 申能任务需要按范围获得建表工匠、源 MySQL、目标 PostgreSQL 的访问能力 | 探源、编译、部署和验收；不以拥有凭据代替写权限授权 |

### 安装指定技能

在目标业务项目根目录执行，不要添加 `-g`：

```bash
npx skills add gyb-cpu/yabo-data-skills --skill pg-function-craft
npx skills add gyb-cpu/yabo-data-skills --skill shenergy-dwd-development
```

默认安装到当前项目，仅当前项目中的 Agent 可见。切换业务项目时需要重新安装；只有明确希望所有项目共用时才使用 `-g`。

本仓库是公有仓库，匿名拉取不需要 GitHub 登录。具体落盘目录由 skills CLI 和当前 Agent 决定，以命令输出为准。推送或维护仓库源码时才需要 GitHub 凭据，不要把 token 写进命令、仓库文件或交付物。

### 自动发现安装

如果所用 CLI 支持扫描仓库内的 `skills/` 目录，可以省略 `--skill`：

```bash
npx skills add gyb-cpu/yabo-data-skills
```

随后按提示选择技能。做申能 DWD 开发时选择两个技能。不同 CLI 版本的参数可能不同，必要时先查看：

```bash
npx skills add --help
```

### 不使用 CLI 时

把需要的技能目录完整复制到目标 Agent 的技能根目录：

- `skills/pg-function-craft/`
- `skills/shenergy-dwd-development/`

目标目录名必须与 `SKILL.md` frontmatter 中的 `name` 完全一致，否则技能发现和后续更新可能错位。`pg-function-craft` 必须保留 `SKILL.md`、`README.md`、`CHANGELOG.md`、`references/`、`scripts/`、`tests/` 和 `assets/`。申能技能必须保留 `SKILL.md`、`CHANGELOG.md`、`references/` 和 `.env.example`；实际 `.env.shenergy` 只放在业务项目本地，不随技能分发。

### 安装后验证

在 `pg-function-craft` 技能根目录执行：

```bash
python scripts/verify_offline.py --json
```

预期至少满足：

```json
{
  "ok": true,
  "issues": [],
  "warnings": [],
  "database_connected": false
}
```

该脚本只使用 Python 标准库，不连接数据库、不访问网络、不执行 SQL。它检查文件完整性、技能名称、文档引用、编码、换行和禁止夹带内容，不代表 SQL 已在数据库中编译通过。

申能技能没有独立的自检脚本。至少确认 Agent 能加载 `shenergy-dwd-development/SKILL.md`，并能读取 `references/` 下的四份说明。需要访问平台或数据库时，再检查 `.env.shenergy` 和对应授权。

### 更新已安装技能

skills CLI 不会自动监听 GitHub 仓库更新。通过 CLI 安装的用户需要显式执行更新。

安装时使用了 `-g`：

```bash
npx skills update -g
```

安装时没有使用 `-g`：

```bash
npx skills update
```

如果当前 CLI 不支持 `update`，或者更新后版本没有变化，重新执行安装命令覆盖旧版本：

```bash
npx skills add gyb-cpu/yabo-data-skills --skill pg-function-craft
npx skills add gyb-cpu/yabo-data-skills --skill shenergy-dwd-development
```

更新后重新检查两个 `SKILL.md` 的 `version`，并运行：

```bash
cd <pg-function-craft 技能目录>
python scripts/verify_offline.py --json
```

手动复制的技能不会自动更新。维护者可以使用目录联接指向 Git 仓库并通过 `git pull` 更新；普通使用者需要重新复制技能目录。`.env.shenergy` 位于业务项目根目录，更新技能不会修改本地配置。

#### Agent 开工前版本检查

每次开始依赖这些技能的任务前，可以发送下面的轻量检查提示词：

```text
检查 yabo-data-skills 是否需要更新。
先读取两个已安装 SKILL.md 的 version 和实际路径。若当前 CLI 支持 update，先给出命令并等待我确认，不要静默更新；若不支持，给出按原安装作用域重新安装的命令并等待确认。成功后重新读取版本并运行 pg-function-craft 的 verify_offline.py --json。失败时继续使用本地版本，但必须标注“未确认最新”。
```

## 环境配置

### Agent 运行环境

`pg-function-craft` 不需要数据库驱动，也不需要数据库连接。Agent 只要能读取技能文件并运行 Python 即可。

`shenergy-dwd-development` 会在获得授权后读取业务证据、访问平台或数据库。本仓库不内置数据库驱动、平台 SDK 或自动化执行器；Agent 应复用其运行环境中已有的连接器、CLI 或安全凭据机制，不能假设这些能力已经存在。

### 申能配置：`.env.shenergy`

将申能技能目录下的 `.env.example` 复制到业务项目根目录，命名为 `.env.shenergy`。PowerShell 示例：

```powershell
Copy-Item "<技能安装目录>\shenergy-dwd-development\.env.example" ".env.shenergy"
Add-Content ".gitignore" ".env.shenergy"
```

Linux / macOS 示例：

```bash
cp "<技能安装目录>/shenergy-dwd-development/.env.example" .env.shenergy
printf '\n.env.shenergy\n' >> .gitignore
```

配置只在本机填写，不得提交、打包、发送或写入交付物。变量含义如下：

| 变量组 | 变量 | 说明 |
|---|---|---|
| 建表工匠 | `TABLEFORGE_URL` | 平台地址 |
| 建表工匠 | `TABLEFORGE_USERNAME`、`TABLEFORGE_PASSWORD` | 账号密码认证方式；是否必填以平台为准 |
| 建表工匠 | `TABLEFORGE_TOKEN` | token 认证方式；与账号密码按实际认证方式选择 |
| 源 MySQL | `SOURCE_MYSQL_HOST`、`SOURCE_MYSQL_PORT`、`SOURCE_MYSQL_DATABASE` | 源库地址、端口和数据库 |
| 源 MySQL | `SOURCE_MYSQL_USER`、`SOURCE_MYSQL_PASSWORD` | 只读账号；不要把只读账号视为写库授权 |
| 源 MySQL | `SOURCE_MYSQL_SSL_MODE` | 按驱动和服务器要求填写，不能把空值理解为已启用 TLS |
| 目标 PostgreSQL | `TARGET_PG_HOST`、`TARGET_PG_PORT`、`TARGET_PG_DATABASE` | 目标库地址、端口和数据库 |
| 目标 PostgreSQL | `TARGET_PG_USER`、`TARGET_PG_PASSWORD` | 探查阶段使用只读账号 |
| 目标 PostgreSQL | `TARGET_PG_SSLMODE` | 按实际连接要求填写 |

多省份、多业态或多环境不能共用一组不明范围的连接。无法唯一确定目标时，应先明确本次任务使用的环境，不要让 Agent 猜配置。

## 使用前需要准备什么

### 通用准备

- 明确任务目标、业务项目路径和期望交付物。
- 明确本次操作边界：离线、只读、事务内试跑、允许写库、允许回算或允许平台变更。
- 指定要使用的技能；申能 DWD 任务默认需要两个技能。
- 准备项目已有的规范、命名约定、历史决策和验收标准。
- 去掉凭据、个人信息和无关敏感数据后再交给 Agent 阅读。

### `pg-function-craft` 文件清单

| 使用模式 | 必须提供 | 缺失后的影响 |
|---|---|---|
| `generate` | 函数用途、输入输出、业务规则、目标 schema / 表、字段类型、调用方式 | 可以生成带假设的候选 SQL，但无法保证可部署 |
| `generate` / `rewrite` | PostgreSQL 或 Greenplum 版本 | 无法确认语法、函数形态和版本兼容性 |
| `generate` / `rewrite` | 目标表 DDL、主键、约束、索引 | 可能生成错误的列、类型、幂等或性能方案 |
| `rewrite` / `review` | 完整现有函数定义和调用上下文 | 无法可靠做等价改写或定位行号问题 |
| `review` | 数据量级、日期范围、执行频率、并发或上游调度信息 | 只能给静态风险，不能给实测性能结论 |
| 任意模式 | 不能改变的签名、异常处理、返回码和部署约束 | 可能误改调用方依赖的外部契约 |

推荐同时提供脱敏后的示例数据或字段说明，但不要把生产数据、连接串或凭据放进 SQL 文件和提示词。

### `shenergy-dwd-development` 文件清单

| 场景或阶段 | 用户需要提供 | 说明 |
|---|---|---|
| 首次开发 | 省份、业态、参考业务逻辑文件、当前项目根目录的 `.env.shenergy` | 在业务项目根目录运行；日期、输出目录和目标范围可由参考文件、当前日期和项目约定推导。目标表、映射、DDL、计算脚本和验收报告是产出 |
| 存量维护 | 首次开发的输入，加上现有目标表、DDL、函数、字段映射和变更范围 | 目标表已存在时，业务列名以现库既有列为准，不按平台条目或快照原文改名 |
| 口径 | 当天 BI 看快照 `.xlsx`，保留文件名、日期、sheet 和表头 | 输入项；没有当天快照时，正式口径和事实取证阻塞，历史资料只能用于明确标注的演练 |
| 探源 | `.env.shenergy` 和实际只读访问能力 | 源表登记、同步方式和覆盖信息可由技能探查后产出；不要要求用户预先完成整份源表登记 |
| 命名与字段 | 项目命名规范、平台只读访问和必要业务确认人 | 字段候选、查重结果和平台补录项由技能产出；口径冲突未确认时标 `open_questions` |
| DDL | 首次开发只需项目类型规范；存量维护再提供现有 DDL、约束、索引和主键 | 目标 DDL 由技能产出；已有对象必须先比对真实结构 |
| 计算脚本 | 首次开发只需业务目标；改写时再提供现有函数签名、异常、返回码和调用契约 | 函数 SQL 和检查器结果由技能产出；写函数前必须调用 `pg-function-craft` |
| 验收 | 验收口径、只读对账能力、允许差异和业务确认人 | 验收 SQL 和报告由技能产出；静态检查不能代替数据库编译和实际验收 |
| 权限 | 本地产物写入授权、数据库只读授权；部署、写库、回算权限按后续动作单独确认 | 只读授权足以生成候选产物；不能因缺少写库授权就停止本地设计 |

`shenergy-dwd-development` 会在用户指定的省份/业态根目录下按需要生成 `参考资料/`、`DDL/`、`计算脚本/` 和 `复核验证/`。不要为尚未确认的阶段预建空 SQL 冒充完成。

## 使用

安装后直接用自然语言描述任务。建议在任务开头写明技能名、项目路径、授权范围和期望产物，减少 Agent 自行猜测。

### PostgreSQL 函数

```text
使用 pg-function-craft 审查这个 PostgreSQL 函数。
目标版本：PostgreSQL 14。
关注：动态 SQL、异常处理、增量删除范围、索引适配和固定风格。
只能只读分析，不连接数据库，不执行 SQL。
函数定义如下：……
```

常用模式：

| 需求 | 模式 | 示例 |
|---|---|---|
| 新写函数、过程或触发器函数 | `generate` | “写一个按日期范围落表的 PG 函数” |
| 让已有函数符合固定风格 | `rewrite` | “按 pg-function-craft 重写这个函数，保持行为不变” |
| 检查安全、正确性、性能和风格 | `review` | “审查这个函数的性能和 SQL 写法” |

### 申能 DWD 开发

提示词只提供任务事实、资料路径和授权；SOP、阶段门禁、产物结构和报告格式由技能文件执行，不在提示词里重复。

首次开发在业务项目根目录运行，用户只需提供省份、业态、参考业务逻辑文件和 `.env.shenergy`。任务日期、输出目录和目标范围由 Agent 从参考文件、当前日期和项目约定推导；目标表清单、字段映射、DDL、计算脚本和验收记录由技能产出，不能作为用户必须提前提供的材料。

发送接入提示词并确认准备清单后，再使用下面的对应模板。

#### 首次开发

```text
请使用新安装的 shenergy-dwd-development 技能，在当前业务项目根目录执行首次 DWD 开发。

省份和业态：<省份> / <业态>（如：安徽 / 售电）
参考业务逻辑文件：<绝对路径>
配置：当前项目根目录的 .env.shenergy

本次只做只读探查，不写数据库、不部署、不回算。目标表、字段映射、DDL、计算脚本和验收记录由技能产出。按 SKILL.md 和 references 执行完整 SOP；信息不足写入 open_questions，不猜测。
```

#### 存量维护或改写

```text
请使用新安装的 shenergy-dwd-development 维护 <省份> <业态> 的存量 DWD；涉及函数时调用 pg-function-craft。

项目根目录：<绝对路径>
省份和业态：<省份> / <业态>
任务日期：<日期>
目标表和变更范围：<目标表与范围>
当天 BI 看快照：<绝对路径>
现有 DDL：<绝对路径>
现有函数：<绝对路径>
字段映射：<绝对路径>

.env.shenergy 已在本机准备。请自行检查，不输出配置值。
授权：源端、目标端和平台只读探查；本地产物写入。数据库写入、事务试跑、部署和回算按实际另行授权。

按技能流程核对真实表结构、列名、函数签名和调用契约。目标表已存在时，业务列名以现库既有列为准；改名必须单独列影响并获得授权。
```

每次阶段性交付应明确：

- `artifacts`：实际生成或更新的文件路径。
- `gates`：通过、阻塞或未验证，并附证据。
- `open_questions`：仍需业务确认的问题及其影响。
- `next`：下一阶段可以执行的动作和所需授权。

## 常见问题

### 安装时返回 404

先检查仓库地址是否为 `gyb-cpu/yabo-data-skills`、网络是否可用、skills CLI 是否为兼容版本。该仓库为公有仓库，正常安装不需要 GitHub 登录。不要改用来源不明副本。

### Agent 没有触发技能

先检查安装目录名是否与 `SKILL.md` 的 `name` 一致，再重启 Agent 让它重新扫描技能。仍不触发时，在任务中直接写“使用 `pg-function-craft`”或“使用 `shenergy-dwd-development`”。

### `python` 命令不存在

先安装 Python 3.10+。部分 Linux / macOS 环境使用 `python3`，把命令中的 `python` 替换为 `python3` 即可。

### 申能任务提示配置缺失

只报告缺失的变量名、受影响阶段和不含秘密的原因。让使用者在本地补齐 `.env.shenergy`，不要在日志、聊天或交付物中展开配置值。

### 检查器返回 `ok: false`

按 `issues` 中的规则逐项修正源文件。`pg-function-craft` 的检查器不解析完整 SQL 语法；通过后仍需在授权范围内做数据库编译验证。

### 无法连接数据库或平台

先确认对应变量、网络、账号权限和本次任务授权。连接失败时继续完成不依赖连接的盘点或映射工作，把依赖连接的结果标为未验证，不要伪造成功。

## 本地开发：让技能跟随仓库更新

如果在本机维护仓库，又希望 Agent 始终读取最新版本，不要复制副本。用目录联接把本地技能目录指向仓库子目录。以下以 `~/.minimax/skills` 为例：

```powershell
# 1. 现有副本改名留底，不删除
Rename-Item "$env:USERPROFILE\.minimax\skills\pg-function-craft" "pg-function-craft.bak"

# 2. 建立目录联接
cmd /c mklink /J "$env:USERPROFILE\.minimax\skills\pg-function-craft" `
  "<仓库绝对路径>\skills\pg-function-craft"
```

验证：

```powershell
Get-Item "$env:USERPROFILE\.minimax\skills\pg-function-craft" | Select-Object LinkType,Target
```

`LinkType` 应为 `Junction`，`Target` 指向仓库子目录。此后 `git pull` 即完成技能更新。

约束：

- 仓库目录不能移动或改名，否则联接断开。
- 切换分支会直接影响 Agent 读到的技能版本。
- 备份目录应放在技能目录之外，避免被识别成第二个同名技能。
- 其他 Agent 使用同一方法，只需替换其技能根目录。

如果不使用联接，继续用 `npx skills add ... -g` 安装，并用 CLI 支持的更新命令更新。这样会保留一份副本。

## 仓库结构

```text
yabo-data-skills/
  README.md                          本文件：安装、配置和使用说明
  assets/
    yabo-data-skills-hero.svg        README 封面
  tests/                             仓库级回归测试
    README.md                        测试职责说明
    test_*.py                        规则文本、脚本契约和发布形态测试
  skills/
    shenergy-dwd-development/        申能 DWD 开发流程与配置模板
      SKILL.md
      CHANGELOG.md
      .env.example                   不含凭据的连接配置模板
      references/                    流程、产物、函数与连接说明
    pg-function-craft/
      SKILL.md                       技能主规则与触发入口
      README.md                      技能自身说明
      CHANGELOG.md                   版本变更记录
      assets/                        图示资源
      references/                    规则参考文档
      scripts/verify_offline.py      离线完整性检查
      scripts/check_sql_output.py    SQL 输出规则检查
      scripts/verify_output_contract.py  模式输出契约校验
      tests/                         验收场景与检查器回归测试
```

## 开发与验证

### 技能修改与发版约定

修改任一技能目录后，按以下顺序处理：

1. 在对应 `SKILL.md` 的 frontmatter 中递增 `version`。
2. 在对应 `CHANGELOG.md` 顶部增加同版本条目，写明行为变化和影响。
3. 同步 README 技能表中的版本号；涉及申能版本时同步封面资源中的版本标识。
4. 运行仓库回归测试和 `pg-function-craft` 离线自检。

版本号采用语义化规则：

- 文本纠正、措辞澄清、无行为变化：递增 `PATCH`。
- 新增规则、改变默认输出或增加必调流程：递增 `MINOR`。
- 删除或不兼容地改变既有契约：递增 `MAJOR`。

只看文件时间无法判断技能是否最新。`SKILL.md` 的 `version` 和 `CHANGELOG.md` 是更新判断依据，因此技能行为或规则发生变化时必须同步修改两者。

### 本地检查

修改规则或脚本后，在仓库根目录运行：

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

再到 `pg-function-craft` 技能根目录运行：

```bash
python scripts/verify_offline.py --json
```

两层都通过再提交。测试文件中的 `_red` 是历史命名，当前全部为绿色用例。

## 边界说明

- 仓库可以携带无凭据的配置模板，但不得携带实际连接配置、凭据、开发语料、样例库、风格档案或导出元数据。
- `shenergy-dwd-development` 根据具体任务授权访问平台和数据库；`pg-function-craft` 只处理离线函数工程。
- `pg-function-craft` 默认不连接数据库，不执行 SQL、DDL、DML、`ANALYZE`、`VACUUM` 或 `EXPLAIN`；性能结论只做静态标记。
- 仓库以各技能 `SKILL.md` 的 `version` 和对应 `CHANGELOG.md` 作为版本来源；使用者需通过 CLI 更新、重新安装或目录联接同步，不会自动跟随仓库。
