import os
import json
import yaml
from typing import Any, Dict, List
try:
    from utils import sanitize_id, escape_html
except ImportError:
    from src.utils import sanitize_id, escape_html


def load_trials_yaml(path: str = "trials.yaml") -> List[Dict[str, Any]]:
    """Load trials configuration from YAML file."""
    if not os.path.exists(path):
        return []

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
        raise ValueError(f"{path} must be a dictionary")

    if "targets" in data and isinstance(data["targets"], list):
        return data["targets"]

    return []


def discover_all_targets() -> List[Dict[str, Any]]:
    """Discover all targets from trials.yaml and data/targets directory."""
    targets_dict = {}

    # 1. Load from trials.yaml
    for t in load_trials_yaml():
        name = t["name"]
        targets_dict[name.lower()] = {
            "name": name,
            "description": t.get("description", f"{name} 타겟 임상시험 모니터링"),
        }

    # 2. Discover from data/targets directory
    targets_data_dir = "data/targets"
    if os.path.exists(targets_data_dir):
        for d in os.listdir(targets_data_dir):
            if d.lower() in targets_dict:
                continue

            summary_path = os.path.join(targets_data_dir, d, "status_summary.json")
            if os.path.exists(summary_path):
                try:
                    with open(summary_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data and isinstance(data, list):
                            name = data[0].get("target", d)
                            targets_dict[name.lower()] = {
                                "name": name,
                                "description": f"{name} 타겟 임상시험 모니터링",
                            }
                except Exception:
                    continue

    return list(targets_dict.values())


def generate_target_qmd(
    target_name: str, description: str, output_dir: str = "targets"
) -> str:
    """Generate a QMD file for a target."""
    os.makedirs(output_dir, exist_ok=True)

    target_id = sanitize_id(target_name).lower()
    qmd_path = os.path.join(output_dir, f"{target_id}.qmd")

    # Use yaml.safe_dump for frontmatter to prevent YAML injection
    safe_name = escape_html(target_name)
    frontmatter = {"title": safe_name}
    yaml_header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)

    safe_description = escape_html(description)
    header = f"---\n{yaml_header}---\n\n::: {{.callout-note}}\n{safe_description}\n:::\n"

    body = (
        r'''
## Visual Summary

::: {.panel-tabset}

### Status & Phase

```{python}
#| echo: false
#| warning: false
import pandas as pd
import plotly.express as px
import os
from src.utils import sanitize_id, get_status_badge, get_phase_badge, get_update_badge, escape_html, format_truncated_with_tooltip, format_enrollment

target_id = "'''
        + target_id
        + r'''"
csv_path = f"data/targets/{target_id}/all_trials_raw.csv"

if os.path.exists(csv_path):
    try:
        df = pd.read_csv(csv_path, on_bad_lines='skip')
    except Exception as e:
        print(f"Error reading CSV: {e}")
        df = pd.DataFrame()
    
    if 'status_overallStatus' in df.columns:
        status_counts = df['status_overallStatus'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        fig1 = px.bar(status_counts, x='Status', y='Count', 
                     title='Study Status Distribution', 
                     color='Status',
                     template='plotly_white')
        fig1.update_layout(showlegend=False)
        fig1.show()
else:
    df = pd.DataFrame()
    print("No data available yet.")
```

```{python}
#| echo: false
#| warning: false
if os.path.exists(csv_path):
    if 'design_phases' in df.columns:
        phase_df = df['design_phases'].dropna().astype(str).str.split(', ').explode()
        phase_counts = phase_df.value_counts().reset_index()
        phase_counts.columns = ['Phase', 'Count']
        fig2 = px.pie(phase_counts, names='Phase', values='Count', 
                     title='Trial Phase Distribution',
                     hole=0.4,
                     template='plotly_white')
        fig2.show()
```

### Top Sponsors

```{python}
#| echo: false
#| warning: false
if os.path.exists(csv_path):
    if 'sponsorCollaborators_leadSponsor_name' in df.columns:
        sponsor_counts = df['sponsorCollaborators_leadSponsor_name'].value_counts().reset_index().head(12)
        sponsor_counts.columns = ['Sponsor', 'Count']
        fig4 = px.bar(sponsor_counts, x='Count', y='Sponsor', 
                     title='Top Lead Sponsors (by Number of Trials)', 
                     orientation='h', 
                     color='Sponsor',
                     template='plotly_white')
        fig4.update_layout(yaxis={'categoryorder':'total ascending'}, showlegend=False)
        fig4.show()
```

:::

---

## Change History

::: {.panel-tabset}

### Target Milestones

```{python}
#| echo: false
#| output: asis
import json
import os
from src.utils import sanitize_id, escape_html

target_id = "'''
        + target_id
        + r'''"
target_h_file = f"data/history/target_{target_id}.json"

if os.path.exists(target_h_file):
    try:
        with open(target_h_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception as e:
        print(f"Error loading history: {e}")
        history = []
    
    print("")
    for record in reversed(history[-10:]):
        print(f'- **{escape_html(record["timestamp"])}**: {escape_html(record["event"])}')
else:
    print(f"No target-level milestones recorded yet for {target_id}.")
```

### Trial Changes

```{python}
#| echo: false
#| output: asis
import json
import os
from src.utils import sanitize_id, escape_html, format_diff_line_markdown

target_id = "'''
        + target_id
        + r'''"
summary_path = f"data/targets/{target_id}/status_summary.json"

# Get trial IDs for this target
target_trials = []
if os.path.exists(summary_path):
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            target_trials = [item['id'] for item in json.load(f)]
    except Exception:
        target_trials = []

history_found = False
for trial_id in target_trials:
    h_file = f"data/history/{trial_id}_history.json"
    if os.path.exists(h_file):
        try:
            with open(h_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            continue
        
        # Filter out "Initial data collection" to only show real changes
        real_changes = [r for r in history if r['diff'] != "Initial data collection"]
        
        if real_changes:
            if not history_found:
                history_found = True
            print("")
            print(f"#### {escape_html(trial_id)}")
            print("")
            for record in reversed(real_changes[-5:]):
                print(f'- **{escape_html(record["timestamp"])} (Trial Update)**')
                for line in record['diff'].splitlines():
                    line = line.strip()
                    if line:
                        formatted_line = format_diff_line_markdown(line)
                        print(f'    - {formatted_line}')
                print("")

if not history_found:
    print(f"No specific trial changes (beyond initial collection) recorded yet for {target_id}.")
```

:::

---

<a href="../data/targets/'''
        + target_id
        + r'''/all_trials_raw.csv" class="btn btn-primary" role="button" aria-label="Download all raw trial data for '''
        + safe_name
        + r''' in CSV format">📥 Download Full Data (CSV)</a>
<a href="../data/targets/'''
        + target_id
        + r'''/status_summary.csv" class="btn btn-outline-secondary" role="button" aria-label="Download status summary for '''
        + safe_name
        + r''' in CSV format">📥 Download Status Summary (CSV)</a>

---

## Monitoring Status

```{python}
#| echo: false
#| output: asis
import json
import os
from src.utils import sanitize_id, get_status_badge, get_phase_badge, get_update_badge, escape_html, format_truncated_with_tooltip, format_enrollment

target_id = "'''
        + target_id
        + r'''"
summary_path = f"data/targets/{target_id}/status_summary.json"

if os.path.exists(summary_path):
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except Exception as e:
        print(f"Error loading data: {e}")
        summary = []
    
    print("")
    print('<div style="font-size: 0.8em">')
    print("")
    print("| Trial ID | Sponsor | Update | Status | Conditions | Phases | Start | End | Enroll | Last Updated |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | ---:| --- |")
    for item in summary:
        update_badge = get_update_badge(item.get('monitor_status', 'No Change'), item.get('last_monitored_change'))
        status_badge = get_status_badge(item.get('status', 'N/A'))
        phase_badge = get_phase_badge(item.get('phases', 'N/A'))

        safe_sponsor = format_truncated_with_tooltip(item.get('sponsor', 'N/A'), 30)
        safe_conditions = format_truncated_with_tooltip(item.get('conditions', 'N/A'), 30)

        trial_id = item['id']
        safe_trial_id = sanitize_id(trial_id)
        escaped_trial_id = escape_html(trial_id)
        safe_enrollment = format_enrollment(item.get('enrollment', 'N/A'))
        print(f"| [{escaped_trial_id}](https://clinicaltrials.gov/study/{safe_trial_id}) | {safe_sponsor} | {update_badge} | {status_badge} | {safe_conditions} | {phase_badge} | {escape_html(item.get('study_start', 'N/A'))} | {escape_html(item.get('study_end', 'N/A'))} | {safe_enrollment} | {escape_html(item.get('last_updated', 'N/A'))} |")
    print("")
    print('</div>')
    print("")
else:
    print(f"No monitoring data available yet for {target_id} at {os.path.abspath(summary_path)}. Run the data collection script first.")
```
'''
    )

    with open(qmd_path, "w", encoding="utf-8") as f:
        f.write(header + body)

    print(f"Generated: {qmd_path}")
    return qmd_path


