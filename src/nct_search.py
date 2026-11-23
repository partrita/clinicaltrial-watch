"""
Fuzzy NCT code lookup for ClinicalTrials.gov.

The plain keyword search on ClinicalTrials.gov only finds studies whose text
contains the term as written, and the rest of this project requires an exact
NCT ID. This module lets an approximate query find the right NCT code instead:

  * a code with a typo or a missing digit  ("NCT0489579", "nct 4895709")
  * a compound or target written differently ("B7H3", "ccr-8", "LM108")
  * a half-remembered title ("lm-108 pembrolizumab solid tumour")

Candidates come from the tracked trials in ``trials.yaml`` and from a widened
set of ClinicalTrials.gov queries (hyphen/space variants and the closest known
target name). Every candidate is scored against the query -- the ID digits, the
brief title and the intervention names -- and the best matches are returned
with their score so a person can confirm the code before using it.

Usage (see also ``python src/nct_search.py --help``):

    pixi run python src/nct_search.py "b7h3 car-t"
    pixi run python src/nct_search.py --local "NCT0489579"
    pixi run python src/nct_search.py --json "lm108"

Standard library only: no extra dependency is added to the project.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

try:
    from utils import check_file_size, is_valid_nct_id
except ImportError:
    from src.utils import check_file_size, is_valid_nct_id

# --- Limits (defensive bounds for untrusted input, CWE-400) -----------------
MAX_QUERY_LENGTH = 500
MAX_CANDIDATE_TEXT_LENGTH = 1000
MAX_REMOTE_STUDIES = 2000
MAX_VARIANTS = 4
DEFAULT_THRESHOLD = 0.55
# Two unrelated 8-digit codes can still score around 0.6 on character overlap,
# so a code-like query needs a stricter bar than a text query.
MIN_CODE_SCORE = 0.75
DEFAULT_LIMIT = 10

# Words that carry no target information and would inflate a token score.
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "vs",
        "versus",
        "study",
        "studies",
        "trial",
        "trials",
        "phase",
        "patients",
        "participants",
        "subjects",
        "subcutaneous",
    }
)

# Fields requested from the API so scores can use titles and interventions.
SEARCH_FIELDS = "NCTId,BriefTitle,InterventionName,OverallStatus,Phase"

_TOKEN_SPLIT = re.compile(r"[^\w\-]+", re.UNICODE)
_DIGIT_TO_LETTER = re.compile(r"(?<=\d)(?=[A-Za-z])")
_LETTER_TO_DIGIT = re.compile(r"(?<=[A-Za-z])(?=\d)")


def clean_text(text: Any, max_length: int = MAX_QUERY_LENGTH) -> str:
    """Normalize unicode and whitespace, and bound the length of external text."""
    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFKC", text)[:max_length]
    return " ".join(normalized.split())


def squash(text: Any) -> str:
    """Lowercase and drop every separator, so 'B7-H3' and 'B7 H3' become 'b7h3'."""
    return "".join(ch for ch in clean_text(text).lower() if ch.isalnum())


def tokenize(text: Any) -> list[str]:
    """Split into lowercase words, keeping hyphens inside compounds ('lm-108')."""
    return [
        token
        for token in (
            t.strip("-") for t in _TOKEN_SPLIT.split(clean_text(text).lower())
        )
        if token
    ]


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _typo_ratio(a: str, b: str) -> float:
    """
    Ratio that also catches swapped letters in short names.

    SequenceMatcher scores a transposition in a 4-letter name ('FCNR' for
    'FcRn') only 0.5, which is too low for a name that is clearly the same word
    with two letters in the wrong order.
    """
    ratio = _ratio(a, b)
    if len(a) >= 3 and len(b) >= 3 and sorted(a) == sorted(b):
        return max(ratio, 0.85)
    return ratio


def _partial_ratio(needle: str, haystack: str) -> float:
    """Best ratio of `needle` against a window of `haystack` of the same length."""
    if len(needle) > len(haystack):
        needle, haystack = haystack, needle
    if not needle:
        return 0.0
    if needle in haystack:
        return 1.0
    span = len(needle)
    step = max(1, span // 5)
    best = 0.0
    for start in range(0, len(haystack) - span + 1, step):
        best = max(best, _ratio(needle, haystack[start : start + span]))
        if best >= 0.99:
            break
    return best


def text_similarity(query: Any, candidate: Any) -> float:
    """
    Score how well `candidate` text matches `query` on a 0..1 scale.

    Separator-insensitive containment ('lm108' in 'study of lm-108 ...') counts
    as a full match; otherwise the best of a windowed character ratio and a
    content-word ratio is used, so a query of several words still scores well
    against a long title that contains them.
    """
    query_clean = clean_text(query)
    cand_clean = clean_text(candidate, MAX_CANDIDATE_TEXT_LENGTH)
    q_squash = squash(query_clean)
    c_squash = squash(cand_clean)
    if not q_squash or not c_squash:
        return 0.0

    score = 0.0
    if len(q_squash) >= 4 and q_squash in c_squash:
        score = 1.0
    elif len(q_squash) >= 6:
        # Windowed character comparison is only meaningful for a query long
        # enough that a chance overlap with a long title is unlikely.
        score = _partial_ratio(q_squash, c_squash)

    q_tokens = [t for t in tokenize(query_clean) if t not in STOP_WORDS and len(t) > 1]
    c_tokens = tokenize(cand_clean)
    if q_tokens and c_tokens:
        total = 0.0
        for token in q_tokens:
            best = 0.0
            for candidate_token in c_tokens:
                if token == candidate_token:
                    best = 1.0
                    break
                if len(token) < 3:
                    # Fuzzy matching of 1-2 character tokens is mostly noise.
                    continue
                best = max(best, _typo_ratio(token, candidate_token))
            total += best
        # Token matching is a recall aid, never a full replacement for the ratio.
        score = max(score, 0.95 * total / len(q_tokens))

    return round(min(score, 1.0), 4)


def extract_digits(text: Any) -> str | None:
    """Return the digits of a code-like input such as 'nct 04895709' or '4895709'."""
    if not isinstance(text, str):
        return None
    cleaned = clean_text(text).lower()
    cleaned = re.sub(r"^nct", "", cleaned)
    cleaned = re.sub(r"[\s\-_]", "", cleaned)
    if re.fullmatch(r"\d{4,9}", cleaned):
        return cleaned
    return None


def looks_like_nct_id(text: Any) -> bool:
    """True when the input is an NCT code, with or without the prefix/formatting."""
    cleaned = clean_text(text).lower().replace(" ", "")
    if "nct" in cleaned and re.fullmatch(r"nct[\-_]?\d{3,9}", cleaned):
        return True
    return extract_digits(text) is not None


def nct_similarity(query: Any, nct_id: Any) -> float:
    """
    Score a code-like query against an NCT ID.

    NCT numbers are sequential, so a shared prefix means the codes are close; a
    truncated code ('NCT04895') therefore scores much higher than an unrelated
    one, and a single wrong digit still scores well above the threshold.
    """
    if not isinstance(nct_id, str) or not is_valid_nct_id(nct_id):
        return 0.0
    query_digits = extract_digits(query)
    if not query_digits:
        # Allow a malformed-but-close code such as 'NCT4895709' or 'NCT-04895709'.
        query_digits = "".join(ch for ch in clean_text(query) if ch.isdigit())[:9]
    candidate_digits = nct_id[3:]
    if not query_digits or not candidate_digits:
        return 0.0

    if query_digits == candidate_digits:
        return 1.0
    # A truncated code is a genuine (if less certain) match: NCT numbers are
    # sequential, so the remaining digits only narrow the candidate down.
    if len(query_digits) < len(candidate_digits) and candidate_digits.startswith(
        query_digits
    ):
        coverage = len(query_digits) / len(candidate_digits)
        return round(0.75 + 0.24 * coverage, 4)

    shared = 0
    for query_ch, cand_ch in zip(query_digits, candidate_digits):
        if query_ch != cand_ch:
            break
        shared += 1
    prefix_ratio = shared / max(len(query_digits), len(candidate_digits))
    score = max(_ratio(query_digits, candidate_digits), 0.98 * prefix_ratio)
    return round(min(score, 1.0), 4)


def study_to_trial(study: Any) -> dict[str, Any] | None:
    """Reduce an API study object to {'id', 'name', 'interventions'}."""
    if not isinstance(study, dict):
        return None
    protocol = study.get("protocolSection")
    if not isinstance(protocol, dict):
        return None
    identity = protocol.get("identificationModule")
    if not isinstance(identity, dict):
        return None
    nct_id = identity.get("nctId")
    title = identity.get("briefTitle")
    if not isinstance(nct_id, str) or not is_valid_nct_id(nct_id):
        return None
    if not isinstance(title, str) or not title.strip():
        return None

    interventions: list[str] = []
    arms = protocol.get("armsInterventionsModule")
    if isinstance(arms, dict):
        raw_interventions = arms.get("interventions")
        if isinstance(raw_interventions, list):
            for item in raw_interventions[:MAX_REMOTE_STUDIES]:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    interventions.append(clean_text(name, MAX_CANDIDATE_TEXT_LENGTH))

    return {
        "id": nct_id,
        "name": clean_text(title, MAX_CANDIDATE_TEXT_LENGTH),
        "interventions": interventions,
    }


def trial_similarity(query: Any, trial: dict[str, Any]) -> tuple[float, str]:
    """Score one trial against the query; returns (score, matched field)."""
    nct_id = trial.get("id")
    # A code-like query is asking for a code, not for title words: scoring titles
    # as well would only add noise from incidental number overlap.
    if looks_like_nct_id(query):
        if isinstance(nct_id, str):
            return nct_similarity(query, nct_id), "nct"
        return 0.0, ""

    best = 0.0
    matched_on = ""

    title = trial.get("name")
    score = text_similarity(query, title)
    if score > best:
        best, matched_on = score, "title"

    interventions = trial.get("interventions")
    if isinstance(interventions, (list, tuple)):
        for intervention in interventions[:50]:
            score = text_similarity(query, intervention)
            if score > best:
                best, matched_on = score, "intervention"

    return round(best, 4), matched_on


def rank_trials(
    query: Any,
    trials: Iterable[dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    Rank trials by similarity to the query, dropping scores below `threshold`.

    Each result is {'id', 'name', 'score', 'matched_on'}; the order is by score
    descending, then by NCT ID so ties are stable.
    """
    scored: list[dict[str, Any]] = []
    seen: set[str] = set()
    effective_threshold = (
        max(threshold, MIN_CODE_SCORE) if looks_like_nct_id(query) else threshold
    )
    for trial in trials:
        if not isinstance(trial, dict):
            continue
        nct_id = trial.get("id")
        if not isinstance(nct_id, str) or not nct_id or nct_id in seen:
            continue
        seen.add(nct_id)
        score, matched_on = trial_similarity(query, trial)
        if score < effective_threshold:
            continue
        scored.append(
            {
                "id": nct_id,
                "name": clean_text(trial.get("name", ""), MAX_CANDIDATE_TEXT_LENGTH),
                "score": score,
                "matched_on": matched_on,
            }
        )

    scored.sort(key=lambda item: (-item["score"], item["id"]))
    return scored[: max(1, limit)]


