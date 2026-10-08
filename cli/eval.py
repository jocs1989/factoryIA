"""`make eval`: falla (exit 1) si aparece un falso OK, un rechazo de mas o
un bypass del gate."""

from __future__ import annotations

import sys

from observability.evaluation import evaluate


def main() -> int:
    """Corre la evaluacion adversarial; sale con error si hay un falso OK."""
    report = evaluate()
    print(report.format())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
