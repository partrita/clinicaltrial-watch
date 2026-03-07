import os
import yaml
import json

def load_trials_yaml(path="trials.yaml"):
    """Load trials configuration from YAML file."""
    if not os.path.exists(path):
        return []
    
    with open(path, "r", encoding="utf-8") as f:
        # Use a more robust way to load if it's very large or has special tags
        try:
            data = yaml.safe_load(f)
            if data and 'targets' in data:
                return data['targets']
        except Exception:
            # Fallback to simple parsing if yaml fails
            pass

    # Simple fallback parser for trials.yaml
    data = {'targets': []}
    with open(path, "r", encoding="utf-8") as f:
        current_target = None
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- name:"):
                if current_target:
                    data['targets'].append(current_target)
                current_target = {
                    'name': stripped.split(":", 1)[1].strip().strip('"').strip("'"),
                    'trials': []
                }
            elif stripped.startswith("description:") and current_target:
                current_target['description'] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        if current_target:
            data['targets'].append(current_target)
    
    return data.get('targets', [])

def generate_target_qmd(target_name, description, output_dir="targets"):
    """Generate a QMD file for a target."""
    os.makedirs(output_dir, exist_ok=True)
    
    safe_target_name = sanitize_id(target_name)
    target_lower = safe_target_name.lower()
    qmd_path = os.path.join(output_dir, f"{target_lower}.qmd")
    
    # Using a literal string for most of the content to avoid f-string brace hell
    header = f'---\ntitle: "{target_name}"\n---\n\n::: {{.callout-note}}\n{description}\n:::\n'

    body = r'''
## Visual Summary

::: {.panel-tabset}

### Status & Phase

```{python}
#| echo: false
#| warning: false
import pandas as pd
import plotly.express as px
import os
from utils import sanitize_id

target_name = "''' + target_lower + r'''"
csv_path = f"data/targets/{target_name}/all_trials_raw.csv"

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
from utils import sanitize_id

target_name = "''' + target_lower + r'''"
target_h_file = f"data/history/target_{target_name}.json"

if os.path.exists(target_h_file):
    try:
        with open(target_h_file, "r") as f:
            history = json.load(f)
    except Exception as e:
        print(f"Error loading history: {e}")
        history = []
    
    for record in reversed(history[-10:]):
        print(f"**Date:** {record['timestamp']}")
        print(f"\n{record['event']}\n")
        print("***")
else:
    print(f"No target-level milestones recorded yet for {target_name}.")
```

### Trial Changes

```{python}
#| echo: false
#| output: asis
import json
import os
from utils import sanitize_id

target_name = "''' + target_lower + r'''"
summary_path = f"data/targets/{target_name}/status_summary.json"

# Get trial IDs for this target
target_trials = []
if os.path.exists(summary_path):
    try:
        with open(summary_path, "r") as f:
            target_trials = [item['id'] for item in json.load(f)]
    except Exception:
        target_trials = []

history_found = False
for trial_id in target_trials:
    h_file = f"data/history/{trial_id}_history.json"
    if os.path.exists(h_file):
        try:
            with open(h_file, "r") as f:
                history = json.load(f)
        except Exception:
            continue
        
        # Filter out "Initial data collection" to only show real changes
        real_changes = [r for r in history if r['diff'] != "Initial data collection"]
        
        if real_changes:
            if not history_found:
                history_found = True
            print(f"#### {trial_id}")
            for record in reversed(real_changes[-5:]):
                print(f"**Date:** {record['timestamp']}")
                print(f"\n{record['diff']}\n")
                print("***")

if not history_found:
    print(f"No specific trial changes (beyond initial collection) recorded yet for {target_name}.")
```

:::

---

<a href="../data/targets/''' + target_lower + r'''/all_trials_raw.csv" class="btn btn-primary" role="button">📥 Download Full Data (CSV)</a>
<a href="../data/targets/''' + target_lower + r'''/status_summary.csv" class="btn btn-outline-secondary" role="button">📥 Download Status Summary (CSV)</a>

---

## Monitoring Status

```{python}
#| echo: false
#| output: asis
import json
import os
from utils import sanitize_id

target_name = "''' + target_lower + r'''"
summary_path = f"data/targets/{target_name}/status_summary.json"

if os.path.exists(summary_path):
    try:
        with open(summary_path, "r") as f:
            summary = json.load(f)
    except Exception as e:
        print(f"Error loading data: {e}")
        summary = []
    
    print("| Trial ID | Sponsor | Update | Status | Conditions | Phases | Start | End | Enroll | Last Updated |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in summary:
        update_color = "🟢" if item.get('monitor_status') == "No Change" else "🔴"
        status = item.get('status', 'N/A')
        status_map = {
            'RECRUITING': 'success',
            'ACTIVE_NOT_RECRUITING': 'info',
            'COMPLETED': 'secondary',
            'NOT_YET_RECRUITING': 'warning',
            'SUSPENDED': 'danger',
            'TERMINATED': 'danger',
            'WITHDRAWN': 'danger'
        }
        badge_class = status_map.get(status, 'light text-dark')
        status_badge = f'<span class="badge bg-{badge_class}">{status}</span>'
        print(f"| [{item['id']}](https://clinicaltrials.gov/study/{item['id']}) | {item.get('sponsor', 'N/A')} | {update_color} {item.get('monitor_status')} | {status_badge} | {item.get('conditions', 'N/A')} | {item.get('phases', 'N/A')} | {item.get('study_start', 'N/A')} | {item.get('study_end', 'N/A')} | {item.get('enrollment', 'N/A')} | {item.get('last_updated', 'N/A')} |")
else:
    print(f"No monitoring data available yet for {target_name} at {os.path.abspath(summary_path)}. Run the data collection script first.")
```
'''
    
    with open(qmd_path, 'w', encoding='utf-8') as f:
        f.write(header + body)
    
    print(f"Generated: {qmd_path}")
    return qmd_path

