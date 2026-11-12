"""Decide, for each reported number, whether some evidence value rounds to it."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .extract import ReportNumber
from .sources import Entry, Index

EPS = 1e-12


@dataclass
class Waiver:
    value: str              # number exactly as printed, without sign
    context_contains: str   # text that must appear in the number's context
    reason: str


@dataclass
class Result:
    number: ReportNumber
    status: str             # MATCHED, WAIVED or UNMATCHED
    matches: list[Entry]
    reason: str = ""


def rounding_interval(text: str) -> tuple[float, float]:
    """All true values that round to `text` at its printed precision (either tie rule)."""
    x = Decimal(text)
    half = Decimal(5) * Decimal(10) ** (x.as_tuple().exponent - 1)
    return float(x - half) - EPS, float(x + half) + EPS


def load_waivers(path: str | Path | None) -> list[Waiver]:
    if not path:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [Waiver(r["value"].strip(), r["context_contains"].strip(), r["reason"].strip())
                for r in csv.DictReader(f) if r.get("value")]


def check(numbers: list[ReportNumber], index: Index, waivers: list[Waiver] | None = None,
          max_matches: int = 3) -> list[Result]:
    waivers = waivers or []
    results = []
    for n in numbers:
        lo, hi = rounding_interval(n.text)
        hits = index.between(lo, hi, limit=max_matches)
        if hits:
            results.append(Result(n, "MATCHED", hits))
            continue
        w = next((w for w in waivers if w.value == n.text and w.context_contains in n.context), None)
        if w:
            results.append(Result(n, "WAIVED", [], w.reason))
        else:
            results.append(Result(n, "UNMATCHED", []))
    return results
