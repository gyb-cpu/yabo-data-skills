"""RED 阶段测试：模式输出契约的可执行校验（目标能力尚未实现）。

被测能力
--------
`SKILL.md` 的「输出契约」一节以及 `references/08-PostgreSQL审查规则.md` §1.1 规定了三种模式各自
必须按序出现的段落，但技能里只有 `scripts/verify_offline.py` 检查文件/语料/编码，没有任何东西能
判断"一份产出是否满足当前模式的输出契约"。本测试把该契约固化成可判定的行为，作为未来实现的验收
标准。

期望的最小实现
--------------
新增 `scripts/verify_output_contract.py`（仅标准库，不连库、不执行 SQL）：

- `MODES = ("generate", "rewrite", "review")`
- `check_output(mode: str, text: str) -> dict`：返回
  `{"ok": bool, "mode": str, "findings": [{"rule": str, "level": "error"|"warn",
  "line": int | None, "message": str}]}`；`ok` 等价于"没有 error 级 finding"。
- 命令行：`python scripts/verify_output_contract.py --mode MODE --file PATH [--json]`，
  通过 0 / 有问题 1 / 用法问题 2。

规则 ID
-------
- `OUT-MODE-01`  模式缺失或不在 `generate`/`rewrite`/`review` 三者之内。
- `OUT-SEQ-01`   缺少契约段落；每个缺失段落一条 finding，`message` 必须含该段落名。
- `OUT-SEQ-02`   段落出现顺序与契约不一致。
- `OUT-LABEL-01` 风险/性能段落中的要点行缺少五档证据标签之一：
  `static-risk` / `inferred` / `plan-required` / `workload-required` / `not verified`。
- `OUT-EVID-01`  出现未实测的性能断言（`更快` / `实测通过` / `已验证` / `性能已确认`），
  反引号内的引用不算。

段落识别
--------
只认"标题行"：去掉行首空白后以 `#` 或 `【` 开头的行。按模式逐个匹配关键词（首个命中的段落规格生效），
要求每个契约段落至少命中一次，且命中顺序与契约顺序一致。

契约段落顺序（取自 `SKILL.md` §输出契约 与 `08` §1.1）
--------------------------------------------------
- `generate`：假设与缺失输入 → SQL → 静态验证 → 风险与未验证项 → 自检
- `rewrite` ：假设与缺失输入 → diff → 改动表 → 行为等价声明 → 性能风险与未验证项 → 保留的例外
- `review`  ：问题表 → 结论 → 性能标签与未验证项 → 待确认事项（schema/执行计划/负载/人工确认）
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

SKILL_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT_SCRIPT = SKILL_ROOT / "scripts" / "verify_output_contract.py"

RISK_SECTION_NAMES = {
    "generate": "风险与未验证项",
    "rewrite": "性能风险与未验证项",
    "review": "性能标签与未验证项",
}

COMPLIANT_GENERATE = textwrap.dedent(
    """\
    ## 假设与缺失输入

    - 目标表按 `t_order(id bigint, stat_date date, amount numeric)` 处理。
    - 缺失输入：索引定义、行数、PostgreSQL 版本、权限。

    ## SQL

    ```sql
    CREATE OR REPLACE FUNCTION f_order_stats(p_start date)
    RETURNS TABLE (stat_date date, total numeric)
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN QUERY
        SELECT o.stat_date
             , sum(o.amount)
          FROM t_order AS o
         WHERE o.stat_date >= p_start
         GROUP BY o.stat_date;
    END;
    $$;
    ```

    ## 静态验证

    - 用户侧执行 `EXPLAIN (ANALYZE, BUFFERS) SELECT ...`；本技能不执行计划。
    - 结构等价：格式化前后语句序列一致。

    ## 风险与未验证项

    - 日期谓词写为 `o.stat_date >= p_start`，列侧裸露；是否走索引：plan-required。
    - 统计信息可能过期，实际收益取决于负载：workload-required。

    ## 自检

    - 命名 `f_`/`p_`、函数体内八字段头、前置逗号、`SECURITY INVOKER` 逐条自检通过。
    """
)

COMPLIANT_REVIEW = textwrap.dedent(
    """\
    | 级别 | 规则 ID | 位置 | 证据 | 后果 | 整改建议 |
    |---|---|---|---|---|---|
    | WARNING | REV-P01 | demo.sql:42 | `q.riqi::date >= p_start` 列侧 cast | 可能无法走索引 | 改为 `q.riqi >= p_start::date` |

    ## 问题表

    - 共 1 条，其中 BLOCKER 0 条。

    ## 结论

    - 无 BLOCKER，存在 1 条 WARNING，需要补输入后再判定计划。

    ## 性能标签与未验证项

    - 索引可用性：plan-required。
    - 实际负载收益：not verified。

    ## 需要 schema / 执行计划 / 负载 / 人工确认的事项

    - 需要目标表 DDL、索引定义与真实执行计划。
    """
)

MISSING_SECTION_GENERATE = textwrap.dedent(
    """\
    ## 假设与缺失输入

    - 假设目标表为 `t_order`。

    ## SQL

    ```sql
    SELECT 1;
    ```

    ## 自检

    - 命名、排版逐条自检通过。
    """
)

OUT_OF_ORDER_REVIEW = textwrap.dedent(
    """\
    ## 结论

    - 无 BLOCKER。

    ## 问题表

    - 共 0 条。

    ## 性能标签与未验证项

    - 索引可用性：plan-required。

    ## 需要 schema / 执行计划 / 负载 / 人工确认的事项

    - 需要目标表 DDL。
    """
)

UNLABELLED_PERF_GENERATE = textwrap.dedent(
    """\
    ## 假设与缺失输入

    - 假设目标表为 `t_order`。

    ## SQL

    ```sql
    SELECT 1;
    ```

    ## 静态验证

    - 结构等价，无语法错误。

    ## 风险与未验证项

    - 加上索引后扫描行数会明显下降。

    ## 自检

    - 命名、排版逐条自检通过。
    """
)

UNVERIFIED_CLAIM_REVIEW = textwrap.dedent(
    """\
    ## 问题表

    - 共 0 条。

    ## 结论

    - 改完之后查询更快，性能已确认。

    ## 性能标签与未验证项

    - 索引可用性：plan-required。

    ## 需要 schema / 执行计划 / 负载 / 人工确认的事项

    - 需要目标表 DDL。
    """
)

QUOTED_CLAIM_REVIEW = textwrap.dedent(
    """\
    ## 问题表

    - 共 0 条。

    ## 结论

    - 不得把 `更快` 写成结论，收益仍未验证。

    ## 性能标签与未验证项

    - 索引可用性：plan-required。

    ## 需要 schema / 执行计划 / 负载 / 人工确认的事项

    - 需要目标表 DDL。
    """
)

COMPLIANT_REWRITE = textwrap.dedent(
    """\
    ## 假设与缺失输入

    - 假设原函数语义保持不变，索引定义未知。

    ## 统一 diff

    ```diff
    --- old.sql
    +++ new.sql
    @@ -1,1 +1,1 @@
    -WHERE q.riqi::date >= p_start
    +WHERE q.riqi >= p_start::date
    ```

    ## 改动表

    - 日期谓词改为列侧裸露；纯版式改动单独成组。

    ## 行为等价声明

    - 签名、返回类型、返回码、异常文本不变；差异仅排版与日期比较类型。

    ## 性能风险与未验证项

    - 合并两张临时表需重算中间结果，计划是否变化：plan-required。
    - 日期列若为文本类型，比较语义可能变化：workload-required。

    ## 保留的例外

    - 保留原有 `VOLATILE`，未按固定风格调整。
    """
)

MISSING_DIFF_REWRITE = textwrap.dedent(
    """\
    ## 假设与缺失输入

    - 假设原函数语义保持不变。

    ## 改动表

    - 仅调整命名与头部。

    ## 行为等价声明

    - 签名、返回码、异常文本不变。

    ## 性能风险与未验证项

    - 索引可用性：plan-required。

    ## 保留的例外

    - 无。
    """
)


_LOADED = {}


def load_contract_module():
    """加载待实现的契约校验器；缺失时给出明确的 RED 失败信息。"""
    if "module" in _LOADED:
        return _LOADED["module"]
    if not CONTRACT_SCRIPT.is_file():
        raise AssertionError(
            "目标能力缺失：找不到 %s。SKILL.md「输出契约」目前只是散文，"
            "没有任何可执行的模式-段落校验器。" % CONTRACT_SCRIPT.relative_to(SKILL_ROOT)
        )
    spec = importlib.util.spec_from_file_location("pgfc_output_contract", CONTRACT_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("无法导入 %s" % CONTRACT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    for attr in ("MODES", "check_output"):
        if not hasattr(module, attr):
            raise AssertionError("verify_output_contract.py 缺少公开接口：%s" % attr)
    _LOADED["module"] = module
    return module


class ModeOutputContractTest(unittest.TestCase):
    def setUp(self):
        self.module = load_contract_module()

    def check(self, mode, text):
        result = self.module.check_output(mode, text)
        self.assertIsInstance(result, dict, "check_output 必须返回 dict")
        for key in ("ok", "mode", "findings"):
            self.assertIn(key, result, "返回值缺少字段：%s" % key)
        self.assertIsInstance(result["findings"], list)
        for finding in result["findings"]:
            for key in ("rule", "level", "message"):
                self.assertIn(key, finding, "finding 缺少字段：%s" % key)
            self.assertIn(finding["level"], ("error", "warn"))
            self.assertTrue(finding["rule"].startswith("OUT-"), finding["rule"])
        return result

    @staticmethod
    def rules(result):
        return [finding["rule"] for finding in result["findings"]]

    def test_api_surface(self):
        self.assertEqual(
            tuple(self.module.MODES), ("generate", "rewrite", "review")
        )

    def test_compliant_generate_passes(self):
        result = self.check("generate", COMPLIANT_GENERATE)
        self.assertTrue(result["ok"], "合规的 generate 产出被误判：%s" % self.rules(result))
        self.assertEqual(result["findings"], [])

    def test_compliant_review_passes(self):
        result = self.check("review", COMPLIANT_REVIEW)
        self.assertTrue(result["ok"], "合规的 review 产出被误判：%s" % self.rules(result))
        self.assertEqual(result["findings"], [])

    def test_compliant_rewrite_passes(self):
        result = self.check("rewrite", COMPLIANT_REWRITE)
        self.assertTrue(result["ok"], "合规的 rewrite 产出被误判：%s" % self.rules(result))
        self.assertEqual(result["findings"], [])

    def test_rewrite_missing_diff_is_reported(self):
        result = self.check("rewrite", MISSING_DIFF_REWRITE)
        self.assertFalse(result["ok"], "缺少 diff 段落的 rewrite 被判定为通过")
        messages = " ".join(
            finding["message"]
            for finding in result["findings"]
            if finding["rule"] == "OUT-SEQ-01"
        )
        self.assertIn("diff", messages, "缺失的 diff 段落未被点名")

    def test_missing_section_is_reported(self):
        result = self.check("generate", MISSING_SECTION_GENERATE)
        self.assertFalse(result["ok"], "缺少段落的产出被判定为通过")
        self.assertIn("OUT-SEQ-01", self.rules(result))
        messages = " ".join(
            finding["message"]
            for finding in result["findings"]
            if finding["rule"] == "OUT-SEQ-01"
        )
        for section in ("静态验证", RISK_SECTION_NAMES["generate"]):
            self.assertIn(section, messages, "缺少段落未被点名：%s" % section)

    def test_out_of_order_sections_are_reported(self):
        result = self.check("review", OUT_OF_ORDER_REVIEW)
        self.assertFalse(result["ok"], "段落顺序颠倒的产出被判定为通过")
        self.assertIn("OUT-SEQ-02", self.rules(result))

    def test_performance_bullet_without_label_is_reported(self):
        result = self.check("generate", UNLABELLED_PERF_GENERATE)
        self.assertFalse(result["ok"], "无证据标签的性能要点被判定为通过")
        self.assertIn("OUT-LABEL-01", self.rules(result))

    def test_unverified_performance_claim_is_reported(self):
        result = self.check("review", UNVERIFIED_CLAIM_REVIEW)
        self.assertFalse(result["ok"], "未实测的性能断言没有被拦下")
        self.assertIn("OUT-EVID-01", self.rules(result))

    def test_backticked_claim_is_not_flagged(self):
        result = self.check("review", QUOTED_CLAIM_REVIEW)
        self.assertTrue(
            result["ok"],
            "反引号内的规则引用被误判为性能断言：%s" % self.rules(result),
        )

    def test_unknown_mode_is_rejected(self):
        result = self.module.check_output("optimize", COMPLIANT_REVIEW)
        self.assertFalse(result["ok"], "第四种模式被接受，违反三模式边界")
        self.assertIn("OUT-MODE-01", self.rules(result))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            good = tmpdir / "good.md"
            bad = tmpdir / "bad.md"
            good.write_text(COMPLIANT_GENERATE, encoding="utf-8")
            bad.write_text(MISSING_SECTION_GENERATE, encoding="utf-8")

            def run(*args):
                env = dict(os.environ)
                env["PYTHONIOENCODING"] = "utf-8"
                return subprocess.run(
                    [sys.executable, str(CONTRACT_SCRIPT), *args],
                    cwd=str(SKILL_ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )

            ok = run("--mode", "generate", "--file", str(good))
            self.assertEqual(ok.returncode, 0, "合规产出的退出码应为 0：%s%s" % (ok.stdout, ok.stderr))

            failed = run("--mode", "generate", "--file", str(bad))
            self.assertEqual(failed.returncode, 1, "违规产出的退出码应为 1：%s" % failed.stdout)
            self.assertIn("OUT-SEQ-01", failed.stdout, "CLI 未输出规则 ID")

            usage = run("--mode", "nope", "--file", str(good))
            self.assertEqual(usage.returncode, 2, "未知模式应作为用法错误返回 2")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