def generate_index_qmd(output_path="index.qmd"):
    """Generate the main index page with dynamic targets."""
    
    content = r'''---
title: "Clinical Trial Watch"
---

## Targets Overview

임상시험을 타겟별로 모니터링합니다.

```{python}
#| echo: false
#| output: asis
import json
import os
from utils import sanitize_id

summary_path = "data/targets_summary.json"

if os.path.exists(summary_path):
    try:
        with open(summary_path, "r") as f:
            targets = json.load(f)
    except Exception as e:
        print(f"Error loading summary: {e}")
        targets = []
    
    print("| Target | Description | Trials | Changed |")
    print("| --- | --- | --- | --- |")
    for target in targets:
        name = target['name']
        link = f"targets/{name.lower()}.qmd"
        changed_badge = f"🔴 {target['changed_count']}" if target['changed_count'] > 0 else "🟢 0"
        print(f"| [{name}]({link}) | {target.get('description', '')} | {target['trial_count']} | {changed_badge} |")
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
                print(f"| [{name}](targets/{name.lower()}.qmd) | {desc} |")
    except Exception as e:
        print(f"Error loading targets: {e}")
```
'''
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Generated: {output_path}")

def update_quarto_yml(targets, quarto_path="_quarto.yml"):
    """Update _quarto.yml with navbar for all targets."""
    
    # Build navbar menu items
    menu_items = []
    for target in targets:
        target_name = target['name']
        safe_target_name = sanitize_id(target_name)
        target_lower = safe_target_name.lower()
        menu_items.append(f"          - href: targets/{target_lower}.qmd\n            text: {target_name}")
    
    menu_str = "\n".join(menu_items)
    
    content = f'''project:
  type: website
  output-dir: docs
  execute-dir: project

website:
  title: "Clinical Trial Watch"
  navbar:
    left:
      - href: index.qmd
        text: Home
      - text: Targets
        menu:
{menu_str}
      - about.qmd

format:
  html:
    theme:
      - cosmo
      - brand
    css: styles.css
    toc: true

execute:
  freeze: auto
'''
    
    with open(quarto_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Updated: {quarto_path}")

def main():
    # Load targets
    targets = load_trials_yaml()
    
    if not targets:
        print("No targets found in trials.yaml")
        return
    
    print(f"Found {len(targets)} targets")
    
    # Generate QMD pages
    for target in targets:
        generate_target_qmd(
            target['name'],
            target.get('description', f"{target['name']} 타겟 임상시험 모니터링")
        )
    
    # Update index.qmd
    generate_index_qmd()
    
    # Update _quarto.yml
    update_quarto_yml(targets)
    
    print(f"\n✓ Generated {len(targets)} target pages and updated index.qmd")

if __name__ == "__main__":
    main()
