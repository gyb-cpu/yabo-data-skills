# yabo-data-skills

![yabo-data-skills](assets/yabo-data-skills-hero.svg)

可复用的 Agent Skills 集合，通过通用的 skills CLI 分发，不绑定任何特定的 Agent 或 IDE。

当前收录：

| Skill | 版本 | 作用 |
|---|---|---|
| `pg-function-craft` | 见技能文件 | PostgreSQL / Greenplum 函数、存储过程与触发器函数的生成、改写与静态审查 |
| `shenergy-dwd-development` | 0.0.4 | 申能各省份、业态 DWD 开发流程、产物与验收 |

## 安装

前提：

- 已安装 Node.js，可用 `npx`；
- 使用的 Agent 兼容 skills CLI（能读取 `SKILL.md` 形式的技能目录）。

> 本仓库为私有仓库。skills CLI 匿名拉取时会返回 404，需要先在本地配置好 GitHub 凭据
> （`gh auth login`，或带 token 的 git 凭据管理器），再执行下面的安装命令。

安装位置不是本仓库决定的。skills CLI 或承载它的 Agent 会选择落盘目录——可能是用户级技能目录，也可能是项目内目录——请以 CLI 的实际输出和该 Agent 的文档为准。本仓库不假定也不要求任何固定路径。

### 安装指定 Skill

在任意目录执行：

```bash
npx skills add gyb-cpu/yabo-data-skills --skill pg-function-craft
npx skills add gyb-cpu/yabo-data-skills --skill shenergy-dwd-development
```

申能技能的函数生成、改写和审查需要同时安装 `pg-function-craft`；两个技能分别安装、独立更新。安装后，将申能技能目录下的 `.env.example` 复制到业务项目根目录并命名为 `.env.shenergy`，由使用者填写建表工匠和数据库连接信息。实际配置不得提交或分享，详见申能技能的 `references/连接配置.md`。

### 自动发现安装

如果所用 CLI 支持仓库自动发现（扫描仓库内的 `skills/` 目录并列出可安装项），可以省略 `--skill`：

```bash
npx skills add gyb-cpu/yabo-data-skills
```

随后按提示选择所需技能；使用申能函数开发流程时选择两个技能。不同 CLI 版本的参数可能略有差异，必要时先查看 `npx skills add --help`。

### 不使用 CLI 时

把需要的 `skills/pg-function-craft/` 和 `skills/shenergy-dwd-development/` 各自完整复制到目标 Agent 的技能目录，具体位置由该 Agent 的文档决定。`pg-function-craft` 目录中必须保留：

```text
SKILL.md
references/
scripts/
tests/
assets/
```

申能技能需保留 `SKILL.md`、`references/` 和隐藏文件 `.env.example`；仅分发空模板，不分发实际 `.env.shenergy`。

## 安装后验证

在 `pg-function-craft` 技能根目录执行：

```bash
python scripts/verify_offline.py --json
```

预期结果：

```json
{
  "ok": true,
  "files_scanned": 20,
  "issues": [],
  "warnings": [],
  "database_connected": false
}
```

脚本只使用 Python 标准库，不连接数据库、不访问网络、不执行 SQL。只要 `ok` 为 `true`、`issues` 为空，就说明文件齐全、没有夹带连接信息或开发语料。

## 本地开发：让技能跟随仓库更新

如果你在本机维护这个仓库，又想让自己正在用的 Agent 一直加载最新版本，不要复制副本——副本会漂移，改了仓库本地还是旧的。用目录联接把本地技能目录直接指向仓库子目录：

```powershell
# 1. 现有副本改名留底（不删除，随时可回滚）
Rename-Item "$env:USERPROFILE\.minimax\skills\pg-function-craft" "pg-function-craft.bak"

# 2. 建联接到仓库的技能子目录（指向 skills\pg-function-craft，不是仓库根）
cmd /c mklink /J "$env:USERPROFILE\.minimax\skills\pg-function-craft" `
  "<仓库绝对路径>\skills\pg-function-craft"
