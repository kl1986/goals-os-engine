# Engine Release Process

This document outlines the standard release process for the `goals-os-engine`. Since upgrades in Goals OS are effectively "plugin updates" that structurally cannot touch the user's Brain, the release process is focused on verifying the Engine's functional correctness against the base template.

## Prerequisites

- Ensure you have `pytest` installed via the `requirements.txt`.
- Make sure `python3` is available.

## Release Checklist

1. **Verify Tests**: Run the test suite using `pytest` to ensure all core functionalities are working correctly against mocked structures.
   ```bash
   pip install -r requirements.txt
   PYTHONPATH=. pytest
   ```

2. **Integration Verification**: Run the `test_fresh_install.sh` script to confirm that the real clone-and-onboard flow works from end-to-end. This integration test should cleanly simulate materializing configuration and executing a mock loop.
   ```bash
   ./test_fresh_install.sh
   ```

3. **Verify Library Plugins**: Ensure the Library plugins still route correctly against the updated Engine. Clone the `goals-os-library` and verify that any updated Engine APIs or structural behaviors have not broken compatibility with the optional plugins.

4. **Verify Documentation**: Update any newly added scripts or protocols in the corresponding `docs/` and `protocols/` areas. Ensure changes are reflected accurately.

5. **Bump the Engine Version (Tag Release)**: Version tracking for the Engine is via git tags only (a conscious decision, there is no `VERSION` file). Tag the current commit in Git with the new version (e.g., `git tag v2.0.1`). Note that because the user's Brain is isolated, they simply pull the latest `goals-os-engine` without needing migrations, unless explicitly stated.

6. **Commit and Push**: Ensure all changes (including this checklist execution) are cleanly committed and pushed to `main` and push tags (`git push --tags`).
