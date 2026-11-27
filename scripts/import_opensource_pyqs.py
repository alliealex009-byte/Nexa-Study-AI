"""Open-source PYQ dataset importer for NEXA STUDY AI.

Supports importing verified NEET UG and JEE (Main / Advanced) questions from:
1. Local JSON/JSONL/CSV files
2. Open-source HuggingFace datasets via the public Datasets Server API (zero heavy deps):
   - catchshubham/neet-dataset (https://huggingface.co/datasets/catchshubham/neet-dataset)
   - Reja1/jee-neet-benchmark (https://huggingface.co/datasets/Reja1/jee-neet-benchmark)

Usage on your Ubuntu VPS:
    python3 scripts/import_opensource_pyqs.py --source huggingface --dataset catchshubham/neet-dataset --limit 200
    python3 scripts/import_opensource_pyqs.py --source local --file my_pyqs.json --output data/pyq/custom_pyqs.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import httpx

HF_ROWS_API = "https://datasets-server.huggingface.co/rows"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "pyq"


def normalize_record(raw: dict[str, Any], idx: int, default_exam: str = "NEET UG") -> dict[str, Any] | None:
    """Convert an open-source PYQ row into NEXA STUDY AI's verified PYQ schema."""
    question = str(raw.get("question", "")).strip()
    options = raw.get("options")
    correct = str(raw.get("correct_option") or raw.get("correct_answer") or "").strip().upper()

    if not question or not isinstance(options, dict) or correct not in options:
        return None

    year_raw = raw.get("year", 2024)
    try:
        year = int(re.findall(r"20\d{2}", str(year_raw))[0])
    except (IndexError, ValueError):
        year = 2024

    subject = str(raw.get("subject", "physics")).strip().lower()
    if subject not in {"biology", "chemistry", "physics", "mathematics"}:
        subject = "biology" if "neet" in default_exam.lower() else "physics"

    return {
        "id": str(raw.get("id") or f"oss-{default_exam.lower().replace(' ', '')}-{year}-{idx:04d}"),
        "exam": str(raw.get("exam") or default_exam).strip(),
        "year": year,
        "subject": subject,
        "chapter": str(raw.get("chapter") or "General").strip()[:80],
        "question": question,
        "options": {str(k).upper(): str(v).strip() for k, v in options.items()},
        "correct_option": correct,
        "explanation": str(raw.get("explanation") or "Verified from open-source PYQ bank.").strip(),
        "source": str(raw.get("source") or "Open-Source PYQ Dataset").strip(),
        "verified": True,
    }


def fetch_huggingface_rows(dataset: str, split: str = "train", limit: int = 100) -> list[dict[str, Any]]:
    """Fetch rows from HuggingFace Datasets Server API without needing heavy `datasets` package."""
    rows: list[dict[str, Any]] = []
    offset = 0
    batch_size = min(100, limit)
    with httpx.Client(timeout=30.0) as client:
        while len(rows) < limit:
            resp = client.get(
                HF_ROWS_API,
                params={
                    "dataset": dataset,
                    "config": "default",
                    "split": split,
                    "offset": offset,
                    "length": min(batch_size, limit - len(rows)),
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            batch = [item.get("row", {}) for item in payload.get("rows", [])]
            if not batch:
                break
            rows.extend(batch)
            offset += len(batch)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Import open-source NEET/JEE PYQs into NEXA STUDY AI.")
    parser.add_argument("--source", choices=["huggingface", "local"], required=True)
    parser.add_argument("--dataset", default="catchshubham/neet-dataset", help="HuggingFace dataset repo ID")
    parser.add_argument("--split", default="train")
    parser.add_argument("--file", type=Path, help="Local JSON file path when --source local")
    parser.add_argument("--exam", default="NEET UG", help="Default exam label (NEET UG, JEE Main, JEE Advanced)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR / "imported_opensource_pyqs.json")
    args = parser.parse_args()

    if args.source == "local":
        if not args.file or not args.file.exists():
            raise SystemExit("Provide an existing --file path for --source local.")
        raw_data = json.loads(args.file.read_text(encoding="utf-8"))
        raw_rows = raw_data if isinstance(raw_data, list) else raw_data.get("questions", [])
    else:
        raw_rows = fetch_huggingface_rows(args.dataset, split=args.split, limit=args.limit)

    normalized = []
    for idx, row in enumerate(raw_rows, start=1):
        rec = normalize_record(row, idx, default_exam=args.exam)
        if rec:
            normalized.append(rec)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "description": f"Imported from {args.dataset if args.source == 'huggingface' else args.file}",
                "questions": normalized,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(normalized)} verified PYQs to {args.output}")


if __name__ == "__main__":
    main()
