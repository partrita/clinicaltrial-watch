"""Tests for human-readable diff rendering helpers."""

from generate_target_pages import (
    _format_diff_cell,
    _render_trial_history_body,
    _safe_timestamp,
)
from utils import humanize_diff_field, humanize_diff_value, parse_diff_records


class TestHumanizeDiffField:
    def test_known_status_field(self):
        assert humanize_diff_field("statusModule.overallStatus") == "모집 상태"

    def test_known_nested_field(self):
        assert (
            humanize_diff_field("statusModule.completionDateStruct.date") == "종료 예정일"
        )
        assert humanize_diff_field("designModule.enrollmentInfo.count") == "모집 인원"

    def test_list_item_with_index(self):
        assert (
            humanize_diff_field("contactsLocationsModule.locations.[39]city")
            == "연구 기관 #40 · 도시"
        )
        assert (
            humanize_diff_field("outcomesModule.primaryOutcomes.[0]")
            == "주 평가 지표 #1"
        )

    def test_deepdiff_root_bracket_form(self):
        path = "root['contactsLocationsModule']['locations'][8]['city']"
        assert humanize_diff_field(path) == "연구 기관 #9 · 도시"

    def test_lead_sponsor(self):
        assert (
            humanize_diff_field("sponsorCollaboratorsModule.leadSponsor.name")
            == "주관 기관"
        )

    def test_unknown_path_falls_back_to_prettified(self):
        result = humanize_diff_field("someUnknown.newFieldX")
        assert "New Field X" in result
        assert "[" not in result

    def test_empty_path(self):
        assert humanize_diff_field("") == ""


class TestHumanizeDiffValue:
    def test_status_enum_translation(self):
        assert humanize_diff_value("RECRUITING") == "모집 중 (RECRUITING)"
        assert humanize_diff_value("COMPLETED") == "완료 (COMPLETED)"

    def test_phase_translation(self):
        assert "2상" in humanize_diff_value("PHASE2")

    def test_dict_summarized_by_measure(self):
        raw = "{'measure': 'Overall Survival (OS)', 'timeFrame': 'Up to 6 years'}"
        assert humanize_diff_value(raw) == "Overall Survival (OS)"

    def test_truncated_dict_regex_fallback(self):
        raw = "{'measure': 'Objective Response Rate', 'description': '" + "x" * 2000
        assert humanize_diff_value(raw) == "Objective Response Rate"

    def test_list_joined(self):
        assert humanize_diff_value("['PHASE2', 'PHASE3']").startswith("2상")

    def test_long_scalar_truncated(self):
        result = humanize_diff_value("a" * 500, max_length=50)
        assert len(result) <= 51
        assert "…" in result

    def test_none_and_empty(self):
        assert humanize_diff_value(None) == ""
        assert humanize_diff_value("") == ""

    def test_plain_date_unchanged(self):
        assert humanize_diff_value("2025-11-24") == "2025-11-24"


class TestParseDiffRecords:
    def test_changed_record(self):
        recs = parse_diff_records(
            "Field `statusModule.overallStatus` changed from `RECRUITING` to `COMPLETED`"
        )
        assert recs == [
            {
                "kind": "changed",
                "field": "statusModule.overallStatus",
                "old": "RECRUITING",
                "new": "COMPLETED",
            }
        ]

    def test_added_and_removed_records(self):
        text = "New field added: `ipdSharingStatementModule`\nField removed: `whyStopped`"
        kinds = [(r["kind"], r["field"]) for r in parse_diff_records(text)]
        assert ("added", "ipdSharingStatementModule") in kinds
        assert ("removed", "whyStopped") in kinds

    def test_multiple_records_split_correctly(self):
        text = (
            "Field `a.b` changed from `1` to `2`\n"
            "Field `c.d` changed from `3` to `4`\n"
            "New field added: `e.f`"
        )
        recs = parse_diff_records(text)
        assert len(recs) == 3
        assert recs[0]["new"] == "2"
        assert recs[1]["old"] == "3"
        assert recs[2]["kind"] == "added"

    def test_multiline_values(self):
        text = "Field `desc` changed from `line1\nline2` to `line3\nline4`\nField `x` changed from `1` to `2`"
        recs = parse_diff_records(text)
        assert recs[0]["old"] == "line1\nline2"
        assert recs[0]["new"] == "line3\nline4"
        assert recs[1]["new"] == "2"

    def test_initial_data_collection_skipped(self):
        assert parse_diff_records("Initial data collection") == []

    def test_empty_text(self):
        assert parse_diff_records("") == []

    def test_unrecognized_line_is_raw(self):
        recs = parse_diff_records("Something unexpected happened")
        assert recs[0]["kind"] == "raw"


