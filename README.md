# Evidence Checker

[![tests](https://github.com/hmolhem/evidence-checker/actions/workflows/tests.yml/badge.svg)](https://github.com/hmolhem/evidence-checker/actions/workflows/tests.yml)

Checks that every reported number in an engineering report can be found in its evidence files.

The tool reads a report (Markdown, plain text or HTML) and finds every decimal number with at least N printed decimals (default 3). For each number it searches an index of evidence values for one that **rounds to the printed value at the printed precision**. A typo, a stale value or a wrong rounding is reported as UNMATCHED, together with its line, section and surrounding text.

It was built for the *Sensor Validation & Metrology Engineering Report* ([analysis repository](https://github.com/hmolhem/hvac-sensor-validation-metrology)). On integrated report I-2 it checked 604 numbers and found one real rounding error (−4.700 printed where the table value is −4.699451).

## What it indexes

Evidence comes from **sources** listed in a TOML file. Each source is one of:

- a **directory** of files, or
- a **git tag/commit** of a repository. Files are read from that exact ref with `git show`, not from the working copy, so the check runs against the frozen release even if `main` has moved on.

| File type | Values indexed (each with provenance) |
|---|---|
| CSV | every numeric cell (`row, column`); with `derived = true` also mean, median, SD, min, max, 5th and 95th percentile of each column, and mean/median/SD grouped by every low-cardinality column |
| JSON | every number, with its key path |
| other text | every decimal number, with its line |

With `percent = true`, 100·x is also indexed for |x| ≤ 1.5.

## Matching rule

A printed number `x` with `d` decimals matches an evidence value `v` if |v| lies in `[|x| − ½·10⁻ᵈ, |x| + ½·10⁻ᵈ]`, which accepts both tie-breaking conventions. The sign is ignored, because reports often state a magnitude ("a gap of 0.81 %RH").

- `0.4566` matches `0.4566090`.
- `-4.700` does **not** match `-4.699451`.

A MATCHED number exists in the evidence. That does **not** prove the text attributes it to the right quantity; a human or chapter-level review still has to judge that.

## Waivers

Some report values are legitimately derived and appear in no file (a ratio, a recomputation from raw data, a filtered mean). List them in `waivers.csv` with the exact printed value, a phrase from the surrounding text, and the derivation. A waiver applies only where both the value and the phrase match, so the same number elsewhere is still checked.

```csv
value,context_contains,reason
0.0873,rectangular term,"Ch14: 0.1512/sqrt(3) = 0.08730"
```

## Use

```bash
pip install -e .              # Python 3.11+, pandas, numpy
evidence-check -c examples/hvac/evidence.toml -o out/  report.md  [more reports...]
evidence-check ... --strict   # exit code 1 if anything is UNMATCHED (for CI)
```

For each report the tool writes two files to the output directory:

- `<report>_evidence.csv`: one row per number, with status, line, section, context, matching evidence (source, file, row/column or statistic, value) and any waiver reason.
- `<report>_evidence.md`: a summary listing the unmatched numbers.

For Google Docs or Word files, export to Markdown or HTML first.

## Example: this report

`examples/hvac/evidence.toml` indexes four git sources from `hmolhem/hvac-sensor-validation-metrology`:

- `reports/tables` at `v1.0.0`, with derived statistics;
- `config/*.json` at `v1.0.0`;
- the pre-audit tables at `472d4de`;
- the SUP-001 outputs at `sup001-v0.1.0`.

It also indexes the archived Chapter 8/11 report tables. Place the analysis repository next to this one, or edit `path`. The clone must have full history and tags (`git fetch --unshallow --tags`).

Result on I-2:

| Version | Numbers | Matched | Waived | Unmatched |
|---|---|---|---|---|
| as exported | 604 | 591 | 12 | 1 (`-4.700`, Ch. 11 §11.6) |
| after the fix | 604 | 592 | 12 | 0 |

The summaries are in `examples/hvac/results/`. The per-number CSVs are produced locally by running the command above.

## Tests

```bash
pip install -e .[test] && pytest -q
```

## Limits

- Numbers with fewer printed decimals than `min_decimals` (for example 0.83 or 60 %) are not checked. Lowering the threshold raises coincidental matches.
- A loose index (many derived statistics) can match a wrong number by coincidence; the CSV shows which evidence matched, so suspicious matches can be inspected.
- No semantic check: units, labels and the claim around a number are not interpreted.
