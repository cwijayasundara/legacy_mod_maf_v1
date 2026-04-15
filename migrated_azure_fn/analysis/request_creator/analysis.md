# Migration Analysis: request_creator

## Summary
- Language: python
- Complexity: HIGH
- Estimated effort: 12-16 hours
- Migration order priority: 1
- Inbound dependencies: no direct caller identified from provided source; likely HTTP clients via API Gateway
- Outbound dependencies: settings lookup via DynamoDB, request persistence via DynamoDB, downstream event publish to dataGenerator/EventBridge

## AWS Dependencies
| AWS Service | SDK Package | Usage | Azure Equivalent | Azure SDK | Migration Notes |
|------------|-------------|-------|-----------------|-----------|-----------------|
| DynamoDB | boto3.resource("dynamodb") via `aws_clients.get_item` / `put_item` / `update_item` | Reads jurisdiction/service settings and writes the new request record | Azure Cosmos DB NoSQL | `azure-cosmos` | Map the settings table and primary request table to separate Cosmos containers to preserve single-writer ownership |
| EventBridge | boto3.client("events") via `aws_clients.put_event` | Publishes downstream event to `dataGenerator` | Azure Event Grid | `azure-eventgrid` | Preserve the `source`, `destination`, and `detail` payload shape in the event body |
| UUID/time utilities | Python stdlib | Generates request ID and timestamps | Python stdlib | n/a | No Azure equivalent needed |
| Shared AWS wrappers | internal `aws_clients` module | Abstracts AWS SDK calls | Azure client wrappers | `azure-cosmos`, `azure-eventgrid` | This is infrastructure glue, not domain logic |

## Business Logic
- Core functions: `_lookup_jurisdiction_settings`, `handler`
- Input/output contracts (request schema -> response schema):
  - Input body fields used:
    - `serviceType` required
    - `jurisdiction` optional for general storage, required for jurisdiction-specific lookup
    - `eventType`
    - `source` defaults to `UPSTREAM`
    - `cidPin` required only when settings demand it
  - Success response:
    - HTTP 200
    - body: `{"ddbId": "...", "status": "CREATED"}`
  - Validation responses:
    - 400 if `serviceType` missing
    - 400 if CID/PIN required but missing
    - 409 if jurisdiction/service combination is disabled
  - Error response on unexpected failure:
    - HTTP 500 with `error` and `ddbId`
- Side effects (writes to DB, publishes events, uploads files):
  - Writes a request record to the main request table
  - Reads jurisdiction/service settings from the settings table
  - Publishes a downstream event to `dataGenerator`
- Edge cases found in code:
  - If `source == "UPSTREAM"` and `eventType == EventType.UPSTREAM`, settings gating is applied
  - `MERGE_EVIDENCE` and `ORDER_RESUBMIT` add `branch` to the event detail
  - Any unexpected exception triggers `handle_error(ddb_id, exc)` and then returns 500
  - The handler does not implement deduplication, so repeated calls can create multiple records

## Inter-Service Dependencies
- Upstream (who calls us):
  - Not directly visible in the source
  - Based on the comment and route, this is an HTTP ingress likely fronted by API Gateway
- Downstream (who we call):
  - `dataGenerator` via EventBridge event publication
- Shared libraries:
  - `services.helper` for body parsing, JSON response creation, and error handling
  - `services.config` for table/bus names
  - `services.constants` for `DDBStatus` and `EventType`
  - `services.aws_clients` for AWS API access

## Recommended Migration Approach
- Migrate as an HTTP-triggered Azure Function on the Consumption plan
- Keep business validation in a thin application layer and move AWS-specific persistence/event publishing behind Azure adapters
- Use:
  - Azure Cosmos DB container for request records
  - Azure Cosmos DB container for settings lookup
  - Azure Event Grid for downstream publication to `dataGenerator`
- Preserve the response contract exactly, including status codes and the `ddbId`
- Replace `json_response` with Azure Functions HTTP response handling, but keep the JSON error shape consistent with platform standards
- Treat `aws_clients` as a migration boundary: re-implement the SDK calls rather than porting the wrapper as-is
- Add explicit correlation IDs and structured logging before touching code, because the current handler only logs a generic exception

## Risks & Blockers
- The `analysis` output is not enough to infer exact Cosmos partitioning; the DynamoDB key shape is only partially visible
- The module uses a broad `except Exception` block, which is incompatible with the error-handling standards and can hide root causes
- The code persists the full request body in `reqInputJSON`, so any sensitive fields such as `cidPin` will be stored unless the Azure design adds controls
- Event publication is synchronous; if Event Grid delivery or serialization fails, the request returns 500 after the record has already been written
- The settings table key schema must be preserved carefully; otherwise the upstream gating logic could silently change
- I could not verify a golden example under `src/azure-functions/` because the expected directory was not available in the provided filesystem path
- Learned rules file could not be read from the expected location, so no module-specific learned rules could be enumerated from disk

## Learned Rules Applied
- None could be confirmed from `state/learned-rules.md` because the file was not available at the expected path in the provided filesystem snapshot