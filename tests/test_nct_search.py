"""
Tests for nct_search.py (fuzzy NCT code lookup).

No network access: the API is always mocked, so the suite stays deterministic.
"""

import json
import os
import sys
from typing import Any

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import nct_search
from nct_search import (
    clean_text,
    extract_digits,
    find_nct_code,
    load_tracked_trials,
    looks_like_nct_id,
    main as cli_main,
    nct_similarity,
    query_variants,
    rank_trials,
    search_remote,
    squash,
    study_to_trial,
    text_similarity,
    tokenize,
    trial_similarity,
)


def study(
    nct_id: str, title: str, interventions: list[str] | None = None
) -> dict[str, Any]:
    """Build a minimal ClinicalTrials.gov v2 study object."""
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": title},
            "armsInterventionsModule": {
                "interventions": [{"name": name} for name in (interventions or [])]
            },
        }
    }


TRACKED = [
    {
        "id": "NCT04895709",
        "name": "A Study of BMS-986340 as Monotherapy and in Combination With Nivolumab",
        "interventions": ["BMS-986340", "Nivolumab"],
    },
    {
        "id": "NCT05255484",
        "name": "Study of LM-108 as a Single Agent or in Combination With Pembrolizumab",
        "interventions": ["LM-108", "Pembrolizumab"],
    },
    {
        "id": "NCT04385173",
        "name": "Pilot Study of B7-H3 CAR-T in Treating Patients With Recurrent Glioblastoma",
        "interventions": ["B7-H3 CAR-T"],
    },
]


# --- text normalization -----------------------------------------------------


def test_clean_text_normalizes_whitespace_and_bounds_length() -> None:
    assert clean_text("  B7-H3   CAR-T \n") == "B7-H3 CAR-T"
    assert len(clean_text("a" * 5000)) == nct_search.MAX_QUERY_LENGTH


def test_clean_text_rejects_non_strings() -> None:
    assert clean_text(None) == ""
    assert clean_text(123) == ""
    assert clean_text(["x"]) == ""


def test_squash_removes_separators_and_case() -> None:
    assert squash("B7-H3") == "b7h3"
    assert squash("B7 H3") == "b7h3"
    assert squash("lm_108") == "lm108"


def test_tokenize_keeps_compound_names_whole() -> None:
    assert "lm-108" in tokenize("Study of LM-108 in Subjects")
    assert "study" in tokenize("Study of LM-108 in Subjects")


# --- NCT code handling ------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("NCT04895709", True),
        ("nct 04895709", True),
        ("NCT-04895709", True),
        ("NCT0489579", True),
        ("04895709", True),
        ("NCT 0489 5709", True),
    ],
)
def test_looks_like_nct_id_accepts_code_forms(text: str, expected: bool) -> None:
    assert looks_like_nct_id(text) is expected


@pytest.mark.parametrize(
    "text", ["b7h3", "LM-108", "pembrolizumab trial", "NCT", "2024 study", ""]
)
def test_looks_like_nct_id_rejects_text(text: str) -> None:
    assert looks_like_nct_id(text) is False


def test_extract_digits() -> None:
    assert extract_digits("NCT04895709") == "04895709"
    assert extract_digits("nct 0489 5709") == "04895709"
    assert extract_digits("B7-H3") is None


def test_nct_similarity_exact_typo_truncated_and_unrelated() -> None:
    exact = nct_similarity("NCT04895709", "NCT04895709")
    typo = nct_similarity("NCT04895790", "NCT04895709")
    truncated = nct_similarity("NCT0489579", "NCT04895709")
    prefix = nct_similarity("NCT048", "NCT04895709")
    unrelated = nct_similarity("NCT09999999", "NCT04895709")

    assert exact == 1.0
    assert 0.85 <= typo < exact
    assert truncated >= 0.75
    assert prefix >= 0.75
    assert unrelated < nct_search.MIN_CODE_SCORE


def test_nct_similarity_rejects_invalid_candidate() -> None:
    assert nct_similarity("NCT04895709", "not-a-code") == 0.0
    assert nct_similarity("NCT04895709", None) == 0.0


# --- text similarity --------------------------------------------------------


def test_text_similarity_matches_different_spellings() -> None:
    assert text_similarity("b7h3", "B7-H3 CAR-T in Glioblastoma") == 1.0
    assert text_similarity("LM108", "Study of LM-108 in Solid Tumours") == 1.0
    assert text_similarity("lm-108", "Study of LM-108 in Solid Tumours") == 1.0


def test_text_similarity_is_low_for_unrelated_text() -> None:
    assert text_similarity("b7h3", "A Study of Aspirin in Healthy Volunteers") < 0.5


def test_text_similarity_handles_multiple_words() -> None:
    score = text_similarity(
        "b7h3 car-t glioblastoma",
        "Pilot Study of B7-H3 CAR-T in Treating Patients With Recurrent Glioblastoma",
    )
    assert score >= 0.8


def test_text_similarity_bounds_long_candidates() -> None:
    assert 0.0 <= text_similarity("b7h3", "B7-H3 " + "x" * 10_000) <= 1.0


