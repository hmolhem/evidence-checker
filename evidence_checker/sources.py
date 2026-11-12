"""Build a searchable index of numbers from evidence files, keeping provenance for each value."""
from __future__ import annotations

import bisect
import fnmatch
import io
import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

TEXT_NUMBER_RE = re.compile(r"-?\d+\.\d+(?:[eE][-+]?\d+)?")
MAX_GROUP_LEVELS = 12  # a column with at most this many distinct values is used for grouped statistics


@dataclass(frozen=True)
class Entry:
    value: float        # absolute value
    source: str         # label of the source set
    file: str
    where: str          # row/column, JSON key path, or derived statistic


@dataclass
class SourceSpec:
    label: str
    type: str                     # "dir" or "git"
    path: str                     # directory, or git working copy
    ref: str | None = None        # git tag/commit (type="git")
    prefix: str = ""              # subdirectory inside dir/repo
    glob: str = "*"               # file name pattern, e.g. "*.csv"
    derived: bool = False         # also index column statistics
    percent: bool = False         # also index 100*x for |x| <= 1.5


@dataclass
class Index:
    entries: list[Entry] = field(default_factory=list)
    _keys: list[float] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)

    def finalize(self) -> "Index":
        self.entries = sorted((e for e in self.entries if math.isfinite(e.value)), key=lambda e: e.value)
        self._keys = [e.value for e in self.entries]
        return self

    def between(self, lo: float, hi: float, limit: int = 5) -> list[Entry]:
        i = bisect.bisect_left(self._keys, lo)
        out = []
        while i < len(self._keys) and self._keys[i] <= hi and len(out) < limit:
            out.append(self.entries[i])
            i += 1
        return out


# ----------------------------------------------------------------------------- file access

def _list_files(spec: SourceSpec) -> list[tuple[str, bytes]]:
    if spec.type == "dir":
        base = Path(spec.path) / spec.prefix
        files = sorted(p for p in base.rglob("*") if p.is_file() and fnmatch.fnmatch(p.name, spec.glob))
        return [(str(p.relative_to(spec.path)), p.read_bytes()) for p in files]
    if spec.type == "git":
        if not spec.ref:
            raise ValueError(f"source '{spec.label}': type 'git' needs 'ref'")
        git = ["git", "-C", spec.path]
        ls = subprocess.run(git + ["ls-tree", "-r", "--name-only", spec.ref, "--", spec.prefix or "."],
                            capture_output=True, text=True)
        if ls.returncode != 0:
            raise RuntimeError(
                f"source '{spec.label}': cannot read ref '{spec.ref}' in {spec.path}: {ls.stderr.strip()} "
                "(is the clone shallow? try: git fetch --unshallow --tags)")
        names = ls.stdout.split()
        if not names:
            raise RuntimeError(f"source '{spec.label}': no files under '{spec.prefix}' at ref '{spec.ref}'")
        out = []
        for n in names:
            if fnmatch.fnmatch(Path(n).name, spec.glob):
                blob = subprocess.run(git + ["show", f"{spec.ref}:{n}"], check=True, capture_output=True).stdout
                out.append((f"{n}@{spec.ref}", blob))
        return out
    raise ValueError(f"source '{spec.label}': unknown type '{spec.type}'")


# ----------------------------------------------------------------------------- parsers

def _add(index: Index, spec: SourceSpec, file: str, value, where: str) -> None:
    try:
        v = abs(float(value))
    except (TypeError, ValueError):
        return
    if not math.isfinite(v):
        return
    index.entries.append(Entry(v, spec.label, file, where))
    if spec.percent and v <= 1.5:
        index.entries.append(Entry(v * 100, spec.label, file, where + " ×100"))


def _index_csv(index: Index, spec: SourceSpec, file: str, data: bytes) -> None:
    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception:
        _index_text(index, spec, file, data)
        return
    num = df.select_dtypes("number")
    for col in num.columns:
        for row, v in num[col].items():
            _add(index, spec, file, v, f"row {row + 2}, {col}")
    if not spec.derived:
        return
    group_cols = [c for c in df.columns if df[c].nunique(dropna=True) <= MAX_GROUP_LEVELS]
    for col in num.columns:
        x = num[col].dropna()
        if x.empty:
            continue
        stats = {"mean": x.mean(), "median": x.median(), "std": x.std(), "min": x.min(), "max": x.max(),
                 "p5": np.percentile(x, 5), "p95": np.percentile(x, 95)}
        for name, v in stats.items():
            _add(index, spec, file, v, f"{name}({col})")
        for g in group_cols:
            if g == col:
                continue
            agg = df.groupby(g, dropna=True)[col].agg(["mean", "median", "std"])
            for level, row in agg.iterrows():
                for name, v in row.items():
                    _add(index, spec, file, v, f"{name}({col} | {g}={level})")


def _walk_json(index: Index, spec: SourceSpec, file: str, obj, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_json(index, spec, file, v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_json(index, spec, file, v, f"{path}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        _add(index, spec, file, obj, path)


def _index_text(index: Index, spec: SourceSpec, file: str, data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in TEXT_NUMBER_RE.finditer(line):
            _add(index, spec, file, m.group(), f"line {lineno}")


def build_index(specs: list[SourceSpec]) -> Index:
    index = Index()
    for spec in specs:
        for file, data in _list_files(spec):
            index.files_read.append(f"[{spec.label}] {file}")
            name = file.split("@")[0].lower()
            if name.endswith(".csv"):
                _index_csv(index, spec, file, data)
            elif name.endswith(".json"):
                try:
                    _walk_json(index, spec, file, json.loads(data))
                except json.JSONDecodeError:
                    _index_text(index, spec, file, data)
            else:
                _index_text(index, spec, file, data)
    return index.finalize()