def find_nct_code(
    query: Any,
    trials: Iterable[dict[str, Any]],
    threshold: float = 0.75,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Closest tracked NCT codes for a possibly mistyped code (suggestions only)."""
    return rank_trials(query, trials, threshold=threshold, limit=limit)


def _hyphenated_variant(text: str) -> str | None:
    """
    Guess where a compound name is usually hyphenated: 'B7H3' -> 'B7-H3', 'LM108' -> 'LM-108'.

    ClinicalTrials.gov returns noticeably more studies for the hyphenated form,
    so one guessed variant is worth a search when the input has no separator.
    """
    if not any(ch.isdigit() for ch in text) or not any(ch.isalpha() for ch in text):
        return None
    if any(not ch.isalnum() for ch in text):
        return None
    match = _DIGIT_TO_LETTER.search(text)
    if match:
        return text[: match.start()] + "-" + text[match.start() :]
    transitions = list(_LETTER_TO_DIGIT.finditer(text))
    if transitions:
        index = transitions[-1].start()
        return text[:index] + "-" + text[index:]
    return None


def query_variants(query: Any, known_names: Sequence[str] = ()) -> list[str]:
    """
    Search terms to try for one query, most literal first.

    'B7-H3' gains 'B7 H3' and 'B7H3' (ClinicalTrials.gov returns noticeably more
    studies for the spaced form), and a near-miss of a known target name is
    replaced by that name so a typo still finds the target's trials.
    """
    base = clean_text(query)
    if not base:
        return []

    variants: list[str] = [base]

    def add(value: str) -> None:
        value = " ".join(value.split())
        if value and len(variants) < MAX_VARIANTS:
            if value.lower() not in {existing.lower() for existing in variants}:
                variants.append(value)

    if not looks_like_nct_id(base):
        add(base.replace("-", " "))
        add(base.replace("-", ""))
        add(base.replace(" ", "-"))
        hyphenated = _hyphenated_variant(base.replace(" ", ""))
        if hyphenated:
            add(hyphenated)

    # A typo of a target we already track: the target's own spelling searches better.
    # A typo of a target we already track: the target's own spelling searches better.
    # The same squash with a different spelling ('B7H3' vs 'B7-H3') counts too,
    # because ClinicalTrials.gov returns noticeably more studies for one form.
    base_squash = squash(base)
    best_name, best_score = "", 0.0
    for name in known_names[:100]:
        if not isinstance(name, str):
            continue
        name_squash = squash(name)
        if name_squash and name_squash == base_squash and name.strip() != base:
            add(name)
            continue
        score = _typo_ratio(base_squash, name_squash)
        if 0.75 <= score < 1.0 and score > best_score:
            best_name, best_score = name, score
    if best_name:
        add(best_name)

    return variants[:MAX_VARIANTS]


def load_tracked_trials(yaml_path: str = "trials.yaml") -> list[dict[str, Any]]:
    """Read the tracked trials out of trials.yaml, ignoring unrelated keys."""
    if not os.path.exists(yaml_path):
        return []

    check_file_size(yaml_path)

    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a project dependency
        print("Warning: PyYAML is not available; tracked trials were not loaded.")
        return []

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        print(f"Warning: could not read {yaml_path}: {e}")
        return []

    if not isinstance(data, dict):
        return []

    trials: list[dict[str, Any]] = []
    seen: set[str] = set()
    targets = data.get("targets")
    if not isinstance(targets, list):
        return []

    for target in targets[:100]:
        if not isinstance(target, dict):
            continue
        entries = target.get("trials")
        if not isinstance(entries, list):
            continue
        for entry in entries[:1000]:
            if not isinstance(entry, dict):
                continue
            nct_id = entry.get("id")
            if not isinstance(nct_id, str) or nct_id in seen:
                continue
            seen.add(nct_id)
            trials.append(
                {
                    "id": nct_id,
                    "name": clean_text(
                        entry.get("name", ""), MAX_CANDIDATE_TEXT_LENGTH
                    ),
                    "target": clean_text(target.get("name", "")),
                }
            )
    return trials


def load_target_names(yaml_path: str = "trials.yaml") -> list[str]:
    """Target names from trials.yaml, used to repair a mistyped query."""
    return [
        name
        for name in (
            trial.get("target", "") for trial in load_tracked_trials(yaml_path)
        )
        if name
    ]


def _search_trials(
    term: str, page_size: int, fields: str | None
) -> list[dict[str, Any]]:
    """Call the project's existing API search (imported lazily to avoid a cycle)."""
    try:
        from auto_discover_trials import search_trials
    except ImportError:  # pragma: no cover - depends on how the module is started
        from src.auto_discover_trials import search_trials
    return search_trials(term, page_size=page_size, fields=fields)


def search_remote(
    query: Any,
    threshold: float = DEFAULT_THRESHOLD,
    limit: int = DEFAULT_LIMIT,
    page_size: int = 100,
    known_names: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """
    Search ClinicalTrials.gov with the query and its variants, then rank by score.

    Returns [] when the API is unreachable or finds nothing relevant; the caller
    can still fall back to the locally tracked trials.
    """
    variants = query_variants(query, known_names)
    if not variants:
        return []

    pool: dict[str, dict[str, Any]] = {}
    for variant in variants:
        studies = _search_trials(variant, page_size, SEARCH_FIELDS)
        for study in studies[:MAX_REMOTE_STUDIES]:
            trial = study_to_trial(study)
            if trial and trial["id"] not in pool:
                pool[trial["id"]] = trial
        if len(pool) >= MAX_REMOTE_STUDIES:
            break

    return rank_trials(query, pool.values(), threshold=threshold, limit=limit)


def _format_rows(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return "  (no match above the threshold)"
    lines = [f"  {'SCORE':>5}  {'NCT ID':<11}  {'MATCH':<12}  TITLE"]
    for row in rows:
        title = row.get("name", "")
        if len(title) > 90:
            title = title[:87] + "..."
        lines.append(
            f"  {row['score']:>5.3f}  {row['id']:<11}  {row.get('matched_on', ''):<12}  {title}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Find ClinicalTrials.gov NCT codes from an approximate query "
            "(typo'd code, differently written target, or partial title)."
        )
    )
    parser.add_argument("query", nargs="+", help="Approximate name, title, or NCT code")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Search only the trials already tracked in trials.yaml (no network)",
    )
    parser.add_argument(
        "--yaml",
        "-y",
        default="trials.yaml",
        help="Path to trials.yaml (default: trials.yaml)",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=DEFAULT_LIMIT,
        help="Maximum results (default: 10)",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Minimum score 0..1 (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--variants",
        action="store_true",
        help="Show the query variants that were searched",
    )
    parser.add_argument("--json", action="store_true", help="Print results as JSON")
    args = parser.parse_args(argv)

    query = clean_text(" ".join(args.query))
    if not query:
        print("Error: empty query.")
        return 2

    limit = max(1, min(args.limit, 100))
    threshold = min(max(args.threshold, 0.0), 1.0)

    tracked = load_tracked_trials(args.yaml)
    known_names = sorted(
        {trial.get("target", "") for trial in tracked if trial.get("target")}
    )

    variants = query_variants(query, known_names)
    if args.variants and not args.json:
        print(f"Query variants: {variants}")

    # Local matches first: they are already confirmed and need no network call.
    results = rank_trials(query, tracked, threshold=threshold, limit=limit)

    if not args.local:
        if not args.json:
            print(f"Searching ClinicalTrials.gov for '{query}'...")
        try:
            remote = search_remote(
                query,
                threshold=threshold,
                limit=limit,
                known_names=known_names,
            )
        except (OSError, ValueError) as e:
            print(
                f"Warning: online search failed ({e}); showing tracked trials only.",
                file=sys.stderr,
            )
            remote = []

        by_id = {row["id"]: row for row in results}
        for row in remote:
            existing = by_id.get(row["id"])
            if existing is None or row["score"] > existing["score"]:
                by_id[row["id"]] = row
        results = sorted(by_id.values(), key=lambda item: (-item["score"], item["id"]))[
            :limit
        ]

    if args.json:
        print(
            json.dumps(
                {"query": query, "variants": variants, "results": results},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"\nBest matches for '{query}':")
        print(_format_rows(results))
        if results:
            print(f"\nTop match: {results[0]['id']} (score {results[0]['score']:.3f})")

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
