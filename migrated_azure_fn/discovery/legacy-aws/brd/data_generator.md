## Purpose
The `data_generator` module processes a previously created request record after it is triggered by an upstream event. It retrieves the stored request data, transforms the raw input into a merged/filing-oriented JSON structure, updates the request record with the transformed payload and status timestamps, and then emits an event to the next downstream validator step.

## Triggers
- Receives an EventBridge event with a `detail` payload.
- The event must include `detail.ddbId`, which identifies the request record to process.
- This module is invoked after `request_creator` publishes a `dataGenerator` event.

## Inputs
- EventBridge event object with a `detail` field.
- `detail.ddbId`: required identifier for the DynamoDB request record.
- DynamoDB request record looked up by `ID = ddbId`, containing:
  - `reqInputJSON`
  - `serviceType`
  - `jurisdiction` optional
  - `sourceSystem` optional
- Configuration values imported from `services.config`, including the primary table name.
- Transformation behavior provided by `services.transformer.TransformerFactory`.

## Outputs
- On success, returns a JSON-like dict:
  - `{"ok": True, "ddbId": <id>}`
- On missing `ddbId`, returns:
  - `{"ok": False, "reason": "missing ddbId"}`
- On runtime failure, returns:
  - `{"ok": False, "ddbId": <id>, "error": <exception text>}`
- Writes the transformed payload and status fields back to DynamoDB.
- Publishes an event to the downstream validator path via EventBridge.

## Business Rules
- If `detail.ddbId` is missing or empty, processing stops immediately and the handler returns an error response.
- The module loads the DynamoDB record keyed by `ID = ddbId`; if no record exists, it raises an error and enters failure handling.
- Transformation uses:
  - `reqInputJSON` as the raw payload
  - `serviceType` as a required transformation input
  - `jurisdiction` defaulting to an empty string when absent
  - `sourceSystem` defaulting to `"UPSTREAM"` when absent
- After transformation, the record is updated with:
  - `mergedJSON`
  - `transformedJSON` set to the same transformed value
  - `status.transformed` timestamp
  - `finalStatus = TRANSFORMED`
- After successful persistence, the module publishes a validator event containing the same `ddbId`.
- All exceptions inside the main processing block are caught broadly, logged, passed to shared error handling, and returned as a failure response.

## Side Effects
- Reads from DynamoDB table `<unknown:14031bd5>`.
- Reads from DynamoDB table `<unknown:14af6c1a>`.
- Writes to DynamoDB table `<unknown:212cef05>`.
- Reads from DynamoDB table `<unknown:7f721743>`.
- Reads from DynamoDB table `<unknown:9df589fe>`.
- Reads from DynamoDB table `<unknown:bbab3a38>`.
- Reads from DynamoDB table `<unknown:c5f15d58>`.
- Reads from DynamoDB table `<unknown:d70b2210>`.
- Reads from DynamoDB table `<unknown:fe06ed03>`.
- Reads from DynamoDB table `<unknown:fedcae95>`.
- Reads from S3 bucket `<unknown:4a72a035>`.
- Writes to S3 bucket `<unknown:811a67cb>`.
- Reads an object from S3 using `get_object`.
- Publishes an event to SNS topic `<unknown:c6cc3dc0>`.
- Publishes an event to SQS queue `<unknown:6d07956e>`.
- Consumes messages from SQS queue `<unknown:bb43b9e4>`.
- Consumes messages from SQS queue `<unknown:ef951409>`.
- Imports and relies on shared modules:
  - `services`
  - `services.aws_clients`
  - `services.config`
  - `services.constants`
  - `services.helper`
  - `services.transformer`
- Logs errors through the module logger.
- Invokes shared error handling via `handle_error`.

## Error Paths
- If `detail.ddbId` is missing, the handler returns `{"ok": False, "reason": "missing ddbId"}` without attempting any downstream work.
- If the DynamoDB record cannot be found, the handler raises a runtime error, logs the failure, calls shared error handling, and returns a failure payload.
- If the transformation step raises an exception, the handler catches it, logs it, calls shared error handling, and returns an error response containing the exception text.
- If the DynamoDB update fails, the exception is caught by the same broad exception path and the module returns failure.
- If event publication to the downstream validator fails, the exception is caught and reported through the same failure path.

## Non-Functionals
- Latency: the module performs one record read, one transformation, one record update, and one event publish in sequence, so end-to-end latency depends on those external calls.
- Idempotency: repeated processing of the same `ddbId` can overwrite the same `mergedJSON`, `transformedJSON`, and status fields, and can republish the downstream event.
- Ordering: the DynamoDB update occurs before the downstream validator event is published, so consumers see the transformed state before the next-stage trigger.
- The module uses synchronous processing and does not batch multiple requests in one invocation.

## PII/Compliance
- The module persists and transforms request payloads that may contain business or personally identifiable data depending on upstream input.
- The raw request body is stored in DynamoDB and then transformed into merged JSON, so both source and derived data must be treated as sensitive.
- The module logs the `ddbId` and exception details; it does not intentionally log the full payload, but payload contents may be present in upstream records and should be protected by access controls.
- Any compliance handling, retention, encryption, and access restrictions are delegated to the underlying AWS resources and shared services configuration.