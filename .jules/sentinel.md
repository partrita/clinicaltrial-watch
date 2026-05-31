## 2026-05-29 - Recursive Data Exhaustion DoS (CWE-400)
**Vulnerability:** The `flatten_dict` function, while using an iterative approach to avoid stack overflows, did not have a limit on the depth of the nesting it would process. A maliciously crafted or extremely large nested dictionary could cause excessive CPU and memory consumption.
**Learning:** Iterative solutions protect against stack overflows but do not inherently prevent resource exhaustion. Explicit depth limits are necessary when processing untrusted nested structures.
**Prevention:** Always enforce a maximum depth (`MAX_DEPTH`) when traversing or flattening nested data structures, even when using iterative patterns.

## 2025-05-14 - Python Code Injection in Quarto Templates
**Vulnerability:** The `generate_target_pages.py` script was directly embedding the `target_name` from `trials.yaml` into Python code blocks within generated `.qmd` files. This allowed for arbitrary Python code execution when Quarto rendered the website.
**Learning:** Even static site generators can be vulnerable to code injection if they support dynamic execution (like Quarto's Python blocks) and identifiers are not sanitized before being embedded in code.
**Prevention:** Always sanitize any user-provided or external identifiers that are used to generate code, scripts, or file paths. Use a whitelist of allowed characters (e.g., alphanumeric, dashes, underscores).

## 2026-05-26 - Restricting trials.yaml Modification
**Instruction / Rule:** Jules (the AI coding assistant) is strictly prohibited from modifying `trials.yaml` directly.
**Rationale:** `trials.yaml` stores the configuration and tracked list of clinical trials. Direct manual modification of trial data by the AI assistant can lead to inconsistencies, data corruption, or bypass of automation pipelines. All updates must go through automated discovery scripts (`src/auto_discover_trials.py`) or import tools.

## 2026-06-03 - Non-Regular File Access DoS (CWE-400)
**Vulnerability:** The `check_file_size` utility previously only checked `os.path.isfile(filepath)` before getting the size. This allowed non-regular files like directories or character devices (e.g., `/dev/zero`) to bypass the size check in certain contexts or cause the application to hang when attempting to read from them.
**Learning:** Checking for file existence or just `isfile` is not always sufficient if the logic later expects a regular data file. Character devices or directories can cause `open()` or `read()` to hang or behave unexpectedly.
**Prevention:** Use `os.path.isfile()` strictly or explicitly check for regular files before performing I/O operations on untrusted paths. Hardened `check_file_size` to raise `ValueError` for non-regular files.
