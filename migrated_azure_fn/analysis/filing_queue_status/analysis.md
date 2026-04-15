# Migration Analysis: filing_queue_status

## Summary
- Language: Python
- Complexity: HIGH
- Estimated effort: 14-20 hours
- Migration order priority: 4
- Inbound dependencies: request_creator, data_generator, validation, other queue/event producers that enqueue filing work
- Outbound dependencies: filer event destination, bot status/state store, filing counter state store
- Golden example found: yes, see `migrated_azure_fn/discovery/legacy-aws/design/filing_queue_status.md`

## AWS Dependencies
| AWS Service | SDK Package | Usage | Azure Equivalent | Azure SDK | Migration Notes |
|------------|-------------|-------|-----------------|-----------|----------------|-------------|
| SQS | boto3 client `"sqs"` via `services.aws_clients.sqs_send_message` indirectly through helper and `aws.put_event` flow context | Inbound trigger queue; batch processing with partial failure semantics; retry via `RuntimeError("bot_busy")` | Azure Service Bus queue trigger | `azure-servicebus` / Functions Service Bus trigger binding | Main trigger should become a Service Bus queue trigger; preserve per-message handling and dead-letter/abandon semantics |
| EventBridge | boto3 client `"events"` via `aws.put_event` | Publishes filer event after concurrency gate or Delaware bypass | Azure Event Grid topic or Service Bus topic | `azure-eventgrid` or Service Bus output binding | Need explicit decision based on downstream consumer model; Event Grid is closest semantic fit for broadcast-style eventing |
| DynamoDB | boto3 resource `"dynamodb"` via `update_item`, `increment_counter` in helper | Reads/writes bot status and filing count state; conditional update for idle check | Cosmos DB NoSQL | `azure-cosmos` | This is the stateful concurrency gate; preserve conditional write semantics carefully |
| CloudWatch logging | Python logging | Operational logs and exception traces | Application Insights | Azure Monitor / App Insights SDK | Use structured logging with correlation IDs and safe payload redaction |

## Business Logic
- Core functions: `_process`, `handler`
- Input/output contracts (request schema -> response schema):
  - Input: SQS event with `Records[]`, each record containing `body` JSON
  - Expected body fields: `serviceType`, `jurisdiction`, `payload.ddbId`
  - Output: `{ "batchItemFailures": [...], "results": [...] }`
  - Success result examples:
    - `{"ok": True, "ddbId": "..."}`
    - `{"ok": True, "bypass": "DELAWARE_COGS"}`
  - Malformed body result: `{"ok": False, "reason": "bad_body"}`
- Side effects (writes to DB, publishes events, uploads files):
  - Writes bot status to shared filing settings/state store
  - Decrements filing counter
  - Publishes filer event downstream
  - On unexpected failure, calls shared error handler which can mark record exception state and notify Slack
- Edge cases found in code:
  - Malformed JSON body returns failure result and does not retry the record
  - Delaware + COGS bypasses the concurrency gate entirely
  - Busy bot path raises `RuntimeError("bot_busy")` to force retry behavior
  - Generic exception path logs and returns error payload
  - `ddbId` defaults to empty string if missing; downstream behavior is not fully validated here

## Inter-Service Dependencies
- Upstream (who calls us):
  - SQS producers that enqueue filing work
  - Based on graph data, this module is downstream of queue-producing workflow modules, but exact callers are not fully enumerated in this file alone
- Downstream (who we call):
  - Shared helper functions that mutate filing/bot status and counters
  - Event publisher to filer destination
  - Error handler that may update exception state and send notifications
- Shared libraries:
  - `services.aws_clients`
  - `services.constants`
  - `services.helper`
  - `services.config`
- Inter-service coupling notes:
  - This module depends on shared mutable state for concurrency control, so migration must preserve ownership and atomicity
  - The downstream filer event is a hard coupling point; event contract must remain stable during cutover
  - The handler’s retry behavior relies on queue semantics, so Azure settlement behavior must be equivalent

## Recommended Migration Approach
- Migrate as a Service Bus queue-triggered Azure Function, preserving per-message processing and partial failure handling
- Keep the concurrency gate logic in a single state-owner component; do not split bot status writes across multiple Azure modules
- Replace SQS batch failure semantics with Service Bus message settlement:
  - complete on success
  - abandon or dead-letter on retryable failures
- Implement Delaware COGS as a fast-path branch with direct downstream event publication
- Map shared state from DynamoDB to Cosmos DB with conditional update support for the idle/in-progress transition
- Publish filer events through Event Grid or Service Bus topic, depending on the downstream consumer model
- Keep AWS ACL access only if needed temporarily for straddling migration; otherwise remove at final cutover
- Add structured logging and correlation IDs before changing behavior so operational parity can be verified

## Risks & Blockers
- Atomic concurrency gate semantics may not translate 1:1 from DynamoDB conditional update to Cosmos DB without careful design
- The current code relies on SQS partial batch failure and retry timing; Service Bus retry/abandon behavior is different and must be modeled explicitly
- Downstream event target is not fully specified in this module alone, so Azure target choice cannot be guaranteed from code facts
- Shared helper module contains multiple state mutations; migrating only this handler without its state owner may create split-brain writes
- Generic exception handling in helper code is broad and may hide root causes during migration
- `record_filing_started_if_idle` currently suppresses all exceptions and returns False, making diagnosis harder before migration
- No explicit schema validation exists for the body beyond JSON parsing, so malformed-but-parsable payloads may still fail later
- `handle_error` logs state updates best-effort and suppresses failures, which can complicate observability in Azure
- I could not verify a tree-sitter-based AST or a golden example beyond the discovery doc reference; only function/import extraction and graph metadata were available here

## Learned Rules Applied
- No learned rules were available in `learned-rules.md` for this module at analysis time.