class TestRenderTrialHistoryBody:
    def _history(self):
        return [
            {"timestamp": "2026-02-05 15:10:46", "diff": "Initial data collection"},
            {
                "timestamp": "2026-05-26 02:38:40",
                "diff": (
                    "Field `statusModule.overallStatus` changed from "
                    "`RECRUITING` to `COMPLETED`\n"
                    "Field `statusModule.completionDateStruct.date` changed from "
                    "`2025-11-24` to `2025-11-14`"
                ),
            },
        ]

    def test_groups_by_timestamp_with_table(self):
        body = _render_trial_history_body(self._history(), "NCT00000000")
        assert "## 🕘 변경 이력 (1회)" in body
        assert "### 📅 2026-05-26 02:38 · 변경 2건" in body
        assert "| 모집 상태 |" in body
        assert "| 종료 예정일 | 2025-11-24 | 2025-11-14 |" in body

    def test_initial_collection_not_shown(self):
        body = _render_trial_history_body(self._history(), "NCT00000000")
        assert "Initial data collection" not in body

    def test_newest_first(self):
        history = self._history()
        history.append(
            {
                "timestamp": "2026-08-01 10:00:00",
                "diff": "Field `designModule.phases` changed from `PHASE1` to `PHASE2`",
            }
        )
        body = _render_trial_history_body(history, "NCT00000000")
        assert body.index("2026-08-01") < body.index("2026-05-26")

    def test_added_removed_rows(self):
        history = [
            {
                "timestamp": "2026-08-12 01:58:00",
                "diff": "New field added: `ipdSharingStatementModule`\nField removed: `whyStopped`",
            }
        ]
        body = _render_trial_history_body(history, "NCT00000000")
        assert "| ➕ | IPD 공유 계획 | - | 새로 추가됨 |" in body
        assert "| ➖ | IPD 공유 계획 | 삭제됨 | - |" not in body
        assert "| ➖ | 조기 종료 사유 | 삭제됨 | - |" in body
        assert "추가 1건" in body
        assert "삭제 1건" in body

    def test_no_events_message(self):
        history = [
            {"timestamp": "2026-02-05 15:10:46", "diff": "Initial data collection"}
        ]
        body = _render_trial_history_body(history, "NCT00000000")
        assert "변경 기록이 없습니다" in body

    def test_invalid_history(self):
        body = _render_trial_history_body(None, "NCT00000000")
        assert "변경 기록이 없습니다" in body


class TestFormatDiffCell:
    def test_empty_becomes_dash(self):
        assert _format_diff_cell("") == "-"
        assert _format_diff_cell(None) == "-"

    def test_escapes_pipes_for_markdown_tables(self):
        cell = _format_diff_cell("a|b")
        assert "|" not in cell.replace("&#124;", "")

    def test_long_value_gets_tooltip(self):
        value = "x" * 200
        cell = _format_diff_cell(value)
        assert "<span" in cell
        assert 'title="{}"'.format(value) in cell
        assert cell.rstrip("</span>").endswith("…")

    def test_multiline_tooltip_collapsed(self):
        cell = _format_diff_cell("line1\nline2\n" + "y" * 100)
        assert "\n" not in cell
