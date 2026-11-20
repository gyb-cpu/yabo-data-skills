#!/usr/bin/env python3
"""pg-function-craft 模式输出契约校验。

只使用 Python 标准库；不连接数据库、不访问网络、不执行任何 SQL。
按 `SKILL.md` §输出契约 与 `references/08-PostgreSQL审查规则.md` §1.1 的约定，
检查一份产出是否按序包含当前模式要求的段落，并核对证据标签与性能断言。

规则：
  OUT-MODE-01  模式缺失或不在 generate/rewrite/review 之内；
  OUT-SEQ-01   缺少契约段落（每个缺失段落一条）；
  OUT-SEQ-02   段落出现顺序与契约不一致；
  OUT-LABEL-01 风险/性能段落中的要点行缺少五档证据标签之一；
  OUT-EVID-01  出现未实测的性能断言（反引号内的引用不算）。

段落识别只看标题行：去掉行首空白后以 `#` 或 `【` 开头的行；代码围栏内的行不参与识别。
每个标题按契约顺序匹配关键词，首个命中的段落规格生效。

用法：
    python scripts/verify_output_contract.py --mode generate --file out.md [--json]

退出码：0 无 error 级问题 / 1 有 error 级问题 / 2 用法或读取错误。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

MODES = ("generate", "rewrite", "review")

EVIDENCE_LABELS = (
    "static-risk",
    "inferred",
    "plan-required",
    "workload-required",
    "not verified",
)

UNVERIFIED_CLAIMS = ("更快", "实测通过", "已验证", "性能已确认")

# (段落名, 关键词)；关键词按小写比较，标题里出现任一即命中。
CONTRACTS = {
    "generate": (
        ("假设与缺失输入", ("假设与缺失输入", "假设", "assumptions")),
        ("SQL", ("sql",)),
        ("静态验证", ("静态验证",)),
        ("风险与未验证项", ("风险与未验证项",)),
        ("自检", ("自检",)),
    ),
    "rewrite": (
        ("假设与缺失输入", ("假设与缺失输入", "假设", "assumptions")),
        ("diff", ("diff",)),
        ("改动表", ("改动表",)),
        ("行为等价声明", ("行为等价",)),
        ("性能风险与未验证项", ("性能风险与未验证项",)),
        ("保留的例外", ("保留的例外",)),
    ),
    "review": (
        ("问题表", ("问题表",)),
        ("结论", ("结论",)),
        ("性能标签与未验证项", ("性能标签与未验证项",)),
        (
            "需要 schema / 执行计划 / 负载 / 人工确认的事项",
            ("待确认事项", "需要 schema", "schema / 执行计划", "人工确认"),
        ),
    ),
}

RISK_SECTION_INDEX = {"generate": 3, "rewrite": 4, "review": 2}

INLINE_CODE = re.compile(r"`[^`]*`")
FENCE = re.compile(r"^\s*(?:```|~~~)")


def _finding(rule: str, message: str, line: int | None = None,
             level: str = "error") -> dict:
    return {"rule": rule, "level": level, "line": line, "message": message}


def _headings(text: str) -> list[tuple[int, str]]:
    """返回 (行号, 标题文本)，跳过代码围栏内的行。"""
    headings: list[tuple[int, str]] = []
    in_fence = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
        elif stripped.startswith("【"):
            title = stripped.strip().strip("【】").strip()
        else:
            continue
        if title:
            headings.append((number, title))
    return headings


def _match_section(title: str, contract) -> int | None:
    lowered = title.lower()
    for index, (_, keywords) in enumerate(contract):
        for keyword in keywords:
            if keyword in lowered:
                return index
    return None


def _section_body(text: str, headings: list[tuple[int, str]], position: int) -> list[tuple[int, str]]:
    start = headings[position][0] + 1
    end = headings[position + 1][0] if position + 1 < len(headings) else None
    lines = text.splitlines()
    body = []
    for number in range(start, (end - 1) if end else len(lines)):
        if 1 <= number <= len(lines):
            body.append((number, lines[number - 1]))
    return body


def check_output(mode: str, text: str) -> dict:
    """按模式检查输出契约；ok 等价于没有 error 级 finding。"""
    if mode not in MODES:
        return {
            "ok": False,
            "mode": mode,
            "findings": [
                _finding(
                    "OUT-MODE-01",
                    f"未知模式 {mode!r}；只接受 {' / '.join(MODES)} 三种模式",
                )
            ],
        }

    contract = CONTRACTS[mode]
    findings: list[dict] = []
    headings = _headings(text)

    matched: list[tuple[int, int, str]] = []
    for line, title in headings:
        index = _match_section(title, contract)
        if index is not None:
            matched.append((line, index, title))

    present = {index for _, index, _ in matched}
    for index, (name, _) in enumerate(contract):
        if index not in present:
            findings.append(
                _finding("OUT-SEQ-01", f"缺少契约段落：{name}")
            )

    previous = -1
    out_of_order = False
    for _, index, _ in matched:
        if index < previous:
            out_of_order = True
            break
        previous = index
    if out_of_order:
        actual = [title for _, _, title in matched]
        expected = [name for name, _ in contract]
        findings.append(
            _finding(
                "OUT-SEQ-02",
                f"段落顺序与契约不一致：实际 {actual}；契约顺序 {expected}",
                matched[0][0] if matched else None,
            )
        )

    risk_index = RISK_SECTION_INDEX[mode]
    risk_position = next(
        (position for position, (_, index, _) in enumerate(matched) if index == risk_index),
        None,
    )
    if risk_position is not None:
        risk_line, risk_title = matched[risk_position][0], matched[risk_position][2]
        body_start = next(
            position for position, (line, _) in enumerate(headings) if line == risk_line
        )
        for number, raw in _section_body(text, headings, body_start):
            stripped = raw.strip()
            if not (stripped.startswith("- ") or stripped.startswith("* ")):
                continue
            if any(label in stripped for label in EVIDENCE_LABELS):
                continue
            findings.append(
                _finding(
                    "OUT-LABEL-01",
                    f"“{risk_title}”的要点缺少证据标签"
                    f"（{' / '.join(EVIDENCE_LABELS)}）：{stripped[:80]}",
                    number,
                )
            )

    for number, raw in enumerate(text.splitlines(), start=1):
        cleaned = INLINE_CODE.sub("", raw)
        hit = next((claim for claim in UNVERIFIED_CLAIMS if claim in cleaned), None)
        if hit is None:
            continue
        findings.append(
            _finding(
                "OUT-EVID-01",
                f"出现未实测的性能断言“{hit}”；只能标注 "
                f"{' / '.join(EVIDENCE_LABELS)}",
                number,
            )
        )

    return {"ok": not any(f["level"] == "error" for f in findings),
            "mode": mode, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 generate / rewrite / review 三种模式的输出契约；离线静态检查。"
    )
    parser.add_argument("--mode", required=False, help="generate / rewrite / review")
    parser.add_argument("--file", required=False, help="待校验的 Markdown 产出")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    if args.mode not in MODES:
        message = f"未知模式 {args.mode!r}；只接受 {' / '.join(MODES)}"
        if args.json:
            print(json.dumps(
                {"ok": False, "mode": args.mode, "findings": [
                    _finding("OUT-MODE-01", message)]},
                ensure_ascii=False, indent=2))
        print(message, file=sys.stderr)
        return 2

    if not args.file:
        print("缺少 --file 参数", file=sys.stderr)
        return 2

    path = pathlib.Path(args.file)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"读取文件失败：{exc}", file=sys.stderr)
        return 2

    result = check_output(args.mode, text)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"模式：{result['mode']}")
        for finding in result["findings"]:
            location = f":{finding['line']}" if finding["line"] else ""
            print(f"[{finding['level'].upper()}] {finding['rule']}{location} "
                  f"{finding['message']}")
        print("结果：通过" if result["ok"] else "结果：未通过")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
