import subprocess
import textwrap
from pathlib import Path

import pytest

from evidence_checker.cli import main
from evidence_checker.extract import extract_numbers, normalize, load_report_text
from evidence_checker.match import Waiver, check, rounding_interval
from evidence_checker.sources import SourceSpec, build_index


# --------------------------------------------------------------------- extraction

def test_extracts_signed_and_unicode_minus():
    nums = extract_numbers(normalize("gap was \u22124.700 %RH and +0.1683 bias"), min_decimals=3)
    assert [n.signed for n in nums] == ["-4.700", "+0.1683"]


def test_skips_versions_hashes_and_short_decimals():
    text = "Python 3.12.12, tag v1.0.0, sha dce3b9b9d4e44fdd, see §12.5, value 0.925."
    nums = extract_numbers(text, min_decimals=3)
    assert [n.text for n in nums] == ["0.925"]  # sentence-final dot is fine


def test_section_tracking_and_markdown_escapes():
    text = "# 8. Static\nMBE \\-1.1412\n## 8.2 More\nRMSE 1.2228"
    nums = extract_numbers(normalize(text))
    assert (nums[0].signed, nums[0].section) == ("-1.1412", "8. Static")
    assert nums[1].section == "8.2 More"


def test_html_report(tmp_path):
    p = tmp_path / "r.html"
    p.write_text("<h2>10. Held-out</h2><table><tr><td>0.4566</td></tr></table><p>1.140287</p>", encoding="utf-8")
    nums = extract_numbers(load_report_text(p))
    assert [n.text for n in nums] == ["0.4566", "1.140287"]
    assert nums[0].section == "10. Held-out"


# --------------------------------------------------------------------- rounding

def test_rounding_interval_catches_half_unit_error():
    lo, hi = rounding_interval("4.700")
    assert not (lo <= 4.699451 <= hi)          # the real Chapter 11 error
    lo, hi = rounding_interval("4.699")
    assert lo <= 4.699451 <= hi


def test_rounding_interval_accepts_exact_tie_either_way():
    lo, hi = rounding_interval("0.925")
    assert lo <= 0.9249999999999998 <= hi


# --------------------------------------------------------------------- sources and matching

@pytest.fixture
def evidence_dir(tmp_path):
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "model.csv").write_text("Model,RMSE,Role\nC0,1.1402873,A\nC1,0.4566090,A\nC5,0.2131,B\n")
    (d / "spec.json").write_text('{"limits": {"accuracy": 2.0, "t90_s": 60.5}}')
    (d / "notes.txt").write_text("gap = -4.699451\n")
    return d


def test_dir_source_raw_derived_json_text(evidence_dir):
    idx = build_index([SourceSpec("ev", "dir", str(evidence_dir), derived=True)])
    numbers = extract_numbers(
        "RMSE 0.4566 and 1.140; mean RMSE 0.6033; limit 60.500; gap -4.699; wrong -4.700; ghost 9.876")
    res = {r.number.signed: r for r in check(numbers, idx)}
    assert res["0.4566"].status == "MATCHED" and res["0.4566"].matches[0].file == "model.csv"
    assert res["1.140"].status == "MATCHED"
    assert res["0.6033"].matches[0].where.startswith("mean(RMSE")          # derived statistic
    assert res["60.500"].matches[0].where == "limits.t90_s"                 # JSON key path
    assert res["-4.699"].status == "MATCHED"
    assert res["-4.700"].status == "UNMATCHED"
    assert res["9.876"].status == "UNMATCHED"


def test_percent_option(evidence_dir):
    idx = build_index([SourceSpec("ev", "dir", str(evidence_dir), percent=True)])
    res = check(extract_numbers("share 45.661 %"), idx)
    assert res[0].status == "MATCHED" and res[0].matches[0].where.endswith("×100")


def test_waiver_requires_value_and_context(evidence_dir):
    idx = build_index([SourceSpec("ev", "dir", str(evidence_dir))])
    w = [Waiver("1.2495", "sample-level RMSE", "recomputed from raw data")]
    a, b = check(extract_numbers("sample-level RMSE 1.2495\nan unrelated value 1.2495"), idx, w)
    assert (a.status, b.status) == ("WAIVED", "UNMATCHED")


def test_git_source_reads_tagged_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "t.csv").write_text("x\n0.262903\n")
    run("add", "."); run("commit", "-qm", "v1"); run("tag", "v1")
    (repo / "t.csv").write_text("x\n0.999999\n")
    run("commit", "-qam", "later")
    idx = build_index([SourceSpec("rel", "git", str(repo), ref="v1", glob="*.csv")])
    r = check(extract_numbers("UCL 0.2629 and 0.999999"), idx)
    assert [x.status for x in r] == ["MATCHED", "UNMATCHED"]
    assert r[0].matches[0].file == "t.csv@v1"


# --------------------------------------------------------------------- end to end

def test_cli_end_to_end(tmp_path, evidence_dir):
    cfg = tmp_path / "evidence.toml"
    cfg.write_text(textwrap.dedent(f"""
        [report]
        min_decimals = 3
        [[sources]]
        label = "ev"
        type = "dir"
        path = "{evidence_dir.name}"
        derived = true
    """))
    (tmp_path / evidence_dir.name).exists()
    rpt = tmp_path / "chapter.md"
    rpt.write_text("# 10. Held-out\nC1 RMSE 0.4566; typo 0.4576\n")
    out = tmp_path / "out"
    code = main(["--config", str(cfg), "--out", str(out), "--strict", str(rpt)])
    assert code == 1
    text = (out / "chapter_evidence.csv").read_text()
    assert "MATCHED,0.4566" in text and "UNMATCHED,0.4576" in text
