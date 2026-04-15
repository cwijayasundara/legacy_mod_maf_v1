# Migration Analysis: validation

## Summary
- Language: python
- Complexity: MEDIUM
- Estimated effort: 8-12 hours
- Migration order priority: 3
- Inbound dependencies: EventBridge event source from dataGenerator; no direct in-repo callers found in the provided module set
- Outbound dependencies: DynamoDB via `aws_clients`, FIFO SQS common queue, shared validator/helper modules, config/constants

## AWS Dependencies
| AWS Service | SDK Package | Usage | Azure Equivalent | Azure SDK | Migration Notes |
|------------|-------------|-------|-----------------|-----------|-----------|-----------------|
| DynamoDB | `boto3.resource("dynamodb")` via `aws_clients.get_item` / `update_item` | Read merged request record, write validation status/errors, timestamp status updates | Azure Cosmos DB or Azure Table Storage | `azure-cosmos` or `azure-data-tables` | Primary state store. Need table/partition-key mapping and conditional update semantics if used elsewhere. |
| SQS FIFO | `boto3.client("sqs")` via `push_item_to_common_queue` / `sqs_send_message` | Enqueue validated payload to common queue with group and dedup IDs | Azure Storage Queue or Azure Service Bus sessions | `azure-storage-queue` or `azure-servicebus` | FIFO semantics map best to Service Bus sessions; dedup/group behavior should be preserved explicitly. |
| EventBridge | Implicit trigger from module docstring and handler contract | Receives validation event from dataGenerator | Azure Event Grid or Service Bus trigger | `azure-eventgrid` or `azure-servicebus` binding | Trigger shape must be adapted from `event.detail.ddbId` to Azure trigger payload. |
| AWS SDK wrapper layer | `boto3`, `botocore.config.Config` in `services/aws_clients.py` | Abstraction for AWS calls used by handler and helpers | Azure SDK wrappers / client factory | Depends on target store | This module does not import boto3 directly, but depends on shared AWS client wrappers that must be replaced. |

## Business Logic
- Core functions: `handler`, `validate` (from shared validators), `handle_error` (shared best-effort failure path), `push_item_to_common_queue`
- Input/output contracts (request schema -> response schema):
  - Input: EventBridge-style event with `event["detail"]["ddbId"]`
  - Output on missing id: `{"ok": False, "reason": "missing ddbId"}`
  - Output on validation failure: `{"ok": False, "ddbId": ddb_id, "errors": [...]}`
  - Output on success: `{"ok": True, "ddbId": ddb_id}`
  - Output on unexpected exception: `{"ok": False, "ddbId": ddb_id, "error": str(exc)}`
- Side effects (writes to DB, publishes events, uploads files):
  - Reads a record by `ID` from `cfg.TABLE_NAME`
  - Updates record `finalStatus` and nested `status.validated` timestamp
  - On validation failure, stores `mergedJSONValidationErrors`
  - On success, publishes merged payload to FIFO common queue
  - On exception, marks record exception state through `handle_error`
- Edge cases found in code:
  - Missing `ddbId` returns a soft failure without raising
  - Missing record raises `RuntimeError`
  - Validation result expected to contain `success` and `errors`
  - Uses `record["serviceType"]` without fallback; missing field would raise `KeyError`
  - Uses `record.get("jurisdiction", "")`; empty jurisdiction is allowed but may affect downstream routing
  - Broad `except Exception` swallows all failures and converts them into string responses

## Inter-Service Dependencies
- Upstream (who calls us):
  - EventBridge source from `dataGenerator` per module docstring
- Downstream (who we call):
  - DynamoDB via `aws.get_item` / `aws.update_item`
  - Common FIFO queue via `push_item_to_common_queue`
  - Shared error handling via `handle_error`
  - Shared validation logic via `validate`
- Shared libraries:
  - `services/aws_clients.py`
  - `services/config.py`
  - `services/constants.py`
  - `services/helper.py`
  - `services/validators.py`

## Recommended Migration Approach
- Convert this into an Event Grid or Service Bus-triggered Azure Function depending on the upstream event source shape.
- Keep business logic separate from trigger glue:
  - trigger adapter parses Azure event payload
  - domain service loads record, validates merged JSON, persists status, enqueues downstream payload
- Replace DynamoDB access with a single owning repository module for the record table to preserve the single-owner state mutation rule.
- Replace FIFO SQS usage with Azure Service Bus if ordering/grouping/dedup semantics are required; otherwise document lost semantics explicitly.
- Normalize error handling to structured Azure Function responses only if this is also exposed over HTTP; if event-driven, prefer exception-based retry semantics plus structured logging.
- Add contract tests for:
  - missing `ddbId`
  - missing record
  - validation failure path
  - queue publish path
  - unexpected exception path

## Risks & Blockers
- The provided source uses shared AWS wrappers; Azure migration will need replacement for both DynamoDB and SQS behavior, not just handler rewrite.
- FIFO queue semantics may not have a 1:1 match if Azure Storage Queue is used; Service Bus sessions may be needed.
- The handler catches all exceptions, which can hide transient infrastructure failures and reduce retry effectiveness in Azure Functions.
- `record["serviceType"]` is assumed present; if legacy data is inconsistent, this can fail before queue publish.
- No golden example was found in `src/azure-functions/` for this language in the provided repository scan, so there is no local Azure reference pattern to reuse.
- I could not read `learned-rules.md` from the provided path, so no repository-specific learned rules could be listed.

## Learned Rules Applied
- None could be confirmed from `state/learned-rules.md` or a repository `learned-rules.md` file in the provided context.