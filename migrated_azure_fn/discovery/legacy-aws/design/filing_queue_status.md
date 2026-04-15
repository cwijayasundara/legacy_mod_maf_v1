## Function Plan
- **Azure Functions plan:** **Consumption** for the queue-driven handler, unless downstream helper calls require long-running I/O or higher VNet isolation, in which case move to **Premium**.
- Core function: `filing_queue_status` as a **Service Bus queue trigger** function that processes each message independently and emits per-message results for partial failure handling.
- Implement the Delaware COGS bypass as a fast-path branch inside the same function: if `jurisdiction == "DELAWARE"` and `serviceType == "COGS"`, publish directly to the filer destination without the normal concurrency gate.
- Keep the filing concurrency gate and bot status mutations in a single owner service/module to preserve state ownership.
- If batch semantics are required, prefer Service Bus batch-triggering or message settlement patterns that preserve per-record outcomes.

## Trigger Bindings
- **AWS SQS queue (`sqs_queue:<unknown:00b2db8f>`) -> Azure Service Bus queue trigger**
  - Primary inbound filing queue mapped to a Service Bus queue trigger.
  - Use a poison/dead-letter strategy for messages that repeatedly fail validation or processing.
- **AWS SQS queue (`sqs_queue:<unknown:294ef9eb>`) -> Azure Service Bus queue trigger**
  - Secondary inbound queue mapped the same way if it represents another filing intake path or retry lane.
- **AWS SNS topic (`sns_topic:<unknown:21c94b21>`) -> Azure Event Grid or Service Bus topic output**
  - Downstream filer event publication maps to Event Grid by default; use Service Bus topic if the consumer model is queue/topic-based and requires ordered durable delivery.
- **AWS SQS queue (`sqs_queue:<unknown:9dd11495>`) -> Azure Service Bus queue output**
  - Any explicit queue handoff to a downstream worker should be a Service Bus queue output binding or SDK send to the destination queue.
- **SQS partial batch failure handling -> Service Bus message settlement**
  - Model per-message success/failure using explicit message completion, abandon, or dead-letter actions rather than failing the entire invocation.

## State Mapping
- **`dynamodb_table:<unknown:05060438>` -> Cosmos DB NoSQL container**
  - Read-only status/config lookup used by filing queue gating logic.
- **`dynamodb_table:<unknown:0a8c1172>` -> Cosmos DB NoSQL container**
  - Read-only lookup for helper-driven status or routing state.
- **`dynamodb_table:<unknown:10940326>` -> Cosmos DB NoSQL container**
  - Read-only lookup for concurrency or filing metadata.
- **`dynamodb_table:<unknown:491e9a30>` -> Cosmos DB NoSQL container**
  - Read-only lookup for bot or filing status state.
- **`dynamodb_table:<unknown:4ad5977e>` -> Cosmos DB NoSQL container**
  - Read-only lookup for supporting workflow data.
- **`dynamodb_table:<unknown:8425985b>` -> Cosmos DB NoSQL container**
  - Read-only lookup for helper-managed state.
- **`dynamodb_table:<unknown:9326a15c>` -> Cosmos DB NoSQL container**
  - Writable owner container for filing status mutation, including `IN_PROGRESS`, bot status data, and active filing counter updates.
- **`dynamodb_table:<unknown:999cbbc9>` -> Cosmos DB NoSQL container**
  - Read-only lookup for filing workflow coordination.
- **`dynamodb_table:<unknown:bc835f4a>` -> Cosmos DB NoSQL container**
  - Read-only lookup for bot availability or routing context.
- **`dynamodb_table:<unknown:c67c3b06>` -> Cosmos DB NoSQL container**
  - Read-only lookup for additional helper state.
- **`s3_bucket:<unknown:0aba5933>` -> Azure Blob Storage container**
  - Read path via blob client/get-object equivalent for helper data or artifacts.
- **`s3_bucket:<unknown:7cfb575f>` -> Azure Blob Storage container**
  - Write path for generated artifacts or workflow outputs.
- **`sqs_queue:<unknown:00b2db8f>` -> Azure Service Bus queue**
  - Main inbound queue for filing initiation messages.
- **`sqs_queue:<unknown:294ef9eb>` -> Azure Service Bus queue**
  - Secondary inbound/retry queue or alternate intake lane.
- **`sqs_queue:<unknown:9dd11495>` -> Azure Service Bus queue**
  - Downstream queue for deferred or routed filing work.
- **`sns_topic:<unknown:21c94b21>` -> Azure Event Grid topic or Service Bus topic**
  - Event publication target for filer workflow fan-out.

## Secrets
- Store all connection strings, broker credentials, and storage access settings in **Azure Key Vault**.
- Prefer Azure-managed identity access to Service Bus, Cosmos DB, Blob Storage, and Event Grid so secrets are minimized.
- Any legacy helper configuration that references AWS credentials should be removed or replaced with Key Vault references.
- Do not store filing payloads, `ddbId` values, or business data in Key Vault.

## Identity
- Use a **managed identity** for the Function App.
- Grant least-privilege RBAC:
  - Service Bus Data Sender/Receiver as needed
  - Cosmos DB data access roles for the specific containers
  - Storage Blob Data Contributor or Reader as needed
  - Event Grid publisher permissions where applicable
  - Key Vault Secrets User for secret retrieval
- Keep the state-mutating owner service as the only component allowed to write the Cosmos DB container that tracks filing status and bot concurrency.

## IaC (Bicep)
- Define a Function App with a Service Bus queue trigger configuration.
- Provision:
  - Function App
  - App Service Plan only if Premium is chosen
  - Service Bus namespace, queues, and optional topic/subscriptions
  - Cosmos DB account and the mapped containers
  - Storage account and blob containers
  - Key Vault
  - Application Insights
  - User-assigned or system-assigned managed identity
- Add app settings as Key Vault references where possible.
- Configure host settings for:
  - retry behavior
  - Service Bus dead-letter handling
  - logging and telemetry sampling
- Model the writable filing status container as a single owner resource to avoid duplicate write paths.

## Observability
- Send all logs to **Application Insights**.
- Use structured logging with these fields at minimum:
  - `module`
  - `operation`
  - `duration_ms`
  - `status`
  - correlation ID
  - `ddbId` when safe to log
- Emit separate traces for:
  - message received
  - JSON validation failure
  - Delaware COGS bypass
  - bot busy retry path
  - filing start success
  - downstream event publication
  - unexpected exception
- Capture dependency telemetry for Service Bus, Cosmos DB, Blob Storage, and Event Grid calls.
- Track dead-letter counts and retry rates to detect concurrency bottlenecks.
- Avoid logging sensitive payload contents, secrets, or regulated business data.