Implemented the `request_creator` migration artifacts under:

- `migrated_azure_fn/request_creator/tests/test_request_creator.py`
- `migrated_azure_fn/request_creator/function_app.py`
- `migrated_azure_fn/request_creator/host.json`
- `migrated_azure_fn/request_creator/local.settings.json`
- `migrated_azure_fn/request_creator/requirements.txt`
- `migrated_azure_fn/request_creator/services/constants.py`
- `migrated_azure_fn/infrastructure/request_creator/main.bicep`

Notes:
- Tests were written first.
- Azure Function entrypoint is HTTP-triggered and preserves the legacy contract.
- Cosmos DB and Event Grid SDK usage is lazy and mockable.
- Bicep includes Function App, Storage, Cosmos DB, Event Grid, and App Insights.

I have not run tests.