## Function Plan (Consumption/Premium/Flex)

- **Plan:** Consumption
- **Reasoning:** `request_creator` is an HTTP-triggered request validator/orchestrator with a small synchronous workflow: parse request, validate fields, optionally read settings, write the request record, and publish a downstream event. This is a good fit for Consumption given the short-lived, event-driven nature.
- **When to consider Premium/Flex:** Move to Premium or Flex only if the module later needs:
  - VNet integration or private endpoints for data stores,
  - consistently low-latency cold start mitigation,
  - longer execution time due to additional synchronous downstream calls.

## Trigger Bindings (one entry per source AWS trigger)

- **API Gateway → HTTP trigger**
  - Route: `POST /filing/request`
  - Purpose: Accept client-submitted filing request creation payloads.
  - Notes: Use a standard HTTP response wrapper with validation failures returning structured 400/409 errors.

- **SQS `<unknown:12f44477>` → Service Bus queue trigger**
  - Purpose: If this source is still part of the module’s inbound workflow, map it to a Service Bus queue trigger for asynchronous intake.
  - Notes: Keep message handling separate from the HTTP path if the queue is used for retries or delayed processing.

- **SQS `<unknown:c0d18561>` → Service Bus queue trigger**
  - Purpose: Additional async consumer input.
  - Notes: If this queue represents a distinct processing lane, preserve its own trigger/function to avoid mixed responsibility.

## State Mapping (one entry per AWS resource the module touches)

- **DynamoDB table `<unknown:91c11e2e>` → Cosmos DB NoSQL container**
  - Owns persistence of the accepted request record.
  - Stores the original request payload in `reqInputJSON` plus status metadata and identifiers.

- **DynamoDB table `<unknown:0c296b2b>` → Cosmos DB NoSQL container**
  - Stores jurisdiction/service-type settings used for gating and CID/PIN requirements.
  - Must be read consistently by the request validation path.

- **DynamoDB table `<unknown:1a04c780>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:511dce5f>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:5ef17d53>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:798bb231>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:89a55f48>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:d425d1be>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:d8d0a56d>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **DynamoDB table `<unknown:e0da9853>` → Cosmos DB NoSQL container**
  - Referenced by the module edges; map to a read-only Cosmos container if still required by runtime settings or shared helpers.

- **S3 bucket `<unknown:49455859>` → Blob storage container**
  - Referenced by the module edges; map to Azure Blob Storage if the module reads artifacts or attachments from object storage.

- **S3 bucket `<unknown:c5d90f3d>` → Blob storage container**
  - Referenced by the module edges as a write target; map to Azure Blob Storage if the module emits stored artifacts or payload snapshots.

- **S3 `get_object` → Blob trigger / Blob SDK read**
  - If the module reads object content directly, use the Blob SDK from the function rather than a trigger.

- **SNS topic `<unknown:8b05176d>` → Event Grid topic**
  - Map the downstream publication path to Event Grid for fan-out to `dataGenerator` and any other subscribers.

- **SQS queue `<unknown:12f44477>` → Service Bus queue**
  - Map inbound asynchronous consumption, if still active, to a Service Bus queue.

- **SQS queue `<unknown:53539e15>` → Service Bus queue**
  - Map outbound asynchronous production, if still active, to a Service Bus queue.

- **SQS queue `<unknown:c0d18561>` → Service Bus queue**
  - Map inbound asynchronous consumption, if still active, to a Service Bus queue.

## Secrets

- Store all environment-specific connection information in **Key Vault**.
- Likely secrets/config items:
  - Cosmos DB connection details, if using key-based access instead of managed identity
  - Event Grid endpoint/key only if managed identity delivery is not used
  - Any shared configuration values consumed by `services.config`
- Do not store the request payload or `cidPin` in secrets; those are runtime inputs and/or persisted data.
- Prefer Key Vault references in app settings over hard-coded values.

## Identity

- Use the Function App’s **Managed Identity** for:
  - reading the settings container,
  - writing the primary request container,
  - publishing to Event Grid,
  - reading any Blob resources if still needed.
- Grant least-privilege roles:
  - Cosmos DB data reader for settings access,
  - Cosmos DB data contributor for the request write container,
  - Event Grid Data Sender for publishing downstream events,
  - Storage Blob Data Reader/Contributor only if Blob access remains required.
- Avoid shared access keys where managed identity is supported.

## IaC (Bicep)

- Deploy a Function App on the **Consumption** plan.
- Define:
  - HTTP-triggered function route `filing/request`
  - Cosmos DB account and containers for:
    - settings lookup
    - request persistence
  - Event Grid topic for `dataGenerator` publication
  - Key Vault for secrets and configuration references
  - Managed Identity assignment and RBAC role bindings
- Add application settings for:
  - container names,
  - Event Grid topic endpoint or resource reference,
  - Key Vault reference values,
  - telemetry instrumentation key / connection string if required.
- Keep the persistence owner singular: only the request-creator function should write the primary request container.
- If queues remain part of the architecture, model them as Service Bus resources rather than SQS.

## Observability

- Send all logs and metrics to **Application Insights**.
- Use structured logging with fields:
  - `module`
  - `operation`
  - `duration_ms`
  - `status`
  - correlation/request IDs
- Log key checkpoints:
  - request received,
  - validation outcome,
  - settings lookup result,
  - persistence success/failure,
  - Event Grid publish success/failure.
- Capture dependency telemetry for Cosmos DB and Event Grid calls.
- For HTTP failures, return the required JSON error shape without exposing stack traces.
- Include the generated `ddbId` in logs and error telemetry to correlate retries and failures.
