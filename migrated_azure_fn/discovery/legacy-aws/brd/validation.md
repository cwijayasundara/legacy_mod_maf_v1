## Purpose
The `validation` module handles the validation step after a merged request payload has been produced. It reads the stored record for a given `ddbId`, validates the `mergedJSON` content using the shared validator service, and then branches the workflow based on the validation outcome:
- On success, it marks the record as validated and pushes the request onto the common FIFO queue for downstream processing.
- On validation failure, it stores the validation errors on the record and marks the record as an exception state.

## Triggers
- Invoked by an EventBridge-style event containing `detail.ddbId`.
- The event is expected to come from the prior `dataGenerator` step in the processing chain.
- If `detail.ddbId` is missing, the handler exits early and returns a failure response without attempting any persistence or validation.

## Inputs
- Event payload with a `detail` object.
- Required field: `detail.ddbId`.
- DynamoDB record identified by `ddbId`, expected to contain:
  - `mergedJSON`
  - `serviceType`
  - `jurisdiction`
- Validation is performed against the stored `mergedJSON` object.
- Shared configuration/constants used at runtime:
  - `services.config`
  - `services.constants`
  - `services.validators`
  - `services.helper`
  - `services.aws_clients`

## Outputs
- Success response:
  - `{"ok": True, "ddbId": <id>}`
- Missing `ddbId` response:
  - `{"ok": False, "reason": "missing ddbId"}`
- Validation failure response:
  - `{"ok": False, "ddbId": <id>, "errors": <validation_errors>}`
- Runtime error response:
  - `{"ok": False, "ddbId": <id>, "error": <error_message>}`
- Side-effect outputs to downstream systems:
  - Updates the DynamoDB record status.
  - Publishes a message to the common queue for successful validations.

## Business Rules
- The handler must not proceed without a `ddbId`.
- The record for the given `ddbId` must exist in the configured DynamoDB table; otherwise the operation is treated as an error.
- Validation is performed on `mergedJSON` from the stored record, defaulting to an empty object if absent.
- If validation fails:
  - `mergedJSONValidationErrors` is written to the record.
  - `finalStatus` is set to `EXCEPTION`.
  - `status.validated` is stamped with the current Unix timestamp.
- If validation succeeds:
  - `finalStatus` is set to `VALIDATED`.
  - `status.validated` is stamped with the current Unix timestamp.
  - A payload containing `ddbId` plus the validated merged content is pushed to the common queue.
- The downstream queue message includes the original record’s `serviceType` and `jurisdiction`.

## Side Effects
- Reads from DynamoDB table `<unknown:0777f615>` via `aws.get_item`.
- Writes to DynamoDB table `<unknown:229f3a26>` via `aws.update_item`.
- Writes a message to SQS queue `<unknown:8d415f52>` through `push_item_to_common_queue`.
- Depends on the validator logic in `services.validators`.
- Uses shared helper logic in `services.helper` for queue publishing and error handling.
- Uses shared AWS client abstractions in `services.aws_clients`.
- Uses shared configuration in `services.config`.
- Uses shared status constants in `services.constants`.

## Error Paths
- If `detail.ddbId` is missing, the handler returns `{"ok": False, "reason": "missing ddbId"}` and performs no further work.
- If the DynamoDB record cannot be found for the supplied `ddbId`, a runtime error is raised, logged, and routed to shared error handling.
- If validation fails, the record is updated with validation errors and the handler returns a failure response without enqueueing downstream work.
- If any unexpected exception occurs during read, validation, update, or queue push:
  - the exception is logged,
  - `handle_error(ddb_id, exc)` is invoked,
  - the handler returns `{"ok": False, "ddbId": <id>, "error": <message>}`.
- The code does not define a separate recovery path for partial success after the DynamoDB update but before queue publishing.

## Non-Functionals
- Latency: processing is synchronous within the Lambda invocation and includes one DynamoDB read, one validation call, one DynamoDB write, and optionally one queue publish.
- Idempotency: repeated invocation with the same `ddbId` may repeat validation and may re-write status fields and re-enqueue the downstream message.
- Ordering: validation occurs after the record has been persisted by the prior step; downstream queue publication occurs only after a successful validation and status update.
- The function is designed for event-driven execution and does not batch multiple business records in one invocation.

## PII/Compliance
- The module may process request payloads containing business data inside `mergedJSON`, but the code does not explicitly classify or redact PII.
- Validation errors are stored back into DynamoDB and may contain portions of the submitted payload structure depending on validator output.
- The handler does not log the raw merged payload, but it does log exceptions with the `ddbId` context.
- Queue messages include `ddbId`, `serviceType`, `jurisdiction`, and the merged payload; these may contain sensitive business information depending on upstream content.
- No explicit encryption, masking, consent, retention, or regulatory compliance controls are implemented in this module.