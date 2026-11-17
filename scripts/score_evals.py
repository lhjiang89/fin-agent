"""Score frozen Fin-Agent evaluation cases against deterministic outputs.

Usage:
  python -m scripts.score_evals --kind routing --predictions evals/routing_predictions.jsonl
  python -m scripts.score_evals --kind research --predictions evals/research_predictions.jsonl

Prediction files are JSONL keyed by case_id. For research, each row has
action, as_of, citations, missing_information, and optional numeric fields.
For routing, each row has route. This script does not call an LLM.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    "research": ROOT / "evals/research_cases.jsonl",
    "routing": ROOT / "evals/routing_cases.jsonl",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
    return rows


def prediction_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        case_id = row.get("case_id")
        if not case_id or case_id in result:
            raise ValueError(f"missing or duplicate prediction case_id: {case_id!r}")
        result[case_id] = row
    return result


def score_routing(cases: list[dict[str, Any]], predictions: Any) -> dict[str, Any]:
    predictions = prediction_map(list(predictions)) if not isinstance(predictions, dict) else predictions
    labels = sorted({case["expected_route"] for case in cases})
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    errors = []
    scored = 0
    for case in cases:
        prediction = predictions.get(case["id"])
        if prediction is None:
            errors.append({"case_id": case["id"], "error": "missing_prediction"})
            continue
        predicted = prediction.get("route")
        actual = case["expected_route"]
        if predicted not in labels:
            errors.append({"case_id": case["id"], "error": "unknown_route", "route": predicted})
            continue
        scored += 1
        matrix[actual][predicted] += 1
        if predicted != actual:
            errors.append({"case_id": case["id"], "error": "misroute", "expected": actual, "actual": predicted})
    correct = sum(matrix[label][label] for label in labels)
    return {
        "cases": len(cases), "scored": scored, "accuracy": correct / scored if scored else 0.0,
        "confusion_matrix": matrix, "errors": errors,
    }


def numeric_matches(expected: dict[str, float], prediction: dict[str, Any], tolerance: float) -> bool:
    for key, expected_value in expected.items():
        actual = prediction.get(key)
        if not isinstance(actual, (int, float)) or not math.isclose(float(actual), float(expected_value), abs_tol=tolerance, rel_tol=0):
            return False
    return True


def score_research(cases: list[dict[str, Any]], predictions: Any) -> dict[str, Any]:
    predictions = prediction_map(list(predictions)) if not isinstance(predictions, dict) else predictions
    dimensions = Counter()
    errors = []
    scored = 0
    passed = 0
    for case in cases:
        prediction = predictions.get(case["id"])
        if prediction is None:
            errors.append({"case_id": case["id"], "error": "missing_prediction"})
            continue
        scored += 1
        action_ok = prediction.get("action") == case["expected_action"]
        as_of_ok = prediction.get("as_of") == case["as_of"]
        actual_citations = set(prediction.get("citations", []))
        citation_ok = actual_citations.issubset(set(case["allowed_citations"])) and set(case["required_citations"]).issubset(actual_citations)
        missing = prediction.get("missing_information", [])
        missing_ok = isinstance(missing, list) and set(case.get("expected_missing_information", [])).issubset(set(missing))
        numeric_ok = True
        if case.get("expected_change_percent") is not None:
            numeric_ok = numeric_matches({"change_percent": case["expected_change_percent"]}, prediction, case["tolerance_percent_points"])
        if case.get("expected_values"):
            numeric_ok = numeric_ok and numeric_matches(case["expected_values"], prediction, case.get("tolerance_absolute", 0.01))
        if case.get("expected_change_percent") is None and "change_percent" in prediction:
            numeric_ok = numeric_ok and prediction.get("change_percent") is None
        checks = {"action": action_ok, "numeric": numeric_ok, "citation": citation_ok, "as_of": as_of_ok, "missing_information": missing_ok}
        for name, ok in checks.items():
            dimensions[name] += int(ok)
        if all(checks.values()):
            passed += 1
        else:
            errors.append({"case_id": case["id"], "checks": checks})
    return {
        "cases": len(cases), "scored": scored, "answer_pass_rate": passed / scored if scored else 0.0,
        "dimension_pass_rates": {key: value / scored if scored else 0.0 for key, value in dimensions.items()},
        "passed": passed, "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=DATASETS, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    args = parser.parse_args()
    cases = load_jsonl(DATASETS[args.kind])
    if args.split != "all":
        cases = [case for case in cases if case["split"] == args.split]
    predictions = prediction_map(load_jsonl(args.predictions))
    report = score_routing(cases, predictions) if args.kind == "routing" else score_research(cases, predictions)
    report["kind"] = args.kind
    report["split"] = args.split
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
