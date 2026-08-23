"""Generate Quarto dashboard pages for clinical trial monitoring."""

import json
import os
from typing import Any

import yaml

try:
    from utils import (
        atomic_write,
        check_file_size,
        escape_html,
        render_trial_history_body,
        sanitize_id,
    )
except ImportError:
    from src.utils import (
        atomic_write,
        check_file_size,
        escape_html,
        render_trial_history_body,
        sanitize_id,
    )

STATUS_COLORS = {
    "RECRUITING": "#198754",
    "ACTIVE_NOT_RECRUITING": "#0dcaf0",
    "ENROLLING_BY_INVITATION": "#20c997",
    "NOT_YET_RECRUITING": "#ffc107",
    "COMPLETED": "#6c757d",
    "SUSPENDED": "#dc3545",
    "TERMINATED": "#dc3545",
    "WITHDRAWN": "#dc3545",
    "NO_LONGER_AVAILABLE": "#adb5bd",
    "AVAILABLE": "#adb5bd",
    "UNKNOWN": "#ced4da",
}

STATUS_LABELS_KO = {
    "RECRUITING": "모집 중",
    "ACTIVE_NOT_RECRUITING": "진행 중(비모집)",
    "ENROLLING_BY_INVITATION": "초청 모집",
    "NOT_YET_RECRUITING": "모집 예정",
    "COMPLETED": "완료",
    "SUSPENDED": "중단",
    "TERMINATED": "조기종료",
    "WITHDRAWN": "철회",
    "UNKNOWN": "알 수 없음",
}

ACTIVE_STATUSES = {
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
}

STATUS_PRIORITY = {
    "RECRUITING": 0,
    "NOT_YET_RECRUITING": 1,
    "ENROLLING_BY_INVITATION": 2,
    "ACTIVE_NOT_RECRUITING": 3,
}


def load_trials_yaml(path: str = "trials.yaml") -> list[dict[str, Any]]:
    """Load trials configuration from YAML file."""
    if not os.path.exists(path):
        return []

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return []
    except (yaml.YAMLError, OSError) as e:
        print(f"Error: Failed to load trials YAML {path}: {e}")
        raise

    if data is None:
        return []

    if not isinstance(data, dict):
        print(f"Error: {path} is not a valid YAML dictionary.")
        raise TypeError(f"{path} must be a dictionary")

    if "targets" in data and isinstance(data["targets"], list):
        return data["targets"]

    return []


def discover_all_targets() -> list[dict[str, Any]]:
    """Discover all targets from trials.yaml and data/targets directory."""
    targets_dict = {}
    MAX_TARGETS = 100

    # 1. Load from trials.yaml
    for t in load_trials_yaml():
        # Security enhancement: Limit total number of targets to prevent DoS (CWE-400)
        if len(targets_dict) >= MAX_TARGETS:
            break

        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if not name:
            continue

        # Security enhancement: Use sanitized ID as key to prevent path collisions
        target_id = sanitize_id(name).lower()
        if target_id in targets_dict:
            continue

        targets_dict[target_id] = {
            "name": name,
            "description": t.get("description", f"{name} 타겟 임상시험 모니터링"),
        }

    # 2. Discover from data/targets directory
    targets_dir = "data/targets"
    if os.path.exists(targets_dir):
        try:
            entries = sorted(os.listdir(targets_dir))
        except OSError:
            entries = []

        for entry in entries:
            if len(targets_dict) >= MAX_TARGETS:
                break

            target_path = os.path.join(targets_dir, entry)
            if not os.path.isdir(target_path):
                continue

            dir_sanitized_id = sanitize_id(entry).lower()
            if dir_sanitized_id in targets_dict:
                continue

            summary_file = os.path.join(target_path, "status_summary.json")
            target_name = entry
            if os.path.exists(summary_file):
                try:
                    check_file_size(summary_file)
                    with open(summary_file, "r", encoding="utf-8") as f:
                        summary_data = json.load(f)
                    if isinstance(summary_data, list) and summary_data:
                        first_item = summary_data[0]
                        if isinstance(first_item, dict) and "target" in first_item:
                            raw_name = first_item["target"]
                            if raw_name:
                                target_name = raw_name[:255]
                except (OSError, json.JSONDecodeError, ValueError):
                    pass

            target_id = sanitize_id(target_name).lower()
            if target_id in targets_dict or dir_sanitized_id in targets_dict:
                continue

            targets_dict[target_id] = {
                "name": target_name,
                "description": f"{target_name} 타겟 임상시험 모니터링",
            }

    return list(targets_dict.values())


