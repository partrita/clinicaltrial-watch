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

## 2026-06-04 - Inconsistent String Truncation DoS (CWE-400)
**Vulnerability:** The `flatten_dict` function truncated strings aggregated from lists but failed to truncate individual scalar string values. This allowed excessively large strings from the API to consume significant memory and CPU during flattening and CSV generation.
**Learning:** Partial application of resource limits leaves gaps that can still lead to exhaustion. Security controls must be applied consistently across all data types in a transformation pipeline.
**Prevention:** Enforce a global maximum value length (`MAX_VALUE_LENGTH`) for all string outputs in data transformation functions, ensuring both scalar and list-derived values are capped.

## 2026-06-12 - Recursive Comparison DoS in DeepDiff (CWE-400)
**Vulnerability:** The `compare_snapshots` function used `DeepDiff` without a recursion depth limit. A maliciously crafted or extremely deep JSON structure could cause excessive CPU consumption or a `RecursionError` during the comparison process.
**Learning:** While `DeepDiff` is a robust tool, it still relies on recursion. Without a specified `max_depth` (or equivalent callback-based pruning), it is vulnerable to resource exhaustion from deeply nested structures.
**Prevention:** Always enforce a maximum depth (`MAX_DEPTH`) when using recursive comparison or hashing tools on untrusted data. Since some versions of `DeepDiff` may not support a native `max_depth` parameter, use `exclude_obj_callback` to prune traversal at a safe depth.

## 2026-06-15 - CSV Formula Injection Bypass via Invisible Unicode Characters
**Vulnerability:** The `sanitize_csv_value` function used a whitelist of whitespace and invisible characters to strip before checking for dangerous formula prefixes. However, it lacked coverage for Mongolian Free Variation Selectors, Unicode Tag Characters, and C1 control characters, which can be used to obfuscate formula triggers (e.g., `=`) in spreadsheet applications.
**Learning:** Spreadsheet parsers are often overly permissive and ignore a wide range of non-printing Unicode characters at the start of a cell. Security controls must account for these "invisible" bypasses by using a comprehensive stripping regex.
**Prevention:** When sanitizing for CSV injection, explicitly strip all known control characters, variation selectors, and non-rendering Unicode symbols from the beginning of the string before evaluating it for dangerous prefixes.

## 2026-06-20 - Non-Atomic File Writes (CWE-459)
**Vulnerability:** The application extensively updated critical JSON and YAML data files (configuration, trial history, snapshots) using standard `open(..., "w")` calls. An interruption during the write process (e.g., power failure, crash, or disk full) could leave these files in a truncated or corrupted state, leading to data loss or application failure.
**Learning:** Standard file write operations are not atomic. In applications that rely heavily on local file-based persistence for state and configuration, partial writes pose a significant risk to data integrity and system availability.
**Prevention:** Always use an atomic write pattern—writing to a temporary file in the same filesystem and then performing an atomic rename (`os.replace`)—for all critical data persistence. Implement this as a reusable context manager (`atomic_write`) to ensure consistency across the codebase.

## 2026-06-25 - Insecure Default TLS Versions in Requests
**Vulnerability:** The `requests` library, by default, relies on the underlying system's OpenSSL configuration, which may allow the negotiation of deprecated and insecure TLS versions (like 1.0 or 1.1) if not explicitly restricted.
**Learning:** Hardening HTTP clients requires more than just setting timeouts and redirect limits; it must also include explicit enforcement of modern cryptographic protocols. This is achieved in `requests` by overriding the `PoolManager` and `ProxyManager` in a custom `HTTPAdapter`.
**Prevention:** Always implement a custom `TLSAdapter` that configures a secure `SSLContext` (e.g., `minimum_version = ssl.TLSVersion.TLSv1_2`) and mount it to the `https://` prefix of all `requests.Session` objects.