def test_trial_similarity_uses_interventions() -> None:
    trial = {
        "id": "NCT00000001",
        "name": "A Phase 1 Study in Solid Tumors",
        "interventions": ["CCR8 antibody"],
    }
    score, matched_on = trial_similarity("ccr8", trial)
    assert score == 1.0
    assert matched_on == "intervention"


def test_trial_similarity_code_query_only_uses_code() -> None:
    """A code-like query should not match titles with coincidental digits."""
    trial = {"id": "NCT00840957", "name": "Pharmaco Kinetic Study 04895790"}
    score, matched_on = trial_similarity("NCT04895790", trial)
    assert matched_on == "nct"
    assert score < nct_search.MIN_CODE_SCORE


# --- ranking ----------------------------------------------------------------


def test_rank_trials_orders_by_score_then_id() -> None:
    results = rank_trials("lm-108", TRACKED, threshold=0.0)
    assert results[0]["id"] == "NCT05255484"
    assert results[0]["score"] == 1.0
    assert [item["score"] for item in results] == sorted(
        (item["score"] for item in results), reverse=True
    )


def test_rank_trials_applies_threshold() -> None:
    assert rank_trials("nothing related at all", TRACKED, threshold=0.9) == []


def test_rank_trials_respects_limit_and_deduplicates() -> None:
    duplicated = TRACKED + [dict(TRACKED[0])]
    results = rank_trials("b7-h3", duplicated, threshold=0.0, limit=2)
    assert len(results) == 2
    assert len({item["id"] for item in results}) == 2


def test_rank_trials_ignores_malformed_entries() -> None:
    results = rank_trials(
        "lm-108",
        [None, "x", {"name": "no id"}, {"id": "NCT05255484", "name": "LM-108"}],
    )
    assert [item["id"] for item in results] == ["NCT05255484"]


def test_rank_trials_code_query_uses_stricter_threshold() -> None:
    """Unrelated codes scoring ~0.6 are dropped even with a low threshold."""
    results = rank_trials("NCT0489579", TRACKED, threshold=0.0)
    assert [item["id"] for item in results] == ["NCT04895709"]


def test_find_nct_code_suggests_closest_tracked_code() -> None:
    suggestions = find_nct_code("NCT04895790", TRACKED)
    assert suggestions[0]["id"] == "NCT04895709"
    assert suggestions[0]["matched_on"] == "nct"


def test_find_nct_code_returns_empty_for_hopeless_input() -> None:
    assert find_nct_code("NCT99999999", TRACKED) == []


# --- query variants ---------------------------------------------------------


def test_query_variants_expand_hyphenated_names() -> None:
    variants = query_variants("B7-H3")
    lowered = {variant.lower() for variant in variants}
    assert "b7-h3" in lowered
    assert "b7 h3" in lowered
    assert "b7h3" in lowered


def test_query_variants_repair_typo_of_known_name() -> None:
    assert "TIGIT" in query_variants("tigt", ["CCR8", "TIGIT", "B7-H3"])
    assert "FcRn" in query_variants("FCNR", ["CCR8", "FcRn"])


def test_query_variants_add_other_spelling_of_same_name() -> None:
    assert "B7-H3" in query_variants("B7H3", ["CCR8", "B7-H3"])


def test_query_variants_are_bounded_and_unique() -> None:
    variants = query_variants("a-b c-d e-f", ["a b c d e f", "abcdef"])
    assert len(variants) <= nct_search.MAX_VARIANTS
    assert len({variant.lower() for variant in variants}) == len(variants)


def test_query_variants_returns_empty_for_blank_query() -> None:
    assert query_variants("   ") == []
    assert query_variants(None) == []


def test_query_variants_do_not_rewrite_a_code() -> None:
    assert query_variants("NCT04895709") == ["NCT04895709"]


# --- API study reduction ----------------------------------------------------


def test_study_to_trial_extracts_fields() -> None:
    trial = study_to_trial(study("NCT05255484", "Study of LM-108", ["LM-108"]))
    assert trial == {
        "id": "NCT05255484",
        "name": "Study of LM-108",
        "interventions": ["LM-108"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "x",
        {},
        {"protocolSection": None},
        {"protocolSection": {"identificationModule": {}}},
        {
            "protocolSection": {
                "identificationModule": {"nctId": "BAD", "briefTitle": "x"}
            }
        },
        {"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}},
    ],
)
def test_study_to_trial_rejects_malformed(payload: Any) -> None:
    assert study_to_trial(payload) is None


# --- remote search ----------------------------------------------------------


def test_search_remote_ranks_and_merges_variant_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(term: str, page_size: int = 1000, fields: str | None = None):
        calls.append(term)
        if term.lower() == "b7h3":
            return [study("NCT04385173", "Pilot Study of B7-H3 CAR-T in Glioblastoma")]
        if term.lower() == "b7-h3":
            return [
                study("NCT04385173", "Pilot Study of B7-H3 CAR-T in Glioblastoma"),
                study(
                    "NCT05515185",
                    "B7-H3 Targeting CAR-T Cells Therapy for Solid Tumors",
                ),
                study(
                    "NCT05142189", "BNT116 Alone and in Combinations in Advanced NSCLC"
                ),
            ]
        return []

    monkeypatch.setattr(nct_search, "_search_trials", fake_search)

    results = search_remote("B7H3", threshold=0.7)

    ids = [row["id"] for row in results]
    assert "NCT04385173" in ids
    assert "NCT05515185" in ids
    # The unrelated study found by the widened query is filtered by score.
    assert "NCT05142189" not in ids
    assert calls[0] == "B7H3"
    assert "B7-H3" in calls


def test_search_remote_returns_empty_when_api_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nct_search, "_search_trials", lambda *args, **kwargs: [])
    assert search_remote("zzzz") == []