def _build_mini_bar(dist: dict[str, int], total: int) -> str:
    """Build an inline stacked status distribution bar (HTML)."""
    if total <= 0:
        return ""
    order = sorted(dist.items(), key=lambda kv: -kv[1])
    segments = []
    legend = []
    for status, count in order:
        pct = round(count / total * 100, 1)
        color = STATUS_COLORS.get(status, "#ced4da")
        label = STATUS_LABELS_KO.get(status, status.title())
        segments.append(
            f'<div style="width:{pct}%;background:{color}" '
            f'title="{escape_html(label)} {count}개 ({pct}%)"></div>'
        )
        legend.append(
            f'<span><span class="legend-dot" style="background:{color}"></span>'
            f"{escape_html(label)} {count}</span>"
        )
    return (
        '<div class="status-mini-bar">' + "".join(segments) + "</div>"
        '<div class="mini-bar-legend">' + "".join(legend) + "</div>"
    )


def generate_target_qmd(
    target_name: str, description: str, output_dir: str = "targets"
) -> str:
    """Generate a dashboard QMD page for a target."""
    os.makedirs(output_dir, exist_ok=True)

    target_id = sanitize_id(target_name).lower()
    qmd_path = os.path.join(output_dir, f"{target_id}.qmd")

    # Use yaml.safe_dump for frontmatter to prevent YAML injection
    safe_name = escape_html(target_name)
    frontmatter = {"title": safe_name}
    yaml_header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)

    safe_description = escape_html(description)
    header = (
        f'---\n{yaml_header}---\n\n::: {{.callout-note appearance="simple"}}\n'
        f"{safe_description}\n:::\n\n"
    )

    overview_block = (
        r"""
```{python}
#| echo: false
#| output: asis
import json
import os
from collections import Counter

from src.utils import (
    check_file_size,
    escape_html,
    format_enrollment,
    format_truncated_with_tooltip,
    get_phase_badge,
    get_status_badge,
    get_update_badge,
    sanitize_id,
)

target_id = "__TARGET_ID__"

STATUS_COLORS = """
        + repr(STATUS_COLORS)
        + r"""
ACTIVE_STATUSES = """
        + repr(sorted(ACTIVE_STATUSES))
        + r"""
PRIORITY = """
        + repr(STATUS_PRIORITY)
        + r"""

def _upper(v):
    return str(v or "").strip().upper()

rows = []
sp = f"data/targets/{target_id}/status_summary.json"
if os.path.exists(sp):
    try:
        check_file_size(sp)
        with open(sp, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            rows = [r for r in raw if isinstance(r, dict) and r.get("id")]
    except Exception:
        rows = []

active_rows = sorted(
    [r for r in rows if _upper(r.get("status")) in ACTIVE_STATUSES],
    key=lambda r: (PRIORITY.get(_upper(r.get("status")), 9), str(r.get("last_updated", "")), r["id"]),
)
done_rows = [r for r in rows if _upper(r.get("status")) in {"COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED"}]
changed_rows = sorted(
    [r for r in rows if r.get("monitor_status") == "Changed"],
    key=lambda r: str(r.get("last_monitored_change", "")),
    reverse=True,
)

n_total = len(rows)
n_recruiting = sum(1 for r in rows if _upper(r.get("status")) == "RECRUITING")
n_active = len(active_rows)
n_other_active = n_active - n_recruiting
n_done = len(done_rows)

kpis = [
    (n_total, "총 등록 임상", "#212529"),
    (n_recruiting, "🟢 모집 중", "#198754"),
    (n_other_active, "🔵 진행 중(비모집)", "#0aa2c0"),
    (n_done, "⚪ 완료/중단", "#6c757d"),
    (len(changed_rows), "⚡ 최근 변경 감지", "#dc3545"),
]
print('<div class="kpi-row">')
for val, label, color in kpis:
    print(
        f'<div class="kpi-card"><div class="kpi-value" style="color:{color}">{val}</div>'
        f'<div class="kpi-label">{label}</div></div>'
    )
print("</div>")
print("")
print(f"## 🟢 현재 진행 중인 임상 ({n_active}개)")
print("")
```

```{python}
#| echo: false
#| output: asis
print("")
if active_rows:
    print("| Trial ID | 상태 | 단계 | Sponsor | 시작일 | 종료 예정 | 인원 |")
    print("| --- | --- | --- | --- | --- | --- | ---:|")
    for item in active_rows:
        tid = sanitize_id(item["id"])
        etid = escape_html(item["id"])
        print(
            f"| [{etid}](https://clinicaltrials.gov/study/{tid}) "
            f"| {get_status_badge(item.get('status', 'N/A'))} "
            f"| {get_phase_badge(item.get('phases', 'N/A'))} "
            f"| {format_truncated_with_tooltip(item.get('sponsor', 'N/A'), 26)} "
            f"| {escape_html(item.get('study_start', '-'))} "
            f"| {escape_html(item.get('study_end', '-'))} "
            f"| {format_enrollment(item.get('enrollment', 'N/A'))} |"
        )
else:
    print("_현재 진행 중인 임상이 없습니다._")
print("")
```

## ⚡ 최근 변경 감지

```{python}
#| echo: false
#| output: asis
print("")
if changed_rows:
    print(f"_최근 모니터링 실행에서 **{len(changed_rows)}개** 임상의 변동이 감지되었습니다. 클릭하면 상세 변경 내역(Before/After)을 볼 수 있습니다._")
    print("")
    print("| Trial ID | 감지일 | 상태 | 단계 | Sponsor | 최근 업데이트 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for item in changed_rows[:50]:
        tid = sanitize_id(item["id"])
        etid = escape_html(item["id"])
        print(
            f"| [{etid}](../trials/{tid}.qmd) "
            f"| {escape_html(item.get('last_monitored_change', '-'))} "
            f"| {get_status_badge(item.get('status', 'N/A'))} "
            f"| {get_phase_badge(item.get('phases', 'N/A'))} "
            f"| {format_truncated_with_tooltip(item.get('sponsor', 'N/A'), 24)} "
            f"| {escape_html(item.get('last_updated', '-'))} |"
        )
else:
    print("_변경이 감지된 임상이 없습니다. 새로운 변동이 감지되면 이 섹션에 표시됩니다._")
print("")
```

::: {.panel-tabset}

### 일별 변경 로그

```{python}
#| echo: false
#| output: asis
import re

from src.utils import humanize_feed_event

target_h_file = f"data/history/target_{target_id}.json"
history = []
if os.path.exists(target_h_file):
    try:
        check_file_size(target_h_file)
        with open(target_h_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        history = []

if not isinstance(history, list):
    history = []
history = [r for r in history if isinstance(r, dict)]

print("")
if history:
    print('<div class="change-feed">')
    for record in reversed(history[-12:]):
        ts = escape_html(str(record.get("timestamp", "N/A"))[:16])
        event_str = escape_html(humanize_feed_event(str(record.get("event", "N/A"))))
        event_str = re.sub(
            r"(NCT\d+)",
            lambda m: f'<a href="../trials/{m.group(1)}.html">{m.group(1)}</a>',
            event_str,
        )
        print(f'<div class="change-feed-item"><span class="change-feed-time">{ts}</span><br>{event_str}</div>')
    print("</div>")
else:
    print("_기록된 일별 변경 로그가 없습니다._")
print("")
```

### 임상별 상세 변경내역

```{python}
#| echo: false
#| output: asis
from src.utils import (
    check_file_size,
    escape_html,
    render_history_sections,
    sanitize_id,
)

trial_ids = [item["id"] for item in rows]
history_found = False
print("")
for trial_id in trial_ids:
    h_file = f"data/history/{trial_id}_history.json"
    if not os.path.exists(h_file):
        continue
    try:
        check_file_size(h_file)
        with open(h_file, "r", encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        continue

    sections = render_history_sections(hist, max_events=5, heading_level=None)
    if sections:
        history_found = True
        print(
            f"#### [{escape_html(trial_id)}]"
            f"(https://clinicaltrials.gov/study/{sanitize_id(trial_id)})"
        )
        print("")
        print(sections)

if not history_found:
    print("_아직 초기 수집 이후의 개별 임상 변경내역이 없습니다._")
print("")
```

:::

```{python}
#| echo: false
#| output: asis
print(f"## 📋 전체 임상 목록 ({n_total}개)")
print("")
```

```{python}
#| echo: false
#| output: asis
all_rows = sorted(
    rows,
    key=lambda r: (PRIORITY.get(_upper(r.get("status")), 9), str(r.get("last_updated", ""))),
)
print("")
print('<div style="font-size: 0.82em">')
print("")
print("| Trial ID | Update | Status | Phases | Sponsor | Conditions | 시작일 | 종료 예정 | 인원 |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | ---:|")
for item in all_rows:
    tid = sanitize_id(item["id"])
    etid = escape_html(item["id"])
    print(
        f"| [{etid}](https://clinicaltrials.gov/study/{tid}) "
        f"| {get_update_badge(item.get('monitor_status', 'No Change'), item.get('last_monitored_change'))} "
        f"| {get_status_badge(item.get('status', 'N/A'))} "
        f"| {get_phase_badge(item.get('phases', 'N/A'))} "
        f"| {format_truncated_with_tooltip(item.get('sponsor', 'N/A'), 22)} "
        f"| {format_truncated_with_tooltip(item.get('conditions', 'N/A'), 26)} "
        f"| {escape_html(item.get('study_start', '-'))} "
        f"| {escape_html(item.get('study_end', '-'))} "
        f"| {format_enrollment(item.get('enrollment', 'N/A'))} |"
    )
print("")
print("</div>")
print("")
```

## 📊 현황 분포

::: {.panel-tabset}

### 모집 상태

```{python}
#| echo: false
#| warning: false
import pandas as pd
import plotly.express as px

if rows:
    df = pd.DataFrame(rows)
    if "status" in df.columns:
        sc = (
            df["status"].fillna("UNKNOWN").astype(str).str.upper().value_counts().reset_index()
        )
        sc.columns = ["Status", "Count"]
        fig = px.pie(
            sc, names="Status", values="Count", hole=0.45,
            color="Status", color_discrete_map=STATUS_COLORS,
            title="모집 상태 분포",
            template="plotly_white",
        )
        fig.show()
```

### 개발 단계

```{python}
#| echo: false
#| warning: false
if rows:
    df = pd.DataFrame(rows)
    if "phases" in df.columns:
        phase_df = df["phases"].dropna().astype(str).str.split(", ").explode()
        pc = phase_df.value_counts().reset_index()
        pc.columns = ["Phase", "Count"]
        fig = px.bar(
            pc, x="Phase", y="Count", color="Phase",
            title="임상 단계 분포", template="plotly_white",
        )
        fig.update_layout(showlegend=False)
        fig.show()
```

### 주요 스폰서

```{python}
#| echo: false
#| warning: false
if rows:
    df = pd.DataFrame(rows)
    if "sponsor" in df.columns:
        spc = df["sponsor"].fillna("(Unknown)").value_counts().head(10).reset_index()
        spc.columns = ["Sponsor", "Count"]
        fig = px.bar(
            spc, x="Count", y="Sponsor", orientation="h", color="Sponsor",
            title="주요 스폰서 TOP 10", template="plotly_white",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
        fig.show()
```

:::

---

<a href="../data/targets/__TARGET_ID__/all_trials_raw.csv" class="btn btn-primary" role="button" aria-label="Download all raw trial data CSV">📥 전체 데이터 다운로드 (CSV)</a>
<a href="../data/targets/__TARGET_ID__/status_summary.csv" class="btn btn-outline-secondary" role="button" aria-label="Download status summary CSV">📥 요약 데이터 다운로드 (CSV)</a>
"""
    )

    body = overview_block.replace("__TARGET_ID__", target_id)

    # Security enhancement: Use atomic write to prevent data corruption (CWE-459)
    with atomic_write(qmd_path, encoding="utf-8") as f:
        f.write(header + body)

    print(f"Generated: {qmd_path}")
    return qmd_path


