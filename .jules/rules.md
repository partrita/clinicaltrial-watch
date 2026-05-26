# Jules Agent Rules & Instructions

This directory contains instructions and rules that must be followed by Jules (the AI coding assistant) when interacting with this repository.

## Critical Rules

1. **Do Not Modify `trials.yaml` Directly**
   - **Rule**: Jules must **NEVER** manually modify `trials.yaml` to add, edit, or delete trials or targets.
   - **Rationale**: Manual modification bypasses validation logic, risks introducing syntax/format errors, and can lead to data loss.
   - **Allowed Actions**: All updates to target trials must be handled programmatically using the provided automated tools and scripts:
     - Automated trial discovery: `src/auto_discover_trials.py`
     - CSV imports: `src/update_trials_from_csv.py`
