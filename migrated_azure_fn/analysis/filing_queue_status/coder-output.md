Implemented the migration artifacts for `filing_queue_status`:

- Added unit tests under:
  - `migrated_azure_fn/filing_queue_status/tests/test_filing_queue_status.py`
- Added Azure Function implementation:
  - `migrated_azure_fn/filing_queue_status/function_app.py`
- Added required app files:
  - `requirements.txt`
  - `host.json`
  - `local.settings.json`
- Added Bicep template:
  - `migrated_azure_fn/infrastructure/filing_queue_status/main.bicep`

I have not run tests.