def generate_index_qmd(output_path: str = "index.qmd") -> None:
    """Generate the dashboard home page with per-target overview cards."""

    content = (
        r"""---
title: "Clinical Trial Watch"
---

한 곳에서 타겟별 임상시험 현황과 변경사항을 확인하세요.

```{python}
#| echo: false
#| output: asis
import json
import os
import re
from collections import Counter

import yaml

from src.generate_target_pages import _build_mini_bar
from src.utils import (
    check_file_size,
    escape_html,
    humanize_feed_event,
    sanitize_id,
)

ACTIVE_STATUSES = """
        + repr(sorted(ACTIVE_STATUSES))
        + r"""
STATUS_COLORS = """
        + repr(STATUS_COLORS)
        + r"""
STATUS_LABELS = """
        + repr(STATUS_LABELS_KO)
        + r"""

valid_ids = {}
try:
    with open("trials.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
        for t in config.get("targets", []):
            if isinstance(t, dict) and t.get("name"):
                sid = sanitize_id(t["name"]).lower()
                valid_ids[sid] = t["name"]
except Exception:
    pass

targets_data = []
targets_dir = "data/targets"
if os.path.isdir(targets_dir):
    for d in sorted(os.listdir(targets_dir)):
        if valid_ids and d.lower() not in valid_ids:
            continue
        spath = os.path.join(targets_dir, d, "status_summary.json")
        if not os.path.exists(spath):
            continue
        try:
            check_file_size(spath)
            with open(spath, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        rows = [r for r in raw if isinstance(r, dict) and r.get("id")]
        if not rows:
            continue

        dist = Counter(str(r.get("status", "")).strip().upper() for r in rows if r.get("status"))
        changed = sum(1 for r in rows if r.get("monitor_status") == "Changed")
        name = valid_ids.get(d.lower()) or d
        targets_data.append({
            "id": d.lower(),
            "name": name,
            "total": len(rows),
            "recruiting": dist.get("RECRUITING", 0),
            "ongoing": sum(cnt for s, cnt in dist.items() if s in set(ACTIVE_STATUSES)),
            "changed": changed,
            "dist": dist,
        })

targets_data.sort(key=lambda x: x["name"])

grand_total = sum(t["total"] for t in targets_data)
grand_recruiting = sum(t["recruiting"] for t in targets_data)
grand_changed = sum(t["changed"] for t in targets_data)

print('<div class="kpi-row">')
for val, label, color in [
    (len(targets_data), "추적 타겟", "#212529"),
    (grand_total, "총 임상", "#212529"),
    (grand_recruiting, "🟢 모집 중", "#198754"),
    (grand_changed, "⚡ 변경 감지", "#dc3545"),
]:
    print(
        f'<div class="kpi-card"><div class="kpi-value" style="color:{color}">{val}</div>'
        f'<div class="kpi-label">{label}</div></div>'
    )
print("</div>")
print("")

print('<div class="target-grid">')
for t in targets_data:
    badge = f' <span class="badge text-bg-danger">변경 {t["changed"]}</span>' if t["changed"] else ""
    bar = _build_mini_bar(dict(t["dist"]), t["total"])
    print("<div class='target-card'>")
    print(f'<h3><a href="targets/{t["id"]}.html">{escape_html(t["name"])}</a>{badge}</h3>')
    print(
        f'<div class="target-stats">'
        f'<span class="target-stat"><b>{t["total"]}</b><small>총 임상</small></span>'
        f'<span class="target-stat"><b style="color:#198754">{t["recruiting"]}</b><small>모집 중</small></span>'
        f'<span class="target-stat"><b style="color:#0aa2c0">{t["ongoing"]}</b><small>진행 중</small></span>'
        f"</div>"
    )
    print(bar)
    print("</div>")
print("</div>")
print("")

# Merged recent changes feed across all targets
feed = []
hist_dir = "data/history"
if os.path.isdir(hist_dir):
    for fn in sorted(os.listdir(hist_dir)):
        if not (fn.startswith("target_") and fn.endswith(".json")):
            continue
        tid = fn[len("target_"):-len(".json")]
        tname = valid_ids.get(tid) or tid.upper()
        fpath = os.path.join(hist_dir, fn)
        try:
            check_file_size(fpath)
            with open(fpath, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            continue
        if isinstance(records, list):
            for r in records:
                if isinstance(r, dict):
                    feed.append((str(r.get("timestamp", "")), tname, tid, str(r.get("event", ""))))

feed.sort(key=lambda x: x[0], reverse=True)
print("## 🕘 최근 변경사항")
print("")
if feed:
    print('<div class="change-feed">')
    for ts, tname, tid, event in feed[:15]:
        ev = escape_html(humanize_feed_event(event))
        ev = re.sub(
            r"(NCT\d+)",
            lambda m: f'<a href="trials/{m.group(1)}.html">{m.group(1)}</a>',
            ev,
        )
        print(
            f'<div class="change-feed-item">'
            f'<span class="badge text-bg-secondary">{escape_html(tname)}</span> '
            f'<span class="change-feed-time">{escape_html(ts[:16])}</span><br>{ev}</div>'
        )
    print("</div>")
else:
    print("_아직 기록된 변경사항이 없습니다._")
```
"""
    )

    # Security enhancement: Use atomic write to prevent data corruption (CWE-459)
    with atomic_write(output_path, encoding="utf-8") as f:
        f.write(content)

    print(f"Generated: {output_path}")


