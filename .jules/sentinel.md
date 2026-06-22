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

## 2026-07-02 - Memory Exhaustion during List Joining (CWE-400)
**Vulnerability:** The `flatten_dict` function previously joined lists into a single string using `", ".join()` before truncating the result to `MAX_VALUE_LENGTH`. Since individual list items from the API could be up to 10MB each, joining a large list could create a massive intermediate string in memory, leading to an Out-of-Memory (OOM) Denial of Service.
**Learning:** Truncating the *result* of an operation is insufficient if the operation itself consumes excessive resources. Resource limits must be applied *during* the generation of large data structures.
**Prevention:** Build large strings or JSON representations from collections incrementally. Check the aggregate length at each step and terminate the process as soon as the defined safety limit is reached, avoiding the creation of large intermediate objects.

## 2026-06-25 - Insecure Default TLS Versions in Requests
**Vulnerability:** The `requests` library, by default, relies on the underlying system's OpenSSL configuration, which may allow the negotiation of deprecated and insecure TLS versions (like 1.0 or 1.1) if not explicitly restricted.
**Learning:** Hardening HTTP clients requires more than just setting timeouts and redirect limits; it must also include explicit enforcement of modern cryptographic protocols. This is achieved in `requests` by overriding the `PoolManager` and `ProxyManager` in a custom `HTTPAdapter`.
**Prevention:** Always implement a custom `TLSAdapter` that configures a secure `SSLContext` (e.g., `minimum_version = ssl.TLSVersion.TLSv1_2`) and mount it to the `https://` prefix of all `requests.Session` objects.

## 2025-05-24 - Centralized Security-Hardened HTTP Sessions
**Vulnerability:** Security configurations for HTTP sessions (TLS enforcement, redirect limits, proxy avoidance) were duplicated across multiple modules (`crawler.py`, `auto_discover_trials.py`). This led to maintenance overhead and increased the risk of inconsistent security policies if one module was updated while others were forgotten.
**Learning:** Duplicating security-critical code across a project creates "security debt" and potential gaps. Centralizing these controls into a reusable factory ensures a consistent security posture and simplifies global policy updates.
**Prevention:** Use a centralized factory function (`create_safe_session` in `src/utils.py`) to instantiate and configure all network clients. This function should encapsulate TLS hardening, redirect limits (CWE-606), and environment isolation (CWE-918) as a single, auditable unit.

## 2025-06-14 - Enforcing HTTPS-Only Sessions at the Adapter Level
**Vulnerability:** While an application may use HTTPS URLs by default, attackers or compromised servers can use 3xx redirects to downgrade the connection to insecure HTTP. Relying on application-level URL parsing to prevent this is error-prone.
**Learning:** In the `requests` library, session-level protocol enforcement is most robustly achieved by mounting a custom `BlockedAdapter` to the `http://` prefix. This intercepts any attempt to use the insecure protocol, including those originating from redirects, before any network communication occurs.
**Prevention:** For security-critical HTTP clients, explicitly replace the default `HTTPAdapter` for the `http://` schema with a blocking adapter that raises an exception. This provides a fail-secure baseline that prevents protocol downgrade attacks and accidental cleartext data transmission.

## 2025-05-24 - Metadata Field Resource Exhaustion (CWE-400)
**Vulnerability:** Metadata fields extracted from the ClinicalTrials.gov API (such as trial names, sponsor names, and primary outcomes) were not truncated before being included in the trial report object. A malicious or malformed API response containing extremely large strings in these fields could lead to excessive memory consumption, large data files, and performance degradation during website generation.
**Learning:** Security hardening must be applied to all data paths, including seemingly low-risk metadata fields. Even if large fields like descriptions are already capped, many smaller fields can collectively cause resource exhaustion if not bounded.
**Prevention:** Enforce strict length limits on all external data fields before they are processed or persisted. Use a centralized or consistent truncation strategy (e.g., 255-1000 characters) for all metadata to ensure system stability and predictability.

## 2026-06-16 - Target ID Collision and Resource Exhaustion in Discovery (CWE-400)
**Vulnerability:** The `discover_all_targets` function used simple lowercasing for its deduplication keys while the downstream `generate_target_qmd` used `sanitize_id(name).lower()` for filenames. This allowed targets with different names that resolve to the same sanitized ID (e.g., "Target A" and "Target!A") to both be "discovered", leading to overwriting of generated files and inconsistent website state. Additionally, resource limits were inconsistently applied between YAML and filesystem discovery.
**Learning:** Security transformations used for path generation must be mirrored in the discovery and deduplication logic. Inconsistent key generation between these phases creates "blind spots" where collisions can bypass deduplication.
**Prevention:** Always use the exact same sanitization and normalization logic for discovery keys as is used for persistent identifiers (filenames, URLs). Enforce global resource limits (e.g., `MAX_TARGETS`) strictly and consistently across all input sources during the discovery phase.

## 2026-07-28 - Recursion-based DoS in List Serialization (CWE-400)
**Vulnerability:** The `flatten_dict` function, while itself iterative, delegated the serialization of list items to the built-in `str()` and `json.dumps()` functions. If a list contained a deeply nested object, these calls could trigger a `RecursionError`, crashing the application and causing a Denial of Service.
**Learning:** Even iterative algorithms can be vulnerable to recursion-based crashes if they rely on recursive primitives (like standard serialization tools) to process individual elements of a collection. Security boundaries must be enforced at every layer of data transformation.
**Prevention:** Wrap serialization of untrusted or potentially complex objects (including those within collections) in `try...except RecursionError` blocks. Use a safe placeholder or a strictly non-recursive serialization method when the recursion limit is reached to ensure application availability.

## 2025-05-27 - Permission Loss on Atomic Write (CWE-732)
**Vulnerability:** The `atomic_write` implementation used `tempfile.NamedTemporaryFile` and `os.replace` to ensure data integrity. However, `NamedTemporaryFile` creates files with restricted permissions (typically `0o600`) by default. When these files replace existing ones, the original permissions (e.g., world-readability) are lost, potentially breaking access for other users or services.
**Learning:** Atomic write patterns that rely on temporary files must explicitly preserve the metadata of the target file. While `os.replace` ensures atomicity, it does not maintain the attributes of the file being replaced.
**Prevention:** Capture the file mode (`st_mode`) of the existing file before replacement and apply it to the temporary file using `os.chmod`. Always include error handling (e.g., `try...except OSError`) where applying permissions to account for different filesystems or restricted environments.

## 2026-08-05 - DoS via Recursion and Large Cache Keys (CWE-400)
**Vulnerability:** Many locations in the codebase used the built-in `str()` and `json.dumps()` functions on potentially untrusted or deeply nested data from the API. This could lead to a `RecursionError` (crashing the application) or the generation of massive strings that, when used as keys in `@lru_cache` decorated functions, would consume excessive memory and lead to OOM.
**Learning:** Caching mechanisms like `lru_cache` are vulnerable to memory-based DoS if their keys are derived from untrusted input without length limits. Furthermore, implicit recursion in standard serialization tools remains a risk even when the primary processing logic is iterative.
**Prevention:** Use centralized safety utilities (`safe_str`, `safe_json_dumps`) to wrap all serialization of untrusted data. These utilities must catch `RecursionError` and enforce a global `MAX_VALUE_LENGTH` to protect both the application's memory and any downstream caches.
