"""Command line: evidence-check --config evidence.toml REPORT [REPORT ...]"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .extract import extract_numbers, load_report_text
from .match import check, load_waivers
from .report import summary, write_csv
from .sources import SourceSpec, build_index


def load_config(path: Path) -> dict:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    specs = []
    for s in cfg.get("sources", []):
        s = dict(s)
        s["path"] = str((base / s["path"]).resolve())
        specs.append(SourceSpec(**s))
    waivers = cfg.get("waivers", {}).get("file")
    return {
        "specs": specs,
        "min_decimals": int(cfg.get("report", {}).get("min_decimals", 3)),
        "waivers": str((base / waivers).resolve()) if waivers else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evidence-check",
                                 description="Check that numbers in a report exist in the evidence files.")
    ap.add_argument("reports", nargs="+", type=Path, help="report files (.md, .txt, .html)")
    ap.add_argument("--config", "-c", type=Path, required=True, help="TOML file listing evidence sources")
    ap.add_argument("--out", "-o", type=Path, default=Path("evidence_check_out"), help="output directory")
    ap.add_argument("--min-decimals", type=int, help="override report.min_decimals")
    ap.add_argument("--strict", action="store_true", help="exit with code 1 if any number is UNMATCHED")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    min_dec = args.min_decimals or cfg["min_decimals"]
    index = build_index(cfg["specs"])
    waivers = load_waivers(cfg["waivers"])
    args.out.mkdir(parents=True, exist_ok=True)

    any_unmatched = False
    for rpt in args.reports:
        numbers = extract_numbers(load_report_text(rpt), min_decimals=min_dec)
        results = check(numbers, index, waivers)
        stem = rpt.stem
        write_csv(results, args.out / f"{stem}_evidence.csv")
        md = summary(results, rpt.name, len(index.files_read))
        (args.out / f"{stem}_evidence.md").write_text(md + "\n", encoding="utf-8")
        print(md)
        any_unmatched |= any(r.status == "UNMATCHED" for r in results)
        print(f"Details: {args.out / (stem + '_evidence.csv')}\n")
    return 1 if (args.strict and any_unmatched) else 0


if __name__ == "__main__":
    sys.exit(main())
