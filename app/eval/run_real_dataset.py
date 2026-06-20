"""Run evaluation on a JSONL real ticket dataset."""

from __future__ import annotations

import sys

from app.eval.real_dataset import DatasetEvalReport, evaluate_dataset, load_jsonl


def print_report(report: DatasetEvalReport) -> None:
    print(f"total_cases: {report.total_cases}")
    print(f"intent_pass_count: {report.intent_pass_count}")
    print(f"reply_pass_count: {report.reply_pass_count}")
    print(f"failed_cases: {len(report.failed_cases)}")
    print("")

    for item in report.results:
        status = "PASS" if item.passed else "FAIL"
        print(f"[{status}] {item.case_id}")
        print(f"  predicted_intent: {item.predicted_intent}")
        print(f"  final_reply: {item.final_reply}")
        print(f"  issues: {item.issues}")
        print("")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python -m app.eval.run_real_dataset <path-to-jsonl>", file=sys.stderr)
        return 2

    cases = load_jsonl(args[0])
    report = evaluate_dataset(cases)
    print_report(report)
    return 0 if not report.failed_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
