"""Human-labeled Excel dataset evaluation."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.intent.taxonomy import IntentId
from app.models.messages import ConversationMessage
from app.pipeline.run_pipeline import run_pipeline

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_VALID_INTENTS = {intent.value for intent in IntentId}
_CONTEXT_PATTERN = re.compile(
    r"\[(\d+)\]\s*(admin|seller|assistant|user|system)\s*:\s*"
    r"(.*?)(?=\[\d+\]\s*(?:admin|seller|assistant|user|system)\s*:|$)",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class HumanLabelCase:
    case_id: str
    seller_message: str
    expected_intent: str
    conversation_context: list[ConversationMessage] = field(default_factory=list)
    label_notes: str = ""


@dataclass(frozen=True)
class HumanLabelCaseResult:
    case_id: str
    expected_intent: str
    predicted_intent: str
    seller_message: str
    passed: bool
    short_reason: str
    final_reply: str


@dataclass(frozen=True)
class HumanLabelEvalReport:
    total_cases: int
    evaluated_cases: int
    intent_accuracy: float
    pass_count: int
    fail_count: int
    expected_distribution: dict[str, int]
    predicted_distribution: dict[str, int]
    top_confusion_pairs: list[dict[str, str | int]]
    failures: list[HumanLabelCaseResult]
    results: list[HumanLabelCaseResult]


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.get("t")
    value = cell.find("m:v", _NS)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return shared[int(value.text)]
    return value.text


def _read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall(".//m:si", _NS):
                parts = [part.text or "" for part in item.findall(".//m:t", _NS)]
                shared.append("".join(parts))

        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        table_rows: list[list[str]] = []
        for row in sheet.findall(".//m:sheetData/m:row", _NS):
            values = [_cell_value(cell, shared) for cell in row.findall("m:c", _NS)]
            table_rows.append(values)

    if not table_rows:
        return []

    headers = [header.strip() for header in table_rows[0]]
    records: list[dict[str, str]] = []
    for raw in table_rows[1:]:
        padded = raw + [""] * (len(headers) - len(raw))
        record = {headers[index]: padded[index] for index in range(len(headers))}
        if record.get("case_id", "").strip():
            records.append(record)
    return records


def parse_conversation_context_readable(text: str) -> list[ConversationMessage]:
    if not text or not text.strip():
        return []

    cleaned = text.replace("_x000D_", "\n").strip()
    messages: list[ConversationMessage] = []
    for match in _CONTEXT_PATTERN.finditer(cleaned):
        role_raw = match.group(2).lower()
        content = match.group(3).strip()
        if not content:
            continue
        if role_raw == "admin":
            role = "assistant"
        elif role_raw == "seller":
            role = "user"
        elif role_raw in {"assistant", "user", "system"}:
            role = role_raw
        else:
            role = "user"
        messages.append(ConversationMessage(role=role, content=content))
    return messages


def load_human_label_workbook(path: str | Path) -> tuple[list[HumanLabelCase], list[HumanLabelCase]]:
    records = _read_xlsx_rows(Path(path))
    evaluable: list[HumanLabelCase] = []
    skipped: list[HumanLabelCase] = []

    for record in records:
        case_id = record.get("case_id", "").strip()
        seller_message = record.get("seller_message", "").strip()
        expected_intent = record.get("expected_intent", "").strip()
        if not case_id or not seller_message or not expected_intent:
            continue

        case = HumanLabelCase(
            case_id=case_id,
            seller_message=seller_message,
            expected_intent=expected_intent,
            conversation_context=parse_conversation_context_readable(
                record.get("conversation_context_readable", "")
            ),
            label_notes=record.get("label_notes", "").strip(),
        )
        if expected_intent in _VALID_INTENTS:
            evaluable.append(case)
        else:
            skipped.append(case)

    return evaluable, skipped


def _short_reason(expected: str, predicted: str) -> str:
    if expected == predicted:
        return "match"
    return f"expected {expected}, got {predicted}"


def evaluate_human_labels(cases: list[HumanLabelCase]) -> HumanLabelEvalReport:
    results: list[HumanLabelCaseResult] = []
    for case in cases:
        pipeline = run_pipeline(
            case.seller_message,
            conversation_context=case.conversation_context or None,
        )
        predicted = pipeline.intent_result.primary_intent.value
        passed = predicted == case.expected_intent
        results.append(
            HumanLabelCaseResult(
                case_id=case.case_id,
                expected_intent=case.expected_intent,
                predicted_intent=predicted,
                seller_message=case.seller_message,
                passed=passed,
                short_reason=_short_reason(case.expected_intent, predicted),
                final_reply=pipeline.final_reply.text,
            )
        )

    pass_count = sum(1 for item in results if item.passed)
    fail_count = len(results) - pass_count
    evaluated_cases = len(results)
    intent_accuracy = pass_count / evaluated_cases if evaluated_cases else 0.0

    expected_distribution = dict(Counter(item.expected_intent for item in results))
    predicted_distribution = dict(Counter(item.predicted_intent for item in results))
    confusion_counter: Counter[tuple[str, str]] = Counter()
    failures: list[HumanLabelCaseResult] = []
    for item in results:
        if not item.passed:
            failures.append(item)
            confusion_counter[(item.expected_intent, item.predicted_intent)] += 1

    top_confusion_pairs = [
        {
            "expected_intent": expected,
            "predicted_intent": predicted,
            "count": count,
        }
        for (expected, predicted), count in confusion_counter.most_common(10)
    ]

    return HumanLabelEvalReport(
        total_cases=evaluated_cases,
        evaluated_cases=evaluated_cases,
        intent_accuracy=intent_accuracy,
        pass_count=pass_count,
        fail_count=fail_count,
        expected_distribution=expected_distribution,
        predicted_distribution=predicted_distribution,
        top_confusion_pairs=top_confusion_pairs,
        failures=failures,
        results=results,
    )


def build_full_report(
    evaluable: list[HumanLabelCase],
    skipped: list[HumanLabelCase],
    report: HumanLabelEvalReport,
) -> dict:
    return {
        "total_cases": len(evaluable) + len(skipped),
        "evaluated_cases": report.evaluated_cases,
        "skipped_cases": len(skipped),
        "skipped_expected_intents": dict(Counter(item.expected_intent for item in skipped)),
        "intent_accuracy": report.intent_accuracy,
        "pass_count": report.pass_count,
        "fail_count": report.fail_count,
        "expected_distribution": report.expected_distribution,
        "predicted_distribution": report.predicted_distribution,
        "top_confusion_pairs": report.top_confusion_pairs,
        "results": [
            {
                "case_id": item.case_id,
                "expected_intent": item.expected_intent,
                "predicted_intent": item.predicted_intent,
                "passed": item.passed,
                "short_reason": item.short_reason,
                "final_reply": item.final_reply,
                "seller_message": item.seller_message,
            }
            for item in report.results
        ],
    }


def write_reports(
    output_dir: str | Path,
    evaluable: list[HumanLabelCase],
    skipped: list[HumanLabelCase],
    report: HumanLabelEvalReport,
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    full = build_full_report(evaluable, skipped, report)
    (out / "human_label_eval.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    failures = [
        {
            "case_id": item.case_id,
            "expected_intent": item.expected_intent,
            "predicted_intent": item.predicted_intent,
            "seller_message": item.seller_message,
            "short_reason": item.short_reason,
            "final_reply": item.final_reply,
        }
        for item in report.failures
    ]
    (out / "human_label_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Human Label Evaluation Summary",
        "",
        f"- total cases: {full['total_cases']}",
        f"- evaluated cases: {full['evaluated_cases']}",
        f"- skipped cases: {full['skipped_cases']}",
        f"- intent accuracy: {report.intent_accuracy:.2%}",
        "",
        "## Expected intent distribution",
        "",
    ]
    for intent, count in sorted(report.expected_distribution.items()):
        lines.append(f"- {intent}: {count}")
    lines.extend(["", "## Predicted intent distribution", ""])
    for intent, count in sorted(report.predicted_distribution.items()):
        lines.append(f"- {intent}: {count}")
    lines.extend(["", "## Top confusion pairs", ""])
    if report.top_confusion_pairs:
        for pair in report.top_confusion_pairs:
            lines.append(
                f"- {pair['expected_intent']} -> {pair['predicted_intent']}: {pair['count']}"
            )
    else:
        lines.append("- none")
    lines.append("")

    (out / "human_label_summary.md").write_text("\n".join(lines), encoding="utf-8")