def test_search_remote_survives_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any):
        raise OSError("network down")

    monkeypatch.setattr(nct_search, "_search_trials", boom)
    with pytest.raises(OSError):
        search_remote("b7h3")


# --- trials.yaml loading ----------------------------------------------------


def write_yaml(path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def test_load_tracked_trials_deduplicates(tmp_path) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(
        config,
        {
            "targets": [
                {"name": "CCR8", "trials": [{"id": "NCT05255484", "name": "LM-108"}]},
                {"name": "LM108", "trials": [{"id": "NCT05255484", "name": "LM-108"}]},
            ]
        },
    )

    trials = load_tracked_trials(str(config))
    assert len(trials) == 1
    assert trials[0]["target"] == "CCR8"


@pytest.mark.parametrize(
    "content",
    [
        "not: [valid",
        "- just\n- a\n- list\n",
        "targets: not-a-list\n",
        "targets:\n  - name: CCR8\n    trials: not-a-list\n",
    ],
)
def test_load_tracked_trials_survives_bad_yaml(tmp_path, content: str) -> None:
    config = tmp_path / "trials.yaml"
    config.write_text(content, encoding="utf-8")
    assert load_tracked_trials(str(config)) == []


def test_load_tracked_trials_missing_file(tmp_path) -> None:
    assert load_tracked_trials(str(tmp_path / "missing.yaml")) == []


# --- CLI --------------------------------------------------------------------


def test_cli_local_search_prints_matches(tmp_path, capsys) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(
        config,
        {
            "targets": [
                {
                    "name": "CCR8",
                    "trials": [
                        {
                            "id": "NCT05255484",
                            "name": "Study of LM-108 in Solid Tumours",
                        }
                    ],
                }
            ]
        },
    )

    exit_code = cli_main(["lm108", "--local", "--yaml", str(config)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "NCT05255484" in out
    assert "Top match" in out


def test_cli_reports_no_match_with_exit_code(tmp_path, capsys) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(config, {"targets": [{"name": "CCR8", "trials": []}]})

    exit_code = cli_main(
        ["completely unrelated query", "--local", "--yaml", str(config)]
    )
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "no match" in out


def test_cli_json_output(tmp_path, capsys) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(
        config,
        {
            "targets": [
                {
                    "name": "CCR8",
                    "trials": [{"id": "NCT05255484", "name": "Study of LM-108"}],
                }
            ]
        },
    )

    assert cli_main(["lm-108", "--local", "--json", "--yaml", str(config)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "lm-108"
    assert payload["results"][0]["id"] == "NCT05255484"


def test_cli_online_search_uses_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(config, {"targets": [{"name": "B7-H3", "trials": []}]})

    def fake_search(term: str, page_size: int = 1000, fields: str | None = None):
        return [study("NCT04385173", "Pilot Study of B7-H3 CAR-T in Glioblastoma")]

    monkeypatch.setattr(nct_search, "_search_trials", fake_search)

    assert cli_main(["b7h3", "--yaml", str(config)]) == 0
    assert "NCT04385173" in capsys.readouterr().out


def test_cli_online_failure_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(
        config,
        {
            "targets": [
                {
                    "name": "CCR8",
                    "trials": [{"id": "NCT05255484", "name": "Study of LM-108"}],
                }
            ]
        },
    )

    def boom(*args: Any, **kwargs: Any):
        raise OSError("offline")

    monkeypatch.setattr(nct_search, "_search_trials", boom)

    assert cli_main(["lm108", "--yaml", str(config)]) == 0
    captured = capsys.readouterr()
    assert "NCT05255484" in captured.out
    # The warning goes to stderr so --json output stays parseable.
    assert "online search failed" in captured.err


def test_cli_rejects_empty_query(capsys) -> None:
    assert cli_main(["   "]) == 2
    assert "empty query" in capsys.readouterr().out


def test_cli_clamps_limit_and_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    config = tmp_path / "trials.yaml"
    write_yaml(
        config,
        {
            "targets": [
                {
                    "name": "CCR8",
                    "trials": [{"id": "NCT05255484", "name": "Study of LM-108"}],
                }
            ]
        },
    )

    # Out-of-range values must not crash; they are clamped.
    assert (
        cli_main(["lm108", "--local", "--yaml", str(config), "-n", "0", "-t", "5"]) == 0
    )
    assert "NCT05255484" in capsys.readouterr().out
