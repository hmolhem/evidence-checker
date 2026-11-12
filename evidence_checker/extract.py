"""Find reported decimal numbers in a report and remember where they appear."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

# A decimal number that is not part of a longer token:
#   - not preceded by a letter, digit, underscore or dot  (skips hashes, "v1.0.0", "3.12.12")
#   - not followed by a digit, or by a dot plus digit       (skips the head of "3.12.12")
#   - not followed by a letter or underscore                (skips "1.5e3x", hex fragments)
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<sign>[+\-−±≈~]?)(?P<num>\d+\.\d+)(?![\d\w])(?!\.\d)"
)
HTML_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ReportNumber:
    text: str          # digits exactly as printed, without sign, e.g. "0.4566"
    decimals: int      # number of printed decimals
    signed: str        # with sign as printed, e.g. "-4.700"
    line: int          # 1-based line in the normalized text
    section: str       # nearest preceding heading
    context: str       # surrounding text, single line


def load_report_text(path: str | Path) -> str:
    """Return plain text with Markdown-style '#' headings.

    Supported: .md, .txt (as is) and .html/.htm (headings kept, tags removed).
    For Google Docs or Word files, export to Markdown or HTML first.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".html", ".htm"}:
        raw = HTML_HEADING_RE.sub(lambda m: "\n" + "#" * int(m.group(1)) + " " + TAG_RE.sub("", m.group(2)) + "\n", raw)
        raw = re.sub(r"</(p|tr|li|table|div)>", "\n", raw, flags=re.I)
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
        raw = html.unescape(TAG_RE.sub(" ", raw))
    return normalize(raw)


def normalize(text: str) -> str:
    """Unify minus signs and drop Markdown backslash escapes."""
    text = text.replace("−", "-").replace("‒", "-")
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>])", r"\1", text)


def extract_numbers(text: str, min_decimals: int = 3, context_chars: int = 90) -> list[ReportNumber]:
    out: list[ReportNumber] = []
    section = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
        for m in NUMBER_RE.finditer(line):
            num = m.group("num")
            decimals = len(num.split(".")[1])
            if decimals < min_decimals:
                continue
            a, b = max(0, m.start() - context_chars), min(len(line), m.end() + context_chars // 2)
            ctx = " ".join(line[a:b].split())
            sign = m.group("sign").replace("−", "-")
            out.append(ReportNumber(num, decimals, sign + num, lineno, section, ctx))
    return out