def generate_index_qmd(output_path: str = "index.qmd") -> None:
    """Generate the main index page with dynamic targets."""

    content = r"""---
title: "Clinical Trial Watch"
---

## Targets Overview

임상시험을 타겟별로 모니터링합니다.

```{python}
#| echo: false
#| output: asis
import json
import os
from src.utils import sanitize_id, get_changed_count_badge, escape_html

summary_path = "data/targets_summary.json"
targets_dir = "data/targets"
targets = []

# Try to gather data from individual target summaries for maximum accuracy
if os.path.exists(targets_dir):
    for d in os.listdir(targets_dir):
        t_summary_path = os.path.join(targets_dir, d, "status_summary.json")
        if os.path.exists(t_summary_path):
            try:
                with open(t_summary_path, "r", encoding="utf-8") as f:
                    trials = json.load(f)
                    if trials:
                        name = trials[0].get('target', d)
                        trial_count = len(trials)
                        changed_count = sum(1 for t in trials if t.get('monitor_status') == 'Changed')
                        
                        # Find description from targets_summary.json if available
                        desc = f"{name} 타겟 임상시험 모니터링"
                        targets.append({
                            'name': name,
                            'description': desc,
                            'trial_count': trial_count,
                            'changed_count': changed_count
                        })
            except Exception:
                continue

# If no data found in directories, fallback to global summary or config
if not targets and os.path.exists(summary_path):
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            targets = json.load(f)
    except Exception:
        targets = []

if targets:
    # Sort targets by name
    targets.sort(key=lambda x: x['name'])
    
    print("| Target | Description | Trials | Changed |")
    print("| --- | --- | ---:| ---:|")
    for target in targets:
        name = target['name']
        desc = target.get('description', '')
        target_id = sanitize_id(name).lower()
        link = f"targets/{target_id}.qmd"
        changed_badge = get_changed_count_badge(target['changed_count'])
        print(f"| [{escape_html(name)}]({link}) | {escape_html(desc)} | {target['trial_count']} | {changed_badge} |")
else:
    print("No summary data available yet. Showing targets from configuration:")
    print("")
    print("| Target | Description |")
    print("| --- | --- |")
    
    try:
        import yaml
        with open("trials.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            for target in config.get('targets', []):
                name = target['name']
                desc = target.get('description', f"{name} 타겟 임상시험 모니터링")
                target_id = sanitize_id(name).lower()
                print(f"| [{escape_html(name)}](targets/{target_id}.qmd) | {escape_html(desc)} |")
    except Exception as e:
        print(f"Error loading targets: {e}")
```
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Generated: {output_path}")


def update_quarto_yml(
    targets: List[Dict[str, Any]], quarto_path: str = "_quarto.yml"
) -> None:
    """Update _quarto.yml with navbar for all targets."""

    # Build navbar menu items safely
    menu = []
    for target in targets:
        target_name = target["name"]
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

    with open(quarto_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            config, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )

    print(f"Updated: {quarto_path}")


def main() -> None:
    # Discover all targets from trials.yaml AND data directory
    targets = discover_all_targets()

    if not targets:
        print("No targets found in trials.yaml or data/targets/")
        return

    print(f"Found {len(targets)} targets")

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

    print(f"\n✓ Generated/Updated {len(targets)} target pages and updated index.qmd")


if __name__ == "__main__":
    main()
