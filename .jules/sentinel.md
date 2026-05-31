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

## 2026-05-31 - Regular File Enforcement for DoS Protection (CWE-400)
**Vulnerability:** The `check_file_size` utility verified the size of regular files but did not explicitly reject non-regular files (such as character devices or directories). This could allow an attacker to point the application to a special device like `/dev/zero`, potentially causing hangs or infinite resource consumption during subsequent read operations.
**Learning:** Checking the size of a file is insufficient if the file type itself is not validated. Special files in Unix-like systems can behave unexpectedly when opened as regular files.
**Prevention:** Always verify that a path refers to a regular file (`os.path.isfile`) before performing I/O operations in a security-sensitive context. Raise explicit exceptions if the path exists but is not the expected type.