def update_quarto_yml(
    targets: list[dict[str, Any]], quarto_path: str = "_quarto.yml"
) -> None:
    """Update _quarto.yml with navbar for all targets."""

    # Build navbar menu items safely
    menu = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_name = target.get("name")
        if not target_name:
            continue
        target_id = sanitize_id(target_name).lower()
        menu.append(
            {"href": f"targets/{target_id}.qmd", "text": escape_html(target_name)}
        )

    config = {
        "project": {"type": "website", "output-dir": "docs", "execute-dir": "project"},
        "website": {
            "title": "Clinical Trial Watch",
            "navbar": {
                "left": [
                    {"href": "index.qmd", "text": "Home"},
                    {"text": "Targets", "menu": menu},
                    "about.qmd",
                ]
            },
        },
        "format": {
            "html": {
                "link-external-icon": True,
                "link-external-newwindow": True,
                "theme": ["cosmo", "brand"],
                "css": "styles.css",
                "toc": True,
            }
        },
        "execute": {"freeze": "auto"},
    }

    # Security enhancement: Use atomic write to prevent data corruption (CWE-459)
    with atomic_write(quarto_path, encoding="utf-8") as f:
        yaml.safe_dump(
            config, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )

    print(f"Updated: {quarto_path}")


def generate_all_trial_pages(
    history_dir: str = "data/history", output_dir: str = "trials"
) -> None:
    """Generate a QMD file for each trial's history with a current-status header."""
    if not os.path.exists(history_dir):
        return

    os.makedirs(output_dir, exist_ok=True)

    # Build a lookup of current trial info from all target summaries
    current_info: dict[str, dict[str, Any]] = {}
    targets_dir = "data/targets"
    if os.path.isdir(targets_dir):
        for entry in sorted(os.listdir(targets_dir)):
            spath = os.path.join(targets_dir, entry, "status_summary.json")
            if not os.path.exists(spath):
                continue
            try:
                check_file_size(spath)
                with open(spath, "r", encoding="utf-8") as f:
                    rows = json.load(f)
                if isinstance(rows, list):
                    for r in rows:
                        if isinstance(r, dict) and r.get("id"):
                            current_info[r["id"]] = r
            except (OSError, json.JSONDecodeError, ValueError):
                continue

    # Security enhancement: Explicitly sort directory listing for deterministic behavior
    try:
        items = sorted(os.listdir(history_dir))
    except OSError:
        items = []

    count = 0
    for filename in items:
        if filename.startswith("NCT") and filename.endswith("_history.json"):
            trial_id = filename.replace("_history.json", "")
            qmd_path = os.path.join(output_dir, f"{trial_id}.qmd")
            history_file = os.path.join(history_dir, filename)

            header = f'---\ntitle: "{trial_id} 변경 이력"\n---\n\n'

            # Current status header
            info = current_info.get(trial_id)
            if info:
                try:
                    from utils import (
                        format_enrollment,
                        get_phase_badge,
                        get_status_badge,
                        get_update_badge,
                    )
                except ImportError:
                    from src.utils import (
                        format_enrollment,
                        get_phase_badge,
                        get_status_badge,
                        get_update_badge,
                    )

                gov_link = f"https://clinicaltrials.gov/study/{trial_id}"
                header += (
                    f"{get_status_badge(info.get('status', 'N/A'))} "
                    f"{get_phase_badge(info.get('phases', 'N/A'))} "
                    f"{get_update_badge(info.get('monitor_status', 'No Change'), info.get('last_monitored_change'))}\n\n"
                    f"**Sponsor**: {escape_html(info.get('sponsor', 'N/A'))} · "
                    f"**모집 인원**: {format_enrollment(info.get('enrollment', 'N/A'))} · "
                    f"**기간**: {escape_html(info.get('study_start', '-'))} ~ {escape_html(info.get('study_end', '-'))}\n\n"
                    f"[ClinicalTrials.gov에서 보기]({gov_link}){{.btn .btn-outline-primary .btn-sm}}\n\n"
                )

            body = ""
            if os.path.exists(history_file):
                try:
                    check_file_size(history_file)
                    with open(history_file, "r", encoding="utf-8") as f:
                        history = json.load(f)
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    body = f"Error loading history: {e}"
                    history = []

                body = render_trial_history_body(history, trial_id)
            else:
                body = f"No history file found for {trial_id}."

            # Security enhancement: Use atomic write to prevent data corruption (CWE-459)
            with atomic_write(qmd_path, encoding="utf-8") as f:
                f.write(header + body + "\n")

            count += 1

    print(f"Generated {count} trial history pages in {output_dir}/")


def main() -> None:
    # Discover all targets from trials.yaml
    targets = discover_all_targets()

    if not targets:
        print("No targets found in trials.yaml")
        return

    print(f"Found {len(targets)} targets")

    # Get valid target IDs
    valid_ids = {sanitize_id(t["name"]).lower() for t in targets}

    output_dir = "targets"
    if os.path.exists(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith(".qmd"):
                tid = f[:-4]
                if tid not in valid_ids:
                    print(f"Removing obsolete page: {f}")
                    try:
                        os.remove(os.path.join(output_dir, f))
                    except OSError as e:
                        print(f"Error removing {f}: {e}")

    # Generate QMD pages for all targets
    for target in targets:
        generate_target_qmd(
            target["name"],
            target.get("description", f"{target['name']} 타겟 임상시험 모니터링"),
        )

    # Update index.qmd (now uses dynamic discovery internally)
    generate_index_qmd()

    # Update _quarto.yml with all discovered targets
    update_quarto_yml(targets)

    # Generate individual trial pages
    generate_all_trial_pages()

    print(
        f"\n✓ Generated/Updated {len(targets)} target pages, trial pages, and updated index.qmd"
    )


if __name__ == "__main__":
    main()
