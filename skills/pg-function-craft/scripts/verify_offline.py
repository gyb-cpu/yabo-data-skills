#!/usr/bin/env python3
"""pg-function-craft 离线自检。

只使用 Python 标准库；不连接数据库、不访问网络、不执行任何 SQL。
检查目标：
  1. 必备文件与安装目录（assets/、references/、scripts/、tests/）齐全，
     且不存在语料/元数据/风格档案/连接配置；
  2. 正文没有连接串、数据库驱动、云数据库主机、凭据赋值；
  3. 没有任何语料计数、样例路径、元数据文件名或个人资料；
  4. 正文没有内部称呼、已删除的模式、实测性能标签或来源统计；
  5. 关键边界短语存在（默认不连库、物化理由、日期列不做 ::date）；
  6. 文本为 UTF-8 无 BOM、LF 换行、文件尾单个换行；
  7. 只保留离线脚本与测试文件，且它们不引入数据库驱动或网络模块；
  8. 文档引用可解析：`assets/*`、`references/*.md`、`X.md 第 N 节` / `X.md §N`；
  9. frontmatter 有 name 与 description，且 name 与安装目录名一致。

章节号按文档的二级标题（`##`）顺序计：第 N 节即第 N 个 `##` 标题；
标题自带的编号（如 `## 0.`）同样计入，`07`/`08` 的 §0.x 因此可解析。

退出码：0 通过 / 1 发现问题 / 2 用法问题。
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
    "README.md",
    "CHANGELOG.md",
    "assets/pg-function-craft-hero.svg",
    "references/00-风格与边界.md",
    "references/01-基线规范.md",
    "references/02-反模式.md",
    "references/04-固定风格.md",
    "references/05-重写协议.md",
    "references/06-SQL排版规范.md",
    "references/07-性能优化规则.md",
    "references/08-PostgreSQL审查规则.md",
    "references/09-工程与函数结构规范.md",
    "references/10-PLpgSQL语法与函数形态.md",
    "references/11-增量与水位线.md",
    "tests/README.md",
]

FORBIDDEN_PATH_PARTS = {"samples", "metadata", "风格档案.md", "conf.txt", ".env"}

TEXT_SUFFIXES = {".md", ".txt", ".json", ".sql"}

HARD_PATTERNS = [
    ("数据库连接串", re.compile(r"postgres(?:ql)?://", re.IGNORECASE)),
    ("数据库驱动", re.compile(r"\b(?:psycopg2?|asyncpg|pg8000|sqlalchemy)\b", re.IGNORECASE)),
    ("云数据库主机", re.compile(r"\.rds\.aliyuncs\.com\b", re.IGNORECASE)),
    ("凭据赋值", re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*[^\s<*>]")),
]

INTERNAL_TERMS = [
    ("内部称呼", re.compile(r"\u63a8\u5e7f\u7248|\u63a8\u5e7f\u5305|\u63a8\u5e7f\u4f7f\u7528")),
    ("已删除的模式", re.compile(r"dis" r"till", re.IGNORECASE)),
    ("个人资料", re.compile(r"\u4f5c\u8005\u753b\u50cf")),
    ("实测性能标签", re.compile(r"EXPLAIN-" r"verified", re.IGNORECASE)),
    ("语料计数", re.compile(r"(?<!\d)1" r"49(?!\d)")),
]

CORPUS_PATTERNS = [
    ("分母式语料计数", re.compile(r"\b\d{1,3}/\d{2,3}\b")),
    ("样例路径", re.compile(r"sam" r"ples/raw")),
    ("元数据文件", re.compile(r"manifest\.jsonl|checksums\.sha256|export-summary\.json")),
    ("样例标识", re.compile(r"sample_id")),
    ("风格档案规则号", re.compile(r"\bN-\d{2}\b")),
]

POLICY_DOC = "references/00-风格与边界.md"

REQUIRED_PHRASES = {
    "SKILL.md": ["默认不连库", "static-risk", "not verified", "物化", "::date", "固定风格"],
    "README.md": ["不连接数据库", "物化", "::date", "verify_offline.py", "固定风格"],
    "references/04-固定风格.md": ["f_", "p_", "v_", "前置逗号", "SECURITY INVOKER", "USING"],
    POLICY_DOC: ["默认不连库", "物化", "::date"],
    "references/07-性能优化规则.md": ["默认不连库", "::date", "物化"],
    "references/09-工程与函数结构规范.md": ["物化"],
    "references/11-增量与水位线.md": ["回看", "update_time", "逻辑删除"],
}

REQUIRED_DIRS = ["assets", "references", "scripts", "tests"]

# 允许的 Python 文件：三个离线静态检查脚本 + 技能自带测试。
ALLOWED_SCRIPTS = {
    "scripts/verify_offline.py",
    "scripts/check_sql_output.py",
    "scripts/verify_output_contract.py",
}
TEST_FILE = re.compile(r"^tests/test_[^/]+\.py$")

FORBIDDEN_IMPORTS = {
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pg8000",
    "sqlalchemy",
    "requests",
    "urllib",
    "urllib3",
    "httpx",
    "http",
    "socket",
    "ftplib",
}

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
SECTION_HEADING = re.compile(r"^##(?!#)[ \t]+\S")
DOC_REFERENCE = re.compile(
    r"(?<![\w/.-])references/[^\s`'\"()\[\]<>，。；、]+\.md"
)
BARE_REFERENCE = re.compile(
    r"(?<![\w/.-])([0-9]{2}-[^\s`'\"()\[\]<>，。；、]+\.md)"
)
ASSET_REFERENCE = re.compile(
    r"assets/[^\s`'\"()\[\]<>，。；、]+\.(?:svg|png|jpe?g|gif|webp)"
)
SECTION_REFERENCE = re.compile(
    r"`?([A-Za-z0-9_./\-\u4e00-\u9fff]+\.md)`?\s*(?:第\s*(\d+)\s*节|§\s*(\d+))"
)


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def collect_files() -> list[pathlib.Path]:
    return sorted(
        p
        for p in ROOT.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def check_paths(files: list[pathlib.Path], issues: list[str]) -> None:
    for path in files:
        parts = set(path.relative_to(ROOT).parts)
        blocked = parts & FORBIDDEN_PATH_PARTS
        if blocked:
            issues.append(f"禁止路径：{rel(path)}（命中 {', '.join(sorted(blocked))}）")


def line_of(text: str, position: int) -> int:
    return text[:position].count("\n") + 1


def check_layout(files: list[pathlib.Path], issues: list[str]) -> None:
    for name in REQUIRED_DIRS:
        if not (ROOT / name).is_dir():
            issues.append(f"缺少安装目录：{name}/（安装清单要求保留）")

    assets = ROOT / "assets"
    if assets.is_dir() and not any(
        "assets" in path.relative_to(ROOT).parts for path in files
    ):
        issues.append("安装目录 assets/ 为空，README 内嵌图示会失效")


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


def check_frontmatter(text: str, issues: list[str]) -> None:
    fields = parse_frontmatter(text)
    if not fields:
        issues.append("SKILL.md 缺少 frontmatter（--- 包围的元数据块），无法被技能发现")
        return

    name = fields.get("name", "")
    description = fields.get("description", "")
    version = fields.get("version", "")
    if not name:
        issues.append("SKILL.md frontmatter 缺少 name，安装与路由无法定位技能")
    elif name != ROOT.name:
        issues.append(
            f"安装目录名 {ROOT.name} 与 frontmatter name: {name} 不一致，发现与更新会错位"
        )
    if not description:
        issues.append(
            "SKILL.md frontmatter 缺少 description，技能发现与触发会退化"
        )
    if not version or not VERSION_PATTERN.fullmatch(version):
        issues.append(
            "SKILL.md frontmatter 缺少有效 version，必须使用 MAJOR.MINOR.PATCH"
        )


def section_headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if SECTION_HEADING.match(line)]


def section_numbers(text: str) -> set[int]:
    headings = section_headings(text)
    numbers = set(range(1, len(headings) + 1))
    for heading in headings:
        match = re.match(r"^##(?!#)[ \t]+(\d+)(?:[.、．]|\s|$)", heading)
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def resolve_doc(doc: str) -> pathlib.Path | None:
    for candidate in (ROOT / doc, ROOT / "references" / doc):
        if candidate.is_file():
            return candidate
    return None


def check_references(path: pathlib.Path, text: str, issues: list[str]) -> None:
    name = rel(path)

    # 所有 Markdown 都校验 `references/*.md` 引用；外部仓库路径写在
    # `postgres-writing-guidelines/references/...` 之下，不会被误判为本地文件。
    for match in DOC_REFERENCE.finditer(text):
        target = match.group(0)
        if not (ROOT / target).is_file():
            issues.append(
                f"{name}:{line_of(text, match.start())} 引用的文件不存在：{target}"
            )

    for match in BARE_REFERENCE.finditer(text):
        target = match.group(1)
        if not (ROOT / target).is_file() and not (
            ROOT / "references" / target
        ).is_file():
            issues.append(
                f"{name}:{line_of(text, match.start(1))} 引用的参考文件不存在：references/{target}"
            )

    for match in ASSET_REFERENCE.finditer(text):
        target = match.group(0)
        if not (ROOT / target).is_file():
            issues.append(
                f"{name}:{line_of(text, match.start())} 引用的资源不存在：{target}"
            )

    for match in SECTION_REFERENCE.finditer(text):
        doc = match.group(1)
        number = int(match.group(2) or match.group(3))
        line = line_of(text, match.start())
        target = resolve_doc(doc)
        if target is None:
            issues.append(f"{name}:{line} 引用的文档不存在：{doc}")
            continue
        try:
            target_text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if number not in section_numbers(target_text):
            issues.append(
                f"{name}:{line} 引用的章节不存在：{doc} 第 {number} 节"
                f"（{doc} 共 {len(section_headings(target_text))} 节）"
            )


def check_text(
    path: pathlib.Path, text: str, issues: list[str], warnings: list[str]
) -> None:
    name = rel(path)

    for label, pattern in HARD_PATTERNS:
        match = pattern.search(text)
        if match:
            line = text[: match.start()].count("\n") + 1
            issues.append(f"{name}:{line} 命中“{label}”：{match.group(0)[:60]}")

    for label, pattern in INTERNAL_TERMS:
        match = pattern.search(text)
        if match:
            line = text[: match.start()].count("\n") + 1
            issues.append(f"{name}:{line} 命中“{label}”：{match.group(0)[:60]}")

    for label, pattern in CORPUS_PATTERNS:
        match = pattern.search(text)
        if match:
            line = text[: match.start()].count("\n") + 1
            issues.append(f"{name}:{line} 命中“{label}”：{match.group(0)[:60]}")

    for phrase in REQUIRED_PHRASES.get(name, []):
        if phrase not in text:
            issues.append(f"{name} 缺少边界短语：{phrase}")

    if "TODO" in text or "TBD" in text:
        warnings.append(f"{name} 含 TODO/TBD，发布前确认是否有意保留")


def check_encoding(path: pathlib.Path, issues: list[str]) -> None:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append(f"{rel(path)} 含 UTF-8 BOM")
    if b"\r\n" in raw:
        issues.append(f"{rel(path)} 使用 CRLF 换行")
    if not raw.endswith(b"\n"):
        issues.append(f"{rel(path)} 文件尾缺少换行")
    if raw.endswith(b"\n\n"):
        issues.append(f"{rel(path)} 文件尾存在多余空行")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(f"{rel(path)} 不是合法 UTF-8：{exc}")


def check_python(files: list[pathlib.Path], issues: list[str]) -> None:
    for path in files:
        if path.suffix != ".py":
            continue
        name = rel(path)
        if name not in ALLOWED_SCRIPTS and not TEST_FILE.match(name):
            issues.append(
                f"存在额外 Python 文件：{name}（技能只保留离线脚本与 tests/test_*.py）"
            )
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        except (OSError, UnicodeDecodeError, SyntaxError):
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
                f"{name} 引入数据库驱动或网络模块：{', '.join(offenders)}"
            )


def run() -> tuple[list[str], list[str], int]:
    issues: list[str] = []
    warnings: list[str] = []

    files = collect_files()
    check_paths(files, issues)
    check_layout(files, issues)
    check_python(files, issues)

    existing = {rel(p) for p in files}
    for required in REQUIRED_FILES:
        if required not in existing:
            issues.append(f"缺少必备文件：{required}")

    for path in files:
        if path.suffix in TEXT_SUFFIXES:
            check_encoding(path, issues)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            check_text(path, text, issues, warnings)
            if path.suffix == ".md":
                check_references(path, text, issues)

    skill_md = ROOT / "SKILL.md"
    if skill_md.is_file():
        try:
            check_frontmatter(skill_md.read_text(encoding="utf-8"), issues)
        except UnicodeDecodeError:
            pass

    return issues, warnings, len(files)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pg-function-craft 离线自检：不连数据库、不访问网络、不执行 SQL。"
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args()

    try:
        issues, warnings, file_count = run()
    except OSError as exc:
        print(f"读取文件失败：{exc}", file=sys.stderr)
        return 2

    result = {
        "ok": not issues,
        "root": str(ROOT),
        "files_scanned": file_count,
        "issues": issues,
        "warnings": warnings,
        "database_connected": False,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"pg-function-craft 离线自检：{ROOT}")
        print(f"扫描文件：{file_count}")
        print("数据库连接：未建立（离线静态检查）")
        for warning in warnings:
            print(f"[WARN] {warning}")
        for issue in issues:
            print(f"[FAIL] {issue}")
        if issues:
            print(f"\n结果：失败（{len(issues)} 项）")
        else:
            print("\n结果：通过")

    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
