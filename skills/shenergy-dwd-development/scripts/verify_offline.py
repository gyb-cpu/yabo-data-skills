#!/usr/bin/env python3
"""shenergy-dwd-development 离线完整性自检。

只使用 Python 3.10+ 标准库；不连接数据库、不访问网络、不执行 SQL。
检查目标：
  1. 必备文件与目录（references/、scripts/）齐全，不含真实 .env/.env.shenergy；
  2. SKILL.md frontmatter 完整且 name 与技能目录名一致、version 为合法 semver；
  3. SKILL.md frontmatter version 与 CHANGELOG.md 顶部最新版本条目一致；
  4. .env.example 仅含空值或默认端口（3306 / 5432），无真实地址或凭据；
  5. 正文不含真实连接串、云数据库主机或凭据赋值；
  6. .md / .py / .example 文件全部为 UTF-8 无 BOM、LF 换行、文件尾单个换行；
  7. scripts/*.py AST 检查不引入数据库驱动或网络模块；
  8. Markdown 中引用的本地 references/*.md 与 scripts/*.py 路径可解析。

退出码：0 = 通过；1 = 发现问题；2 = 用法或读取错误。
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "SKILL.md",
    "CHANGELOG.md",
    ".env.example",
    "references/函数与验收.md",
    "references/流程与门禁.md",
    "references/产物契约.md",
    "references/连接配置.md",
    "references/首次开发.md",
    "scripts/check_shenergy_artifacts.py",
    "scripts/parse_bi_snapshot.py",
    "scripts/generate_validation_sql.py",
    "scripts/verify_offline.py",
]

ALLOWED_SCRIPTS = {
    "scripts/check_shenergy_artifacts.py",
    "scripts/parse_bi_snapshot.py",
    "scripts/generate_validation_sql.py",
    "scripts/verify_offline.py",
}

FORBIDDEN_PATH_NAMES = {".env", ".env.shenergy", "conf.txt"}

FORBIDDEN_IMPORTS = {
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pg8000",
    "sqlalchemy",
    "pymysql",
    "mysql",
    "pyodbc",
    "sqlite3",
    "oracledb",
    "cx_Oracle",
    "requests",
    "urllib",
    "urllib3",
    "httpx",
    "http",
    "socket",
    "ftplib",
    "aiohttp",
    "smtplib",
    "ssl",
}

ENV_ALLOWED_DEFAULTS = {
    "SOURCE_MYSQL_PORT": {"", "3306"},
    "TARGET_PG_PORT": {"", "5432"},
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

REF_LINK_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:pg-function-craft/)?references/[^\s`'\"()\[\]<>，。；、]+\.md)"
)
SCRIPT_LINK_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:pg-function-craft/)?scripts/[^\s`'\"()\[\]<>，。；、]+\.py)"
)
MD_TARGET_RE = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]*)?\)")

SECRET_PATTERNS = (
    ("数据库连接串", re.compile(r"postgres(?:ql)?://|mysql://", re.IGNORECASE)),
    ("云数据库主机", re.compile(r"\.rds\.aliyuncs\.com\b", re.IGNORECASE)),
    (
        "明文凭据赋值",
        re.compile(r"(?i)\b(?:password|passwd|pwd|token)\s*[:=]\s*(?![\s<>\"']*$)[^\s<*>'\",;]+"),
    ),
)

SIBLING_PG_SCRIPTS = {
    "scripts/check_sql_output.py",
    "scripts/verify_output_contract.py",
    "scripts/verify_offline.py",
}


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def collect_files() -> list[pathlib.Path]:
    return sorted(
        p
        for p in ROOT.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def check_encoding(path: pathlib.Path, issues: list[str]) -> None:
    raw = path.read_bytes()
    r = rel(path)
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append(f"{r} 含 UTF-8 BOM")
    if b"\r\n" in raw:
        issues.append(f"{r} 使用 CRLF 换行（必须为 LF）")
    if not raw.endswith(b"\n"):
        issues.append(f"{r} 文件尾缺少换行符")
    if raw.endswith(b"\n\n"):
        issues.append(f"{r} 文件尾存在多余空行")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(f"{r} 不是合法 UTF-8：{exc}")


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fields: dict[str, str] = {}
    lines = m.group(1).splitlines()
    current_key: str | None = None
    for line in lines:
        if current_key and (line.startswith(" ") or line.startswith("\t")):
            fields[current_key] = (fields[current_key] + " " + line.strip()).strip()
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            current_key = None
            continue
        key, sep, value = line.partition(":")
        if sep:
            k = key.strip()
            v = value.strip().strip("'\"")
            if v in ("|", ">"):
                fields[k] = ""
                current_key = k
            else:
                fields[k] = v
                current_key = None
    return fields


def check_frontmatter_and_changelog(
    skill_text: str, changelog_text: str, issues: list[str]
) -> None:
    fields = parse_frontmatter(skill_text)
    if not fields:
        issues.append("SKILL.md 缺少 frontmatter（--- 区块）")
        return

    name = fields.get("name", "")
    description = fields.get("description", "")
    version = fields.get("version", "")

    if not name:
        issues.append("SKILL.md frontmatter 缺少 name")
    elif name != ROOT.name:
        issues.append(
            f"SKILL.md frontmatter name={name!r} 与目录名 {ROOT.name!r} 不一致"
        )
    if not description:
        issues.append("SKILL.md frontmatter 缺少 description")
    if not version or not VERSION_RE.fullmatch(version):
        issues.append(
            f"SKILL.md frontmatter version={version!r} 不是合法 MAJOR.MINOR.PATCH"
        )

    headings = [
        ln[3:].strip() for ln in changelog_text.splitlines() if ln.startswith("## ")
    ]
    if not headings:
        issues.append("CHANGELOG.md 缺少版本条目（## X.Y.Z）")
    elif version:
        newest = headings[0].split()[0]
        if newest != version:
            issues.append(
                f"SKILL.md version={version} 与 CHANGELOG.md 最新版本 {newest} 不一致"
            )


def check_env_example(env_path: pathlib.Path, issues: list[str]) -> None:
    try:
        text = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(f".env.example 读取失败：{exc}")
        return

    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            issues.append(f".env.example:{idx} 非法行：{stripped}")
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        val = val.strip()
        allowed = ENV_ALLOWED_DEFAULTS.get(key, {""})
        if val not in allowed:
            issues.append(
                f".env.example:{idx} 变量 {key} 含非空/非默认值（禁止随包携带真实配置或凭据）"
            )


def check_python_scripts(files: list[pathlib.Path], issues: list[str]) -> None:
    for path in files:
        if path.suffix != ".py":
            continue
        r = rel(path)
        if r not in ALLOWED_SCRIPTS:
            issues.append(f"存在未登记的 Python 文件：{r}")
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=r)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            issues.append(f"{r} 语法或读取错误：{exc}")
            continue

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        offenders = sorted(imported & FORBIDDEN_IMPORTS)
        if offenders:
            issues.append(
                f"{r} 引入禁止的数据库或网络模块：{', '.join(offenders)}"
            )


def check_md_links_and_secrets(
    path: pathlib.Path, text: str, issues: list[str], warnings: list[str]
) -> None:
    r = rel(path)

    for label, pat in SECRET_PATTERNS:
        m = pat.search(text)
        if m:
            line = text[: m.start()].count("\n") + 1
            issues.append(f"{r}:{line} 命中疑似{label}：{m.group(0)[:60]}")

    for m in REF_LINK_RE.finditer(text):
        target = m.group(1)
        line = text[: m.start()].count("\n") + 1
        if target.startswith("pg-function-craft/"):
            sibling = ROOT.parent / target
            if (ROOT.parent / "pg-function-craft").is_dir() and not sibling.is_file():
                issues.append(f"{r}:{line} 引用的跨技能文件不存在：{target}")
        else:
            if not (ROOT / target).is_file():
                issues.append(f"{r}:{line} 引用的参考文件不存在：{target}")

    for m in SCRIPT_LINK_RE.finditer(text):
        target = m.group(1)
        line = text[: m.start()].count("\n") + 1
        if target.startswith("pg-function-craft/"):
            sibling = ROOT.parent / target
            if (ROOT.parent / "pg-function-craft").is_dir() and not sibling.is_file():
                issues.append(f"{r}:{line} 引用的跨技能脚本不存在：{target}")
        elif target in SIBLING_PG_SCRIPTS:
            sibling = ROOT.parent / "pg-function-craft" / target
            if (ROOT.parent / "pg-function-craft").is_dir() and not sibling.is_file():
                issues.append(f"{r}:{line} 引用的 pg-function-craft 脚本不存在：{target}")
        else:
            if not (ROOT / target).is_file():
                issues.append(f"{r}:{line} 引用的脚本不存在：{target}")

    for m in MD_TARGET_RE.finditer(text):
        target = m.group(1).strip()
        if not target or target.startswith(("http://", "https://", "file://", "<")):
            continue
        if target.startswith("pg-function-craft/"):
            continue
        resolved = (path.parent / target).resolve()
        if ROOT.resolve() in resolved.parents or resolved == ROOT.resolve():
            if not resolved.exists():
                line = text[: m.start()].count("\n") + 1
                issues.append(f"{r}:{line} Markdown 链接目标不存在：{target}")

    if "TODO" in text or "TBD" in text:
        warnings.append(f"{r} 含 TODO/TBD，交付前请确认是否有意保留")


def run() -> tuple[list[str], list[str], int]:
    issues: list[str] = []
    warnings: list[str] = []

    files = collect_files()
    existing = {rel(p) for p in files}

    for path in files:
        parts = set(path.relative_to(ROOT).parts)
        blocked = parts & FORBIDDEN_PATH_NAMES
        if blocked:
            issues.append(f"禁止随技能携带实际配置：{rel(path)}（命中 {', '.join(sorted(blocked))}）")

    for req in REQUIRED_FILES:
        if req not in existing:
            issues.append(f"缺少必备文件：{req}")

    for path in files:
        if path.suffix in {".md", ".py", ".example"} or path.name == ".env.example":
            check_encoding(path, issues)
            if path.suffix == ".md":
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                check_md_links_and_secrets(path, text, issues, warnings)

    check_python_scripts(files, issues)

    env_path = ROOT / ".env.example"
    if env_path.is_file():
        check_env_example(env_path, issues)

    skill_path = ROOT / "SKILL.md"
    changelog_path = ROOT / "CHANGELOG.md"
    if skill_path.is_file() and changelog_path.is_file():
        try:
            check_frontmatter_and_changelog(
                skill_path.read_text(encoding="utf-8"),
                changelog_path.read_text(encoding="utf-8"),
                issues,
            )
        except UnicodeDecodeError:
            pass

    return issues, warnings, len(files)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        description="shenergy-dwd-development 离线完整性自检（不连库、不联网）。"
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出自检结果")
    args = parser.parse_args(argv)

    try:
        issues, warnings, files_scanned = run()
    except OSError as exc:
        print(f"读取文件失败：{exc}", file=sys.stderr)
        return 2

    result = {
        "ok": not issues,
        "root": str(ROOT),
        "files_scanned": files_scanned,
        "issues": issues,
        "warnings": warnings,
        "database_connected": False,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"shenergy-dwd-development 离线自检：{ROOT}")
        print(f"扫描文件：{files_scanned}")
        print("数据库连接：未建立（离线静态检查）")
        for w in warnings:
            print(f"[WARN] {w}")
        for issue in issues:
            print(f"[FAIL] {issue}")
        print("结果：" + ("通过" if not issues else f"失败（{len(issues)} 项）"))

    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