```

验证联接生效：

```powershell
Get-Item "$env:USERPROFILE\.minimax\skills\pg-function-craft" | Select-Object LinkType,Target
```

`LinkType` 应为 `Junction`，`Target` 指向仓库子目录。此后 `git pull` 即完成技能更新，不需要重新安装。

约束：

- **仓库目录不能移动或改名**，否则联接断开，需重建。
- **分支会直接影响技能**。在草稿分支上改规则时，Agent 读到的就是草稿版；改完记得切回 `main`。
- 备份目录要放在 `skills/` **之外**（例如 `~/.minimax/skills-backup/`），否则可能被 Agent 或 CLI 当成第二个同名技能。目录名以 `.bak` 结尾时 `npx skills list` 不会收录，但仍建议移出。
- 本方案在不同 Agent 的技能目录下通用，把上面的路径换成目标 Agent 的目录即可。

不想用联接、希望由 CLI 统一管理时，改用 `npx skills add gyb-cpu/yabo-data-skills --skill pg-function-craft -g` 安装，之后 `npx skills update -g` 更新。代价是需要本机有 GitHub 凭据，且仍会保留一份副本。

## 使用

安装后直接用自然语言描述任务，Agent 会按 `SKILL.md` 的触发条件进入对应模式：

| 需求 | 模式 | 示例 |
|---|---|---|
| 新写函数、过程或触发器函数 | `generate` | “写一个按日期范围落表的 PG 函数” |
| 让已有函数符合固定风格 | `rewrite` | “按 pg-function-craft 重写这个函数，保持行为不变” |
| 检查安全、正确性、性能和风格 | `review` | “审查这个函数的性能和 SQL 写法” |

建议同时提供函数定义、PostgreSQL / Greenplum 版本、目标表 DDL 与索引、数据量与日期范围。缺失的信息会被列为待确认项，不会靠猜测补齐。

## 仓库结构

```text
yabo-data-skills/
  README.md                          本文件：通用安装与使用说明
  .gitattributes
  .gitignore
  assets/
    yabo-data-skills-hero.svg        README 封面
  tests/                             仓库级回归测试（锁定规则文本与脚本契约）
    README.md                        各测试文件的职责说明
    test_*.py                        87 个用例，Python 3.12 下全绿
  skills/
    shenergy-dwd-development/        申能 DWD 开发流程与配置模板
      SKILL.md
      CHANGELOG.md                   版本变更记录
      .env.example                   不含凭据的连接配置模板
      references/                    流程、交付、函数与连接说明
    pg-function-craft/
      SKILL.md                       技能主规则与触发入口（frontmatter 含 semver）
      README.md                      技能自身说明
      CHANGELOG.md                   版本变更记录
      assets/                        图示资源
      references/                    规则参考文档（00-11）
      scripts/verify_offline.py      离线完整性、版本、结构与部署自检
      scripts/check_sql_output.py    SQL 输出规则检查
      scripts/verify_output_contract.py  模式输出契约校验
      tests/README.md                验收场景与静态检查清单
      tests/test_*.py                输出检查器回归测试
```

## 开发与验证

改完规则或脚本，在仓库根目录跑两层检查：

```bash
# 1. 仓库级回归：规则口径、脚本契约、发布形态
python -m unittest discover -s tests -p "test_*.py" -v

# 2. 技能包自检：文件齐全、无禁用词、编码与换行合规
cd skills/pg-function-craft
python scripts/verify_offline.py --json
```

两层都通过再提交。测试文件命名带 `_red` 是历史遗留（最初先写测试后写实现），现在全部为 GREEN。

## 边界说明

- 仓库可携带无凭据的连接配置模板，但不得携带实际连接配置、凭据、开发语料、样例库、风格档案或导出元数据。
- `shenergy-dwd-development` 根据具体任务授权访问平台与数据库；`pg-function-craft` 仍只处理离线函数工程。
- `pg-function-craft` 默认不连接数据库，不执行 SQL、DDL、DML、`ANALYZE`、`VACUUM` 或 `EXPLAIN`，性能结论只做静态标记。
- 仓库不做版本发布声明；需要更新时重新执行安装命令，或按所用 CLI 的更新流程操作。
