## Purpose
`filing_queue_status` processes messages from a FIFO SQS queue to control filing concurrency and route work to the filer workflow.

It determines whether a filing job may start immediately or must wait based on bot availability. When eligible, it marks the bot as in progress, decrements the active filing counter, and publishes a downstream event to the filer. It also includes a special bypass path for Delaware COGS requests, which skips the normal SQS gating behavior and forwards directly to the filer event.

## Triggers
- Invoked by SQS messages from the common filing queue.
- Processes each record in the incoming batch independently.
- For messages with jurisdiction `DELAWARE` and service type `COGS`, it follows a bypass path that publishes directly to the filer destination.

## Inputs
- SQS event containing `Records`.
- Each record is expected to contain a JSON `body`.
- Expected message fields in the decoded body:
  - `serviceType`
  - `jurisdiction`
  - `payload`
- Expected nested payload field:
  - `payload.ddbId`

The module also depends on helper logic that reads and updates multiple DynamoDB-backed status records and counters.

## Outputs
- Returns an object with:
  - `batchItemFailures`: list of failed message identifiers for SQS partial batch processing
  - `results`: per-record processing results
- For successfully handled messages, it returns result objects such as:
  - `{"ok": True, "ddbId": ...}`
  - `{"ok": True, "bypass": "DELAWARE_COGS"}`
- For malformed JSON bodies, it returns a per-record failure result:
  - `{"ok": False, "reason": "bad_body"}`
- When a bot is busy, the record is retried via SQS visibility handling by raising `RuntimeError("bot_busy")`.
- On unexpected processing failures, it returns an error result and may write error state through helper handling.

## Business Rules
- A message body must be valid JSON; otherwise the record is treated as malformed and skipped from normal processing.
- If `jurisdiction == "DELAWARE"` and `serviceType == "COGS"`, the message bypasses the normal concurrency gate and is sent directly to the filer event destination.
- For all other messages, processing only proceeds if `record_filing_started_if_idle(jurisdiction, service_type)` reports that the bot was idle.
- If the bot is already busy, the module intentionally raises a retryable runtime error so the SQS message can be retried later.
- When a filing starts successfully, the module:
  - marks bot filing status as `IN_PROGRESS`
  - stores the `ddbId` in bot status data
  - decrements the filing count by 1
  - publishes an event to the filer destination
- Batch processing is per record, so one message’s failure does not prevent other records from being processed.

## Side Effects
- Reads from DynamoDB tables:
  - `dynamodb_table:<unknown:05060438>`
  - `dynamodb_table:<unknown:0a8c1172>`
  - `dynamodb_table:<unknown:10940326>`
  - `dynamodb_table:<unknown:491e9a30>`
  - `dynamodb_table:<unknown:4ad5977e>`
  - `dynamodb_table:<unknown:8425985b>`
  - `dynamodb_table:<unknown:999cbbc9>`
  - `dynamodb_table:<unknown:bc835f4a>`
  - `dynamodb_table:<unknown:c67c3b06>`
- Writes to DynamoDB table:
  - `dynamodb_table:<unknown:9326a15c>`
- Reads from S3 bucket:
  - `s3_bucket:<unknown:0aba5933>`
- Writes to S3 bucket:
  - `s3_bucket:<unknown:7cfb575f>`
- Reads from S3 using `get_object`
- Consumes messages from SQS queues:
  - `sqs_queue:<unknown:00b2db8f>`
  - `sqs_queue:<unknown:294ef9eb>`
- Produces messages to SQS queue:
  - `sqs_queue:<unknown:9dd11495>`
- Produces events to SNS topic:
  - `sns_topic:<unknown:21c94b21>`
- Imports and depends on shared application modules:
  - `services`
  - `services.aws_clients`
  - `services.config`
  - `services.constants`
  - `services.helper`
- Uses helper routines that likely mutate bot status, filing counters, and downstream event routing.

## Error Paths
- If the SQS body is not valid JSON, the record is marked as malformed and returned with `reason: "bad_body"`.
- If the bot is busy, the module raises `RuntimeError("bot_busy")` to trigger SQS retry/visibility behavior.
- If an unexpected exception occurs during record processing, the module logs the exception and returns an error result for that record.
- If `ddbId` is missing from the payload, downstream logic may operate with an empty identifier and helper error handling may be invoked.
- If helper functions or AWS calls fail, the exception is caught by the generic handler path and converted into a failure result.
- Partial batch failure handling allows only the failed SQS message IDs to be retried.

## Non-Functionals
- Latency: designed for near-real-time queue handling of filing initiation messages.
- Idempotency: not explicitly enforced in this module; repeated SQS deliveries may re-run concurrency gating and event publication depending on helper state.
- Ordering: processes records in the order they appear in the incoming batch, but SQS FIFO semantics and retry behavior determine actual end-to-end ordering.
- Reliability: uses partial batch failure semantics so one bad message does not fail the whole batch.
- Throughput control: concurrency is intentionally constrained by bot idle/in-progress status checks.

## PII/Compliance
- The module processes filing identifiers and payload data that may contain regulated business information.
- It does not explicitly redact or transform PII in this handler; compliance depends on upstream payload shaping and helper/service behavior.
- Logging includes operational details such as jurisdiction and service type, and may include `ddbId`; sensitive payload contents should not be logged.
- The Delaware COGS bypass and queue-based filing control may be part of regulated filing workflows, so auditability of status changes and event publication is important.