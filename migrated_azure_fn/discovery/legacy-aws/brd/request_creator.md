## Purpose
`request_creator` handles an incoming HTTP POST request for creating a filing request. It validates the minimum required request fields, applies jurisdiction/service-type gating for upstream requests, stores the original request payload in the main request DynamoDB table, and publishes an EventBridge event to start downstream processing in `dataGenerator`.

## Triggers
- Invoked by an HTTP request to `/filing/request`.
- Expected to receive a request body that can be parsed by the shared `load_event_body` helper.
- Triggered in response to client-submitted filing request creation, including normal upstream requests and special event types such as merge-evidence or order-resubmit.

## Inputs
- HTTP event payload body parsed by `load_event_body`.
- Request fields read from the body:
  - `serviceType` required.
  - `jurisdiction` optional for general storage but required for jurisdiction-specific settings lookup when applicable.
  - `eventType`
  - `source` defaulting to `UPSTREAM`
  - `cidPin` when required by settings.
- Jurisdiction/service configuration from the settings DynamoDB table keyed by `pk = "{jurisdiction}#{serviceType}"`.
- Runtime-generated identifiers and timestamps:
  - `uuid.uuid4()` for the request record ID.
  - current Unix timestamp for `status.created` and `createdAt`.

## Outputs
- On success:
  - HTTP 200 JSON response containing:
    - `ddbId`
    - `status: "CREATED"`
- On validation failure:
  - HTTP 400 JSON response when `serviceType` is missing.
  - HTTP 400 JSON response when CID/PIN is required but not supplied.
  - HTTP 409 JSON response when the jurisdiction/service-type combination is disabled.
- On unexpected failure:
  - HTTP 500 JSON response containing the error string and the generated `ddbId`.
- Side-channel output:
  - EventBridge event to `dataGenerator` with `detail.ddbId`.
  - For `MERGE_EVIDENCE` and `ORDER_RESUBMIT`, the event detail also includes `branch`.

## Business Rules
- `serviceType` is mandatory; the request is rejected if it is absent.
- A new request ID is generated for every accepted call using a UUID.
- If `source` is `UPSTREAM` and `eventType` equals the upstream event constant:
  - The module looks up jurisdiction/service settings.
  - If the combination is disabled, the request is rejected with a conflict response.
  - If `cidPinRequired` is enabled in settings and no `cidPin` is provided, the request is rejected with a bad request response.
- Every accepted request is persisted to the primary request table with:
  - the original request body in `reqInputJSON`
  - `serviceType`
  - `jurisdiction`
  - `sourceSystem`
  - `eventType`
  - created status metadata
  - `finalStatus = CREATED`
- After persistence, the module always publishes an EventBridge event to `dataGenerator`.
- For `MERGE_EVIDENCE` and `ORDER_RESUBMIT`, the event sent to `dataGenerator` includes a `branch` field indicating the event type.

## Side Effects
- Writes a new item to DynamoDB table `<unknown:91c11e2e>` with the request record.
- Reads DynamoDB table `<unknown:0c296b2b>` for jurisdiction/service settings.
- Publishes an EventBridge event via the AWS client helper to `dataGenerator`.
- Uses shared helper functions from `services.helper` for body parsing, response shaping, and error handling.
- Imports supporting configuration and constants from:
  - `services.config`
  - `services.constants`
  - `services.aws_clients`
  - `services.helper`

## Error Paths
- If the request body cannot be processed into a usable object by `load_event_body`, the function may fail and return a 500 response via the generic exception handler.
- If `serviceType` is missing, the handler returns HTTP 400 immediately.
- If an upstream request targets a disabled jurisdiction/service-type combination, the handler returns HTTP 409.
- If `cidPin` is required by settings and not supplied, the handler returns HTTP 400.
- If any DynamoDB write, settings lookup, or EventBridge publish operation raises an exception, the handler logs the failure, calls `handle_error(ddb_id, exc)`, and returns HTTP 500.
- The error response for unexpected failures includes the error string and the generated request ID.

## Non-Functionals
- Latency: the handler performs synchronous request validation, one settings read when applicable, one DynamoDB write, and one event publish before responding.
- Idempotency: the module does not implement deduplication; repeated calls can create multiple distinct request IDs and records.
- Ordering: the request is written to DynamoDB before the downstream `dataGenerator` event is published.
- The response to the caller is returned only after persistence and event publication are attempted.

## PII/Compliance
- The entire request body is stored in `reqInputJSON`, so any sensitive data included by the caller is persisted in DynamoDB `<unknown:91c11e2e>`.
- The module explicitly checks for `cidPin`, indicating it may handle sensitive identity-related data.
- No masking, encryption, or redaction logic is implemented in this module.
- Error handling logs exceptions and request identifiers, but the code does not intentionally log the full request body.
- Compliance responsibility for any sensitive fields in the request payload depends on upstream callers and the surrounding storage/security configuration.
