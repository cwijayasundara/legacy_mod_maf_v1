# Migration Analysis: data_generator

## Summary
- Language: Python
- Complexity: HIGH
- Estimated effort: 12-16 hours
- Migration order priority: 2
- Inbound dependencies: request_creator, upstream EventBridge producers, other modules that emit `detail.ddbId` for this handler
- Outbound dependencies: DynamoDB `RequestRecords`, transformer service, EventBridge publisher to `validator`, shared error handler/Slack notification path

## AWS Dependencies
| AWS Service | SDK Package | Usage | Azure Equivalent | Azure SDK | Migration Notes |
|------------|-------------|-------|-----------------|-----------|-----------------|
| DynamoDB | `boto3.resource("dynamodb")` via `aws_clients.get_item` / `update_item` | Reads raw request record by `ID`; updates merged/transformed JSON and status | Azure Cosmos DB or Azure Table Storage | `azure-cosmos` or `azure-data-tables` | Must confirm actual data model before choosing target. Update semantics and conditional writes differ. |
| EventBridge | `boto3.client("events")` via `aws_clients.put_event` | Publishes event to downstream `validator` with `ddbId` | Azure Service Bus topic, Event Grid, or Storage Queue | `azure-servicebus` / `azure-eventgrid` / `azure-storage-queue` | Best equivalent depends on current eventing topology. EventBridge fan-out maps more closely to Event Grid or Service Bus topics. |
| Shared AWS wrappers | `aws_clients.py` (boto3) | Infrastructure glue for get/update/publish | Azure SDK wrappers or direct bindings | Depends on selected service | This module depends on wrapper functions, not raw SDK calls. |
| Transformer business layer | `TransformerFactory.transform_to_filer_json` | Converts request JSON into merged filer JSON | No direct Azure equivalent; retain as domain code | N/A | Pure business logic should be kept and reused as-is where possible. |
| Error handling side effects | `handle_error` | Updates failure state and sends Slack notification | Application Insights / Teams webhook / Azure Function logging | `azure-monitor-opentelemetry` optionally | Slack integration is external HTTP, not AWS-specific, but should be reviewed. |

## Business Logic
- Core functions: `handler(event, context)`
- Input/output contracts (request schema -> response schema):
  - Input: EventBridge event with `detail.ddbId`
  - Output on success: `{"ok": True, "ddbId": ddb_id}`
  - Output on validation failure: `{"ok": False, "reason": "missing ddbId"}`
  - Output on runtime failure: `{"ok": False, "ddbId": ddb_id, "error": str(exc)}`
- Side effects (writes to DB, publishes events, uploads files):
  - Reads one DynamoDB record from `TABLE_NAME`
  - Writes `mergedJSON`, `transformedJSON`, `status.transformed`, and `finalStatus`
  - Publishes EventBridge event to destination `validator`
  - On error, `handle_error` marks record as `EXCEPTION` and sends Slack notification
- Edge cases found in code:
  - Missing `detail.ddbId` returns a failure payload without raising
  - Missing record raises `RuntimeError`
  - `record["serviceType"]` is required and will raise `KeyError` if absent
  - `record.get("reqInputJSON", {})` defaults safely when raw payload is missing
  - Any exception is caught broadly and converted to a failure response
  - The code does not validate the transformed output before persisting it

## Inter-Service Dependencies
- Upstream (who calls us):
  - EventBridge source pipeline from `requestCreator` / upstream event producers
  - Exact caller list is not fully available from the provided source
- Downstream (who we call):
  - DynamoDB via `aws.get_item` and `aws.update_item`
  - EventBridge via `aws.put_event` to `validator`
  - Shared `handle_error` path, which also writes back to DynamoDB and calls Slack
- Shared libraries:
  - `services/aws_clients.py`
  - `services/config.py`
  - `services/constants.py`
  - `services/helper.py`
  - `services/transformer.py`

## Recommended Migration Approach
- Preserve the transformer and status-update sequence as domain logic, but replace AWS infrastructure calls with Azure-compatible abstractions.
- Implement the Azure Function as an event-driven function triggered by Service Bus, Event Grid, or HTTP depending on how the source pipeline is migrated.
- Keep the record lookup and status update in a single repository/adapter layer to preserve single-owner state mutation.
- Map the downstream `validator` notification to Azure Service Bus topic publish or Event Grid emission, depending on how validators are subscribed.
- Rework error handling to return Azure-friendly structured failures and use centralized logging/telemetry instead of Lambda-style ad hoc handling.
- Confirm whether the record store should be Cosmos DB or Table Storage before coding, because the update expression used here implies document-style partial updates.

## Risks & Blockers
- The exact Azure target for DynamoDB is not knowable from this file alone; data modeling choice is a blocker.
- `handle_error` mutates the same table as the main handler, so the migration must avoid duplicate write logic across services.
- The function currently depends on a broad `except Exception`, which is a quality-risk and may hide migration failures.
- The outbound event contract to `validator` is implicit; consumer expectations are not visible here.
- The record schema is partially inferred and not validated, especially `serviceType` and `reqInputJSON`.
- No golden Azure Functions example was found in `src/azure-functions/` from the available filesystem context.
- Learned rules file could not be located at `/Users/chamindawijayasundara/Documents/rnd_2026/ai_foundry_agents/learned-rules.md`, so no module-specific learned rules could be applied from that source.

## Learned Rules Applied
- None found or readable in the provided environment.
