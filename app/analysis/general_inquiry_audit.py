"""Root-cause audit for shadow-mode general_inquiry classifications."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CATEGORIES = (
    "CONTEXT_FAILURE",
    "RULE_GAP",
    "TAXONOMY_GAP",
    "TOOL_GAP",
    "CORRECT_GENERAL_INQUIRY",
)

_ACK_PHRASES = (
    "بله",
    "چشم",
    "ممنون",
    "سپاس",
    "مرسی",
    "آهان",
)

_RULE_PATTERNS: list[tuple[str, str, str]] = [
    ("delivery_confirmation_request", r"(تحویل|رسیده|تایید کن|بارکد خرید|بدست .* رسید)", "delivery confirmation signal"),
    ("product_edit_request", r"(ویرایش|اصلاح|عوض کن|تغییر دهید|نام محصول)", "product edit keywords"),
    ("product_approval_request", r"(تایید میفرمایید|تایید کنید|برسی میکنید|تایید محصول)", "product approval keywords"),
    ("order_status_inquiry", r"(INC[\s-]*\d+|وضعیت سفارش|کجاست|کد مرسوله)", "order status keywords"),
    ("order_cancellation", r"(لغو|کنسل|cancel)", "cancellation keywords"),
    ("shop_address_update", r"(آدرس|انبار|warehouse|address)", "shop address keywords"),
    ("bank_account_change", r"(شبا|iban|حساب|بانک)", "bank account keywords"),
    ("card_change_request", r"(کارت|card)", "card change keywords"),
    ("settlement_inquiry", r"(تسویه|واریز|settlement)", "settlement keywords"),
    ("contract_approval", r"(قرارداد|قرار داد)", "contract keywords"),
    ("account_access_issue", r"(رمز|ورود|لاگین|پنل.*غیر.?فعال|غیرفعال.*پنل|ارور.*پنل)", "account/panel access keywords"),
    ("shipping_inquiry", r"(ارسال|پست|tracking|رهگیری|مرسوله)", "shipping keywords"),
    ("order_registration_issue", r"(ثبت نمی|ثبت نمى|سفارش ثبت)", "order registration keywords"),
    ("complaint_order_followup", r"(شکایت|تماس گرفته|برگشت|مرجوع)", "complaint follow-up keywords"),
    ("technical_bug_report", r"(ارور|خطا|باگ|error)", "technical issue keywords"),
]

_TAXONOMY_GAP_PATTERNS: list[tuple[str, str]] = [
    (r"(برند|brand|انتخاب برند)", "brand selection request not in taxonomy"),
    (r"(باز کنید|باز کن|open shop)", "named shop opening request not in taxonomy"),
    (r"(ویژگی جدید|قابلیت جدید|feature)", "new feature request not in taxonomy"),
]

_TOOL_GAP_PATTERNS: list[tuple[str, str]] = [
    (r"(فروشگاه.*فعال|فعال شد|فروشگاه.*باز|بازه\?|وضعیت فروشگاه)", "shop status needs lookup tool"),
]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _has_context(context: list | None) -> bool:
    return bool(context)


def _is_short_ack(text: str) -> bool:
    normalized = _normalize_text(text)
    if len(normalized) <= 20:
        return True
    if normalized in _ACK_PHRASES:
        return True
    if len(normalized) <= 30 and any(
        normalized == phrase or normalized.startswith(f"{phrase} ")
        for phrase in _ACK_PHRASES
    ):
        return True
    return False


def _is_mostly_identifier(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        return True
    digits = sum(char.isdigit() for char in stripped)
    return digits / len(stripped) >= 0.7


def _match_patterns(patterns: list[tuple[str, str]], text: str) -> tuple[str, str] | None:
    for pattern, reason in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return reason, pattern
    return None


def _context_text(context: list | None) -> str:
    if not context:
        return ""
    return " ".join(str(item.get("content", "")) for item in context)


def classify_root_cause(
    *,
    seller_message: str,
    conversation_context: list | None,
    entities: dict,
    room_type: str | None,
) -> tuple[str, str]:
    text = seller_message or ""
    normalized = _normalize_text(text)
    context = conversation_context or []
    combined = f"{_context_text(context)} {text}".strip()

    if _has_context(context):
        if not text:
            return "CONTEXT_FAILURE", "seller message missing but thread context exists"
        if _is_short_ack(text) or _is_mostly_identifier(text):
            return "CONTEXT_FAILURE", "short or identifier-only reply depends on prior thread context"
        if len(normalized) <= 40 and _has_context(context):
            return "CONTEXT_FAILURE", "brief follow-up likely requires conversation context"

    for intent, pattern, reason in _RULE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            if intent == "complaint_order_followup" and room_type != "complaint":
                continue
            return "RULE_GAP", f"{reason}; likely {intent}"

    if entities.get("order_id") or entities.get("tracking_code"):
        return "RULE_GAP", "extracted order/tracking entities suggest a specific operational intent"

    tax_match = _match_patterns(_TAXONOMY_GAP_PATTERNS, text)
    if tax_match:
        return "TAXONOMY_GAP", tax_match[0]

    tool_match = _match_patterns(_TOOL_GAP_PATTERNS, text)
    if tool_match:
        return "TOOL_GAP", tool_match[0]

    if room_type == "complaint" and _has_context(context):
        return "CONTEXT_FAILURE", "complaint-room follow-up without standalone intent markers"

    if not text:
        return "CORRECT_GENERAL_INQUIRY", "insufficient message text; general inquiry may be acceptable fallback"

    if len(normalized) > 120 and not re.search(
        r"(سفارش|محصول|فروشگاه|شبا|لغو|تایید|ویرایش|آدرس|قرارداد|تسویه)",
        combined,
        re.IGNORECASE,
    ):
        return "CORRECT_GENERAL_INQUIRY", "long descriptive message without clear operational intent marker"

    return "CORRECT_GENERAL_INQUIRY", "no stronger specialized intent signal detected"


def audit_general_inquiry(
    results_path: Path,
    private_path: Path,
) -> dict:
    results = _load_jsonl(results_path)
    private_rows = _load_jsonl(private_path)
    private_by_room = {str(row.get("room_id")): row for row in private_rows}

    cases: list[dict] = []
    for row in results:
        if row.get("primary_intent") != "general_inquiry":
            continue

        room_id = str(row.get("room_id", ""))
        private = private_by_room.get(room_id, {})
        seller_message = private.get("seller_message", "")
        conversation_context = private.get("conversation_context")

        category, reason = classify_root_cause(
            seller_message=seller_message,
            conversation_context=conversation_context,
            entities=row.get("entities") or {},
            room_type=row.get("room_type"),
        )

        cases.append(
            {
                "room_id": room_id,
                "shop_id": str(row.get("shop_id", private.get("shop_id", ""))),
                "seller_message": seller_message,
                "predicted_intent": row.get("primary_intent"),
                "root_cause_category": category,
                "short_reason": reason,
            }
        )

    category_counts = Counter(case["root_cause_category"] for case in cases)
    total = len(cases)
    percentages = {
        category: (category_counts.get(category, 0) / total if total else 0.0)
        for category in CATEGORIES
    }

    examples: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        bucket = examples[case["root_cause_category"]]
        if len(bucket) < 5:
            bucket.append(
                {
                    "room_id": case["room_id"],
                    "seller_message_preview": (case["seller_message"] or "")[:120],
                    "short_reason": case["short_reason"],
                }
            )

    priority_order = sorted(
        CATEGORIES,
        key=lambda category: category_counts.get(category, 0),
        reverse=True,
    )

    return {
        "total_general_inquiry": total,
        "count_per_category": dict(category_counts),
        "percentage_per_category": percentages,
        "top_examples_per_category": dict(examples),
        "report_answers": {
            "context_failure_pct": percentages["CONTEXT_FAILURE"],
            "rule_gap_pct": percentages["RULE_GAP"],
            "taxonomy_gap_pct": percentages["TAXONOMY_GAP"],
            "tool_gap_pct": percentages["TOOL_GAP"],
            "correct_general_inquiry_pct": percentages["CORRECT_GENERAL_INQUIRY"],
        },
        "fix_priority": priority_order,
        "recommended_first_fix": _recommended_first_fix(category_counts, percentages),
        "cases": cases,
        "inputs": {
            "results_path": str(results_path),
            "private_path": str(private_path),
            "private_inputs_used": private_path.exists(),
        },
    }


def _recommended_first_fix(counts: Counter, percentages: dict[str, float]) -> str:
    if counts.get("RULE_GAP", 0) >= counts.get("CONTEXT_FAILURE", 0) and counts.get("RULE_GAP", 0) > 0:
        return "Expand classifier rules for obvious single-message intents (RULE_GAP is largest)."
    if counts.get("CONTEXT_FAILURE", 0) > 0:
        return "Improve context-aware classification for short follow-up replies (CONTEXT_FAILURE is largest)."
    if counts.get("TAXONOMY_GAP", 0) > 0:
        return "Review taxonomy for missing merchant request types before adding more rules."
    if counts.get("TOOL_GAP", 0) > 0:
        return "Add operational lookup capability for shop-status style questions."
    return "General inquiry rate appears mostly appropriate; monitor before changing classifier."


def build_markdown_report(audit: dict) -> str:
    answers = audit["report_answers"]
    lines = [
        "# General Inquiry Root Cause Audit",
        "",
        f"Total `general_inquiry` cases: {audit['total_general_inquiry']}",
        f"Private inputs used: {audit['inputs']['private_inputs_used']}",
        "",
        "## Category counts",
        "",
    ]
    for category in CATEGORIES:
        count = audit["count_per_category"].get(category, 0)
        pct = audit["percentage_per_category"].get(category, 0.0)
        lines.append(f"- {category}: {count} ({pct:.1%})")

    lines.extend(
        [
            "",
            "## Report questions",
            "",
            f"1. CONTEXT_FAILURE: {answers['context_failure_pct']:.1%}",
            f"2. RULE_GAP: {answers['rule_gap_pct']:.1%}",
            f"3. TAXONOMY_GAP: {answers['taxonomy_gap_pct']:.1%}",
            f"4. TOOL_GAP: {answers['tool_gap_pct']:.1%}",
            f"5. Correct general inquiry: {answers['correct_general_inquiry_pct']:.1%}",
            "",
            "## Recommended first fix",
            "",
            audit["recommended_first_fix"],
            "",
            "## Top examples per category",
            "",
        ]
    )

    for category in CATEGORIES:
        lines.append(f"### {category}")
        examples = audit["top_examples_per_category"].get(category, [])
        if not examples:
            lines.append("- none")
        else:
            for example in examples:
                preview = example["seller_message_preview"] or "<no seller_message>"
                lines.append(
                    f"- room {example['room_id']}: {preview} — {example['short_reason']}"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_audit(
    results_path: Path = Path("reports/shadow_mode_results.jsonl"),
    private_path: Path = Path("reports/shadow_mode_inputs_private.jsonl"),
    output_dir: Path = Path("reports"),
) -> dict:
    audit = audit_general_inquiry(results_path, private_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "general_inquiry_audit.json"
    md_path = output_dir / "general_inquiry_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown_report(audit), encoding="utf-8")
    return audit


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    results_path = Path(args[0]) if args else Path("reports/shadow_mode_results.jsonl")
    private_path = Path(args[1]) if len(args) > 1 else Path("reports/shadow_mode_inputs_private.jsonl")
    output_dir = Path(args[2]) if len(args) > 2 else Path("reports")

    if not results_path.is_file():
        print(f"Results file not found: {results_path}", file=sys.stderr)
        return 1

    audit = run_audit(results_path, private_path, output_dir)
    print(f"total_general_inquiry: {audit['total_general_inquiry']}")
    print(f"recommended_first_fix: {audit['recommended_first_fix']}")
    print(f"reports written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
