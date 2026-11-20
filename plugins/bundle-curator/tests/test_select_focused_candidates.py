"""Tests for scripts/select-focused-candidates.py."""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "select-focused-candidates.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "select_focused_candidates", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["select_focused_candidates"] = module
    spec.loader.exec_module(module)
    return module


mod = load_module()


def entry(path, confidence, bundle="philosophy"):
    return {"path": path, "bundle": bundle, "confidence": confidence}


class TestSelectCandidatesSortAndThreshold:
    def test_descending_sort_and_threshold_walk_stop(self):
        entries = [
            entry("a.md", 0.65),
            entry("b.md", 0.9),
            entry("c.md", 0.75),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["b.md", "c.md"]

    def test_all_below_threshold_returns_empty(self):
        entries = [entry("a.md", 0.5), entry("b.md", 0.6)]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == []

    def test_all_at_or_above_threshold_returns_all_sorted(self):
        entries = [entry("a.md", 0.7), entry("b.md", 0.95), entry("c.md", 0.8)]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["b.md", "c.md", "a.md"]


class TestAlreadyCuratedFiltering:
    def test_already_curated_paths_filtered_out(self):
        entries = [entry("a.md", 0.95), entry("b.md", 0.9)]
        result = mod.select_candidates(
            entries, curated_paths={"a.md"}, min_confidence=0.7
        )
        assert result == ["b.md"]

    def test_curated_high_confidence_path_does_not_shift_threshold_walk(self):
        # If the curated filter ran after the threshold walk instead of
        # before, a curated high-confidence entry could still influence
        # ordering. Filtering first means only b/c/d are ever considered.
        entries = [
            entry("curated.md", 0.99),
            entry("b.md", 0.9),
            entry("c.md", 0.75),
            entry("d.md", 0.65),
        ]
        result = mod.select_candidates(
            entries, curated_paths={"curated.md"}, min_confidence=0.7
        )
        assert result == ["b.md", "c.md"]


class TestShortCircuit:
    def test_short_circuits_on_first_sub_threshold_value(self):
        entries = [
            entry("high.md", 0.9),
            entry("mid.md", 0.75),
            entry("boundary.md", 0.65),  # first sub-threshold entry
            entry("very-low.md", 0.1),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["high.md", "mid.md"]

    def test_malformed_entries_after_cutoff_do_not_break_run(self):
        # Two malformed entries (non-numeric confidence with no path; a
        # bare confidence with no path or bundle at all) sit below the
        # first sub-threshold entry once sorted. If the walk scanned past
        # the cutoff and tried to use their data, this would raise
        # (TypeError comparing str/float, or a KeyError on 'path'). It
        # must not: the break happens at "boundary.md" and the malformed
        # entries are never inspected beyond their (-inf) sort key.
        entries = [
            entry("high.md", 0.9),
            entry("boundary.md", 0.65),  # first sub-threshold (T=0.7)
            {"bundle": "philosophy", "confidence": "not-a-number"},
            {"confidence": 0.05},
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["high.md"]

    def test_non_numeric_confidence_sorts_last_without_crashing(self):
        entries = [
            entry("high.md", 0.9),
            {"path": "bad.md", "bundle": "philosophy", "confidence": "oops"},
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.0
        )
        assert result == ["high.md"]

    def test_entry_missing_path_above_threshold_is_skipped_not_crashed(self):
        entries = [
            entry("high.md", 0.9),
            {"bundle": "philosophy", "confidence": 0.85},  # no path field
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["high.md"]


class TestSortKey:
    def test_missing_confidence_is_negative_infinity(self):
        assert mod.sort_key({}) == float("-inf")

    def test_bool_confidence_is_not_treated_as_numeric(self):
        # bool is a subclass of int in Python; guard against True/False
        # silently sorting as 1.0/0.0 confidence.
        assert mod.sort_key({"confidence": True}) == float("-inf")

    def test_nan_confidence_sorts_as_negative_infinity(self):
        # float('nan') passes isinstance(value, (int, float)), so without an
        # explicit finiteness check it would sort as NaN, not -inf.
        assert mod.sort_key({"confidence": float("nan")}) == float("-inf")

    def test_inf_confidence_sorts_as_negative_infinity(self):
        # +inf is numeric and would otherwise sort/select as the highest
        # possible confidence (`inf < x` is correctly False, so unlike NaN
        # it has no comparison-bypass bug) -- but a confidence outside a
        # sane range is not a real score, so `math.isfinite` excludes it the
        # same as any other unusable value.
        assert mod.sort_key({"confidence": float("inf")}) == float("-inf")


class TestNonFiniteConfidenceGate:
    def test_nan_confidence_entry_is_dropped_not_selected(self):
        # nan < min_confidence is always False (NaN never compares true
        # either way), so a NaN-confidence entry must not slip past the
        # threshold walk the way it would if sort_key returned NaN as-is.
        entries = [
            entry("high1.md", 0.95),
            entry("nan.md", float("nan")),
            entry("high2.md", 0.9),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["high1.md", "high2.md"]
        assert "nan.md" not in result

    def test_inf_confidence_entry_is_dropped_not_selected(self):
        # Pre-fix, a literal +inf confidence sorted to the top and was
        # selected as the single highest-confidence candidate. Post-fix it
        # must fall back to -inf and be dropped, same as NaN -- not merely
        # excluded from the result count, but genuinely absent while the
        # next-highest legitimate entry still gets selected in its place.
        entries = [
            entry("high1.md", 0.95),
            entry("inf.md", float("inf")),
            entry("high2.md", 0.9),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["high1.md", "high2.md"]
        assert "inf.md" not in result


class TestDuplicatePathDedup:
    def test_duplicate_path_keeps_latest_line_for_same_bundle(self):
        """The latest line for a path and bundle replaces earlier scores.

        dup.md is recorded at 0.99 and later at 0.85. The latest score is
        0.85, so other.md at 0.9 sorts ahead of it.
        """
        entries = [
            entry("dup.md", 0.99),
            entry("other.md", 0.9),
            entry("dup.md", 0.85),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["other.md", "dup.md"]
        assert result.count("dup.md") == 1

    def test_dedup_keeps_latest_line_not_original_list_order(self):
        # The lower score is first in the file. The later 0.95 line is the
        # one that remains after the (path, bundle) collapse.
        entries = [
            entry("dup.md", 0.8),
            entry("dup.md", 0.95),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["dup.md"]

    def test_duplicate_above_threshold_does_not_break_the_walk(self):
        # The later dup.md line (0.9) is the one that remains. The walk
        # must still reach other.md, and must still stop at boundary.md.
        entries = [
            entry("dup.md", 0.95),
            entry("dup.md", 0.9),
            entry("other.md", 0.8),
            entry("boundary.md", 0.65),  # first sub-threshold entry (T=0.7)
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["dup.md", "other.md"]


HIGH_THEN_LOW = (
    '{"path": "fleeting/a.md", "bundle": "observability", "confidence": 0.9}\n'
    '{"path": "fleeting/a.md", "bundle": "observability", "confidence": 0.2}\n'
)
LOW_THEN_HIGH = (
    '{"path": "fleeting/a.md", "bundle": "observability", "confidence": 0.2}\n'
    '{"path": "fleeting/a.md", "bundle": "observability", "confidence": 0.9}\n'
)


class TestLatestRatingLineWins:
    def test_later_lower_score_replaces_earlier_higher_score(
        self, tmp_path: Path
    ):
        ratings = tmp_path / "observability.jsonl"
        ratings.write_text(HIGH_THEN_LOW, encoding="utf-8")
        entries = mod.load_ratings(ratings)
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.5
        )
        assert result == []

    def test_later_higher_score_replaces_earlier_lower_score(
        self, tmp_path: Path
    ):
        ratings = tmp_path / "observability.jsonl"
        ratings.write_text(LOW_THEN_HIGH, encoding="utf-8")
        entries = mod.load_ratings(ratings)
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.5
        )
        assert result == ["fleeting/a.md"]

    def test_later_line_for_a_different_bundle_does_not_replace_earlier_line(
        self,
    ):
        entries = [
            entry("fleeting/a.md", 0.9, "observability"),
            entry("fleeting/a.md", 0.2, "other"),
        ]
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.5
        )
        assert result == ["fleeting/a.md"]


def write_run(tmp_path: Path, ratings_text: str) -> Path:
    """Bundle dir, ledger, and ratings file under a temporary run root.

    This script locates the repo from ``__file__`` rather than the process
    cwd, so the invoked copy lives under the run.
    """
    run = tmp_path / "run"
    (run / "observability").mkdir(parents=True)
    (run / "curation").mkdir()
    (run / "ratings").mkdir()
    (run / "scripts").mkdir()
    (run / "okf-core.toml").write_text(
        '[bundles.observability]\npath = "observability"\n',
        encoding="utf-8",
    )
    (run / "curation" / "observability.txt").write_text("", encoding="utf-8")
    (run / "ratings" / "observability.jsonl").write_text(
        ratings_text, encoding="utf-8"
    )
    shutil.copy(SCRIPT, run / "scripts" / "select-focused-candidates.py")
    return run


def run_select(run: Path) -> subprocess.CompletedProcess[str]:
    script = run / "scripts" / "select-focused-candidates.py"
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "observability",
            "--min-confidence",
            "0.5",
        ],
        cwd=run,
        capture_output=True,
        text=True,
        check=False,
    )


class TestLatestScoreCli:
    def test_later_lower_score_exits_zero_with_empty_stdout(
        self, tmp_path: Path
    ):
        result = run_select(write_run(tmp_path, HIGH_THEN_LOW))
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_later_higher_score_prints_path(self, tmp_path: Path):
        result = run_select(write_run(tmp_path, LOW_THEN_HIGH))
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["fleeting/a.md"]


class TestMinConfidenceType:
    def test_accepts_value_within_range(self):
        assert mod.min_confidence_type("0.8") == 0.8

    def test_accepts_boundary_values(self):
        assert mod.min_confidence_type("0") == 0.0
        assert mod.min_confidence_type("1") == 1.0

    def test_rejects_nan(self):
        # The exact footgun this guards against: plain `type=float` on
        # argparse accepts "nan", and `confidence < nan` is always False,
        # so the threshold walk in `select_candidates` would never see a
        # sub-threshold entry and never stop -- possibly selecting
        # unintended entries. Must be rejected at parse time instead.
        with pytest.raises(argparse.ArgumentTypeError, match="finite"):
            mod.min_confidence_type("nan")

    def test_rejects_infinity(self):
        with pytest.raises(argparse.ArgumentTypeError, match="finite"):
            mod.min_confidence_type("inf")

    def test_rejects_value_above_one(self):
        with pytest.raises(argparse.ArgumentTypeError, match=r"\[0, 1\]"):
            mod.min_confidence_type("1.5")

    def test_rejects_negative_value(self):
        with pytest.raises(argparse.ArgumentTypeError, match=r"\[0, 1\]"):
            mod.min_confidence_type("-0.1")

    def test_rejects_non_numeric_string(self):
        with pytest.raises(
            argparse.ArgumentTypeError, match="invalid float"
        ):
            mod.min_confidence_type("not-a-number")


class TestLoadRatings:
    def test_skips_malformed_json_lines_without_raising(self, tmp_path: Path):
        ratings = tmp_path / "philosophy.jsonl"
        ratings.write_text(
            '{"path": "a.md", "bundle": "philosophy", "confidence": 0.9}\n'
            "not valid json\n",
            encoding="utf-8",
        )
        entries = mod.load_ratings(ratings)
        assert len(entries) == 2
        result = mod.select_candidates(
            entries, curated_paths=set(), min_confidence=0.7
        )
        assert result == ["a.md"]

    def test_missing_file_returns_empty_list(self, tmp_path: Path):
        assert mod.load_ratings(tmp_path / "missing.jsonl") == []

    def test_blank_lines_are_ignored(self, tmp_path: Path):
        ratings = tmp_path / "philosophy.jsonl"
        ratings.write_text(
            '{"path": "a.md", "bundle": "philosophy", "confidence": 0.9}\n'
            "\n"
            "   \n",
            encoding="utf-8",
        )
        assert len(mod.load_ratings(ratings)) == 1


class TestLoadLedgerPaths:
    def test_ignores_comments_and_blank_lines(self, tmp_path: Path):
        ledger = tmp_path / "domain.txt"
        ledger.write_text(
            "# comment\n\nfleeting/a.md\nfleeting/b.md\n", encoding="utf-8"
        )
        assert mod.load_ledger_paths(ledger) == {
            "fleeting/a.md",
            "fleeting/b.md",
        }

    def test_missing_ledger_returns_empty_set(self, tmp_path: Path):
        assert mod.load_ledger_paths(tmp_path / "missing.txt") == set()


class TestFindRoot:
    def test_resolves_repo_root_containing_okf_core_toml(self, tmp_path: Path):
        root = tmp_path / "repo"
        nested = root / "scripts"
        nested.mkdir(parents=True)
        (root / "okf-core.toml").write_text("", encoding="utf-8")
        assert mod.find_root(nested) == root

    def test_missing_okf_core_toml_raises(self, tmp_path: Path):
        try:
            mod.find_root(tmp_path)
        except SystemExit as exc:
            assert "okf-core.toml" in str(exc)
        else:
            raise AssertionError("expected SystemExit")
