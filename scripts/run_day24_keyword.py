"""Run the Day 24 keyword baseline on Day 22 evidence questions.

Usage:
  python -m scripts.run_day24_keyword
  python -m scripts.run_day24_keyword --as-of 2026-11-19 --output evals/runs/day24_keyword_baseline.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from fin_agent.keyword_retrieval import (
    QUESTIONS_PATH,
    ROOT,
    infer_symbol,
    load_manifest_documents,
    search_filings_keyword,
)


DEFAULT_AS_OF = "2026-11-19"
DEFAULT_ALLOWED = ("HK.00700", "HK.01698")
DEFAULT_OUTPUT = ROOT / "evals/runs/day24_keyword_baseline.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 24 keyword baseline over filing chunks.")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument(
        "--allowed-symbols",
        nargs="*",
        default=list(DEFAULT_ALLOWED),
        help="Permission filter: symbols this principal may read.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    args = parser.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
    documents = load_manifest_documents()
    runs = []
    for item in questions:
        symbol = infer_symbol(item["question"], item.get("document_id"), documents)
        result = search_filings_keyword(
            item["question"],
            as_of=args.as_of,
            symbol=symbol,
            allowed_symbols=args.allowed_symbols,
            document_id=None,
        )
        runs.append(
            {
                "question_id": item["id"],
                "gold_document_id": item["document_id"],
                "gold_evidence_pages": item["evidence_pages"],
                "symbol_resolved": symbol,
                **result,
            }
        )

    payload = {
        "run_id": "day24_keyword_baseline",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": args.as_of,
        "allowed_symbols": args.allowed_symbols,
        "note": "Symbol and as-of filters run before keyword ranking. document_id is not passed to mimic routing uncertainty within one issuer.",
        "questions": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "question_count": len(runs)}, ensure_ascii=False))
    for run in runs:
        top = ", ".join(f"{row['rank']}:{row['chunk_id'].rsplit(':', 1)[-1]}@{row['score']}" for row in run["results"])
        print(f"{run['question_id']} candidates={run['candidate_chunks']} top5={top}")


if __name__ == "__main__":
    main()