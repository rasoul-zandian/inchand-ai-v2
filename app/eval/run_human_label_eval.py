"""Run human-labeled workbook evaluation."""

from __future__ import annotations

import sys
from pathlib import Path

from app.eval.human_label_dataset import (
    evaluate_human_labels,
    load_human_label_workbook,
    write_reports,
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: python -m app.eval.run_human_label_eval <workbook.xlsx> [output_dir]",
            file=sys.stderr,
        )
        return 2

    workbook = Path(args[0])
    output_dir = Path(args[1]) if len(args) > 1 else Path("reports")

    evaluable, skipped = load_human_label_workbook(workbook)
    report = evaluate_human_labels(evaluable)
    write_reports(output_dir, evaluable, skipped, report)

    print(f"total_cases: {len(evaluable) + len(skipped)}")
    print(f"evaluated_cases: {report.evaluated_cases}")
    print(f"intent_accuracy: {report.intent_accuracy:.2%}")
    print(f"pass_count: {report.pass_count}")
    print(f"fail_count: {report.fail_count}")
    print(f"reports written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
