"""Write retrieval chunks for the Day 22 filing snapshot.

Usage:
  python -m scripts.chunk_filings
  python -m scripts.chunk_filings --output fixtures/filings_snapshot/chunks.jsonl

The script reads the PDFs already stored under fixtures/filings_snapshot/pdfs.
It does not call OpenD and does not download anything. It refuses to continue
if a PDF hash or page count differs from fixtures/filings_snapshot/manifest.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fin_agent.filing_chunks import DEFAULT_MANIFEST, ROOT, build_filing_chunks, summarize, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk the Day 22 filing PDFs.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "fixtures/filings_snapshot/chunks.jsonl",
    )
    args = parser.parse_args()
    chunks = build_filing_chunks(args.manifest, ROOT)
    write_jsonl(chunks, args.output)
    summary = summarize(chunks)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {len(chunks)} chunks to {args.output}")


if __name__ == "__main__":
    main()
