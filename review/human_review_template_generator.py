"""Human Review comment template helper.

This module only generates review-writing templates. It never updates
candidate status, review_comment, shadow projects, feature flags, or production
logic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GUIDELINE_PATH = ROOT / "reports" / "human_review_guideline.md"


class HumanReviewTemplateGenerator:
    """Generate status-specific Human Review comment templates."""

    VALID_STATUSES = {
        "REVIEW_REQUIRED",
        "APPROVED",
        "WATCH",
        "REJECTED",
        "IMPLEMENTED",
        "REVERTED",
    }

    COMMENT_GUIDE = {
        "REVIEW_REQUIRED": {
            "policy": "OPTIONAL",
            "label": "不要。ただし気になった点がある場合は記録推奨。",
        },
        "APPROVED": {
            "policy": "STRONGLY_RECOMMENDED",
            "label": "必須推奨。Shadowまたは実装候補へ進める根拠を残す。",
        },
        "WATCH": {
            "policy": "STRONGLY_RECOMMENDED",
            "label": "必須推奨。何を次回監視するかを残す。",
        },
        "REJECTED": {
            "policy": "STRONGLY_RECOMMENDED",
            "label": "必須推奨。却下理由と再検討条件を残す。",
        },
        "IMPLEMENTED": {
            "policy": "STRONGLY_RECOMMENDED",
            "label": "必須推奨。採用理由、検証結果、残課題を残す。",
        },
        "REVERTED": {
            "policy": "STRONGLY_RECOMMENDED",
            "label": "必須推奨。戻した理由と再発防止の観点を残す。",
        },
    }

    TEMPLATES = {
        "REVIEW_REQUIRED": [
            "気になった点:",
            "追加確認事項:",
            "判断保留の理由:",
            "次に見るデータ:",
        ],
        "APPROVED": [
            "承認理由:",
            "Shadowへ進める根拠:",
            "期待効果:",
            "想定副作用:",
            "確認すべき指標:",
        ],
        "WATCH": [
            "保留理由:",
            "監視する観点:",
            "次回確認条件:",
            "追加データが必要な条件:",
            "現時点の懸念:",
        ],
        "REJECTED": [
            "却下理由:",
            "根拠:",
            "再検討条件:",
            "代替候補:",
        ],
        "IMPLEMENTED": [
            "採用理由:",
            "期待した改善:",
            "検証結果:",
            "Production影響:",
            "残課題:",
        ],
        "REVERTED": [
            "Revert理由:",
            "発生した問題:",
            "影響範囲:",
            "再検討条件:",
            "残すべき教訓:",
        ],
    }

    UNKNOWN_TEMPLATE = [
        "確認内容:",
        "判断:",
        "根拠:",
        "次の対応:",
    ]

    def normalize_status(self, status: object) -> str:
        if status is None:
            return "UNKNOWN"
        normalized = str(status).strip().upper()
        return normalized if normalized in self.VALID_STATUSES else "UNKNOWN"

    def comment_policy(self, status: object) -> dict[str, str]:
        normalized = self.normalize_status(status)
        if normalized == "UNKNOWN":
            return {
                "policy": "UNDETERMINED",
                "label": "statusが不明なため、まず正しいstatusを確認する。",
            }
        return dict(self.COMMENT_GUIDE[normalized])

    def template_for(self, status: object) -> str:
        normalized = self.normalize_status(status)
        lines = self.TEMPLATES.get(normalized, self.UNKNOWN_TEMPLATE)
        title = normalized if normalized != "UNKNOWN" else "UNKNOWN_STATUS"
        return "\n".join([f"[{title}]", *lines])

    def suggestion_for(self, status: object, comment_state: object = "") -> dict[str, str]:
        normalized = self.normalize_status(status)
        comment_state_text = str(comment_state or "").upper()
        policy = self.comment_policy(normalized)
        needs_template = (
            normalized != "UNKNOWN"
            and policy["policy"] == "STRONGLY_RECOMMENDED"
            and comment_state_text in {"", "EMPTY", "WHITESPACE_ONLY", "MISSING_KEY"}
        )
        if normalized == "UNKNOWN":
            reason = "statusが不明なため、汎用確認テンプレートを表示します。"
            recommended = "UNKNOWN_STATUS"
        elif needs_template:
            reason = f"{normalized} はコメント必須推奨のため、status別テンプレートをおすすめします。"
            recommended = normalized
        elif normalized == "REVIEW_REQUIRED" and comment_state_text in {"", "EMPTY", "WHITESPACE_ONLY", "MISSING_KEY"}:
            reason = "REVIEW_REQUIRED は空でも許容。ただしメモがある場合は任意テンプレートを使えます。"
            recommended = normalized
        else:
            reason = "コメント状態に大きな問題はありません。必要に応じてテンプレートを利用できます。"
            recommended = normalized
        return {
            "status": normalized,
            "comment_policy": policy["policy"],
            "comment_policy_label": policy["label"],
            "recommended_template": recommended,
            "suggestion_reason": reason,
        }

    def self_test(self) -> dict[str, object]:
        cases = [
            ("REVIEW_REQUIRED", "REVIEW_REQUIRED"),
            ("APPROVED", "APPROVED"),
            ("WATCH", "WATCH"),
            ("REJECTED", "REJECTED"),
            ("IMPLEMENTED", "IMPLEMENTED"),
            ("REVERTED", "REVERTED"),
            ("unknown", "UNKNOWN"),
            ("", "UNKNOWN"),
            (None, "UNKNOWN"),
        ]
        results = []
        for status, expected in cases:
            normalized = self.normalize_status(status)
            template = self.template_for(status)
            policy = self.comment_policy(status)
            passed = normalized == expected and bool(template.strip()) and bool(policy.get("policy"))
            results.append(
                {
                    "input": status,
                    "expected": expected,
                    "actual": normalized,
                    "template_present": bool(template.strip()),
                    "policy": policy.get("policy"),
                    "passed": passed,
                }
            )
        return {
            "passed": all(row["passed"] for row in results),
            "case_count": len(results),
            "results": results,
        }

    def write_guideline(self, path: Path | str = DEFAULT_GUIDELINE_PATH) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.guideline_markdown(), encoding="utf-8")
        return path

    def guideline_markdown(self) -> str:
        lines = [
            "# Human Review Guideline",
            "",
            "## Purpose",
            "",
            "Human Review comment は、改善候補を後から見返したときに、人間がなぜそのstatusを選んだかを追跡するための運用メモです。",
            "このガイドは入力補助のみを目的とし、status、review_comment、Candidate、Shadow、Productionロジックを自動更新しません。",
            "",
            "## Status Guide",
            "",
            "| Status | Comment Policy | Purpose |",
            "|---|---|---|",
        ]
        for status in [
            "REVIEW_REQUIRED",
            "APPROVED",
            "WATCH",
            "REJECTED",
            "IMPLEMENTED",
            "REVERTED",
        ]:
            guide = self.comment_policy(status)
            lines.append(f"| {status} | {guide['policy']} | {guide['label']} |")

        lines.extend(["", "## Templates", ""])
        for status in [
            "REVIEW_REQUIRED",
            "APPROVED",
            "WATCH",
            "REJECTED",
            "IMPLEMENTED",
            "REVERTED",
        ]:
            lines.extend([f"### {status}", "", "```text", self.template_for(status), "```", ""])

        lines.extend(
            [
                "## Good Comments",
                "",
                "- APPROVED: `RaceShape由来のFNが複数レースで再現。Shadow検証でFN改善を確認する価値があるため承認。`",
                "- WATCH: `函館芝の開催後半条件に偏るため、次開催で同条件が追加されるまで監視。`",
                "- IMPLEMENTED: `ShadowでFP増加なし、BUY成功率維持を確認。Production影響は限定的。残課題は新潟外回りで別途確認。`",
                "",
                "## Bad Comments",
                "",
                "- `OK`",
                "- `あとで見る`",
                "- `なんとなく良さそう`",
                "- `却下`",
                "",
                "## Guardrails",
                "",
                "- テンプレートは入力補助のみ。",
                "- 自動入力、自動承認、自動status変更は行わない。",
                "- JSON DB、Feature Flag、Production判定には影響しない。",
            ]
        )
        return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Human Review templates and guideline.")
    parser.add_argument("--status", default="", help="Print a template for one status.")
    parser.add_argument("--write-guideline", action="store_true", help="Write reports/human_review_guideline.md.")
    parser.add_argument("--self-test", action="store_true", help="Run template generation self-tests.")
    args = parser.parse_args()

    generator = HumanReviewTemplateGenerator()
    if args.self_test:
        print(json.dumps(generator.self_test(), ensure_ascii=False, indent=2))
    if args.status:
        print(generator.template_for(args.status))
    if args.write_guideline:
        path = generator.write_guideline()
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
