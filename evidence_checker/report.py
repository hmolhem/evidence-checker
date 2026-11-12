"""Write results as CSV and as a short Markdown summary."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .match import Result


def write_csv(results: list[Result], path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["status", "number", "line", "section", "context", "evidence", "waiver_reason"])
        for r in results:
            ev = " || ".join(f"[{e.source}] {e.file} :: {e.where} = {e.value:.10g}" for e in r.matches)
            w.writerow([r.status, r.number.signed, r.number.line, r.number.section, r.number.context, ev, r.reason])


def summary(results: list[Result], report_name: str, files_read: int) -> str:
    c = Counter(r.status for r in results)
    total = len(results)
    lines = [
        f"# Evidence check — {report_name}",
        "",
        f"- Numbers checked: {total} (evidence files indexed: {files_read})",
        f"- MATCHED: {c['MATCHED']}",
        f"- WAIVED (documented derivation): {c['WAIVED']}",
        f"- UNMATCHED: {c['UNMATCHED']}",
        "",
    ]
    un = [r for r in results if r.status == "UNMATCHED"]
    if un:
        lines += ["## Unmatched numbers", "", "| Number | Line | Section | Context |", "|---|---|---|---|"]
        for r in un:
            ctx = r.number.context.replace("|", "\\|")
            lines.append(f"| {r.number.signed} | {r.number.line} | {r.number.section[:50]} | {ctx} |")
        lines.append("")
    lines += [
        "A MATCHED number has at least one evidence value that rounds to it at the printed precision.",
        "That shows the number exists in the evidence; it does not prove the text attributes it to the right quantity.",
    ]
    return "\n".join(lines)
