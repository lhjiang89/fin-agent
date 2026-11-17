import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/score_evals.py"
SPEC = importlib.util.spec_from_file_location("score_evals", MODULE_PATH)
score_evals = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(score_evals)


def test_routing_confusion_matrix_and_misroute_count_change_for_bad_output():
    cases = score_evals.load_jsonl(score_evals.DATASETS["routing"])
    correct = {case["id"]: {"case_id": case["id"], "route": case["expected_route"]} for case in cases}
    perfect = score_evals.score_routing(cases, correct.values())
    assert perfect["accuracy"] == 1.0
    assert perfect["confusion_matrix"]["propose_simulated_buy"]["propose_simulated_buy"] == 7

    correct["D17-13"]["route"] = "query_current_price"
    broken = score_evals.score_routing(cases, correct.values())
    assert broken["accuracy"] == 29 / 30
    assert broken["confusion_matrix"]["propose_simulated_buy"]["query_current_price"] == 1
    assert len(broken["errors"]) == 1


def test_research_scores_each_dimension_and_detects_bad_citation_and_number():
    cases = score_evals.load_jsonl(score_evals.DATASETS["research"])
    predictions = {}
    for case in cases:
        row = {
            "case_id": case["id"], "action": case["expected_action"], "as_of": case["as_of"],
            "citations": case["required_citations"], "missing_information": case.get("expected_missing_information", []),
        }
        if case.get("expected_change_percent") is not None:
            row["change_percent"] = case["expected_change_percent"]
        if case.get("expected_values"):
            row.update(case["expected_values"])
        if case.get("expected_change_percent") is None:
            row["change_percent"] = None
        predictions[case["id"]] = row
    perfect = score_evals.score_research(cases, predictions.values())
    assert perfect["answer_pass_rate"] == 1.0
    assert all(rate == 1.0 for rate in perfect["dimension_pass_rates"].values())

    predictions["D16-01"]["citations"] = ["2026-11-12", "2026-11-16"]
    predictions["D16-04"]["2026-11-13"] = 999.0
    broken = score_evals.score_research(cases, predictions.values())
    assert broken["answer_pass_rate"] == 13 / 15
    assert broken["dimension_pass_rates"]["citation"] == 14 / 15
    assert broken["dimension_pass_rates"]["numeric"] == 14 / 15
