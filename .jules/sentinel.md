## 2025-05-14 - Python Code Injection in Quarto Templates
**Vulnerability:** The `generate_target_pages.py` script was directly embedding the `target_name` from `trials.yaml` into Python code blocks within generated `.qmd` files. This allowed for arbitrary Python code execution when Quarto rendered the website.
**Learning:** Even static site generators can be vulnerable to code injection if they support dynamic execution (like Quarto's Python blocks) and identifiers are not sanitized before being embedded in code.
**Prevention:** Always sanitize any user-provided or external identifiers that are used to generate code, scripts, or file paths. Use a whitelist of allowed characters (e.g., alphanumeric, dashes, underscores).

## 2026-05-26 - Restricting trials.yaml Modification
**Instruction / Rule:** Jules (the AI coding assistant) is strictly prohibited from modifying `trials.yaml` directly.
**Rationale:** `trials.yaml` stores the configuration and tracked list of clinical trials. Direct manual modification of trial data by the AI assistant can lead to inconsistencies, data corruption, or bypass of automation pipelines. All updates must go through automated discovery scripts (`src/auto_discover_trials.py`) or import tools.
