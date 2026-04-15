## Function Plan (Consumption/Premium/Flex)

- **Recommended plan: Consumption**
  - This module is event-driven, short-lived, and performs a single sequential workflow: read request data, transform, update state, publish downstream event.
  - Consumption is the best default for cost efficiency and autoscaling.
- **Upgrade to Premium only if needed**
  - Use Premium if cold start sensitivity becomes material, if VNet integration is required, or if downstream latency needs more predictable warm execution.
- **Flex**
  - Flex is also viable if the broader platform standardizes on Flex for event-driven workloads, but it is not required by the BRD.
- **Runtime shape**
  - Single Azure Function App hosting one main event-driven function for the `data_generator` workflow.
  - Keep the module split into small helpers for:
    - request lookup
    - payload transformation
    - DynamoDB-to-Cosmos persistence adapter
    - downstream event publish
    - error handling

## Trigger Bindings (one entry per source AWS trigger)

- **EventBridge event with `detail.ddbId`**
  - Azure mapping: **Event Grid trigger**
  - Use an Event Grid subscription from the upstream `request_creator` equivalent event source to invoke this function.
  - Event payload should preserve the `detail` envelope so the function can read `detail.ddbId`.
- **Downstream validator publish path**
  - Azure mapping: **Event Grid output binding** or Event Grid client publish
  - After successful persistence, emit an event containing the same `ddbId` to the validator topic/subscription path.
- **SQS queue consumers listed in edges**
  - `sqs_queue:<unknown:bb43b9e4>` → **Service Bus queue trigger**
  - `sqs_queue:<unknown:ef951409>` → **Service Bus queue trigger**
  - If these queues are not actually used by the runtime entrypoint, keep them as separate bindings only if the module truly owns them; otherwise route them to the owning function.
- **SNS topic listed in edges**
  - `sns_topic:<unknown:c6cc3dc0>` → **Event Grid topic** or **Service Bus topic**
  - If the publish is fan-out/event style, prefer Event Grid.
  - If ordered, durable, replayable pub/sub is needed, prefer Service Bus topic.

## State Mapping (one entry per AWS resource the module touches)

- `dynamodb_table:<unknown:14031bd5>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:14af6c1a>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:212cef05>` → **Cosmos DB NoSQL container**  
  - This appears to be the main write target for transformed request state.
- `dynamodb_table:<unknown:7f721743>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:9df589fe>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:bbab3a38>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:c5f15d58>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:d70b2210>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:fe06ed03>` → **Cosmos DB NoSQL container**
- `dynamodb_table:<unknown:fedcae95>` → **Cosmos DB NoSQL container**
- `s3_bucket:<unknown:4a72a035>` → **Blob container**
- `s3_bucket:<unknown:811a67cb>` → **Blob container**
- `s3_bucket:get_object` → **Blob storage read operation**
- `sns_topic:<unknown:c6cc3dc0>` → **Event Grid topic** or **Service Bus topic**
- `sqs_queue:<unknown:6d07956e>` → **Service Bus queue**
- `sqs_queue:<unknown:bb43b9e4>` → **Service Bus queue**
- `sqs_queue:<unknown:ef951409>` → **Service Bus queue**

## Secrets

- Store all non-public configuration in **Azure Key Vault**.
- Likely secret/config items to migrate:
  - Cosmos DB connection details if not using Managed Identity-only access
  - Service Bus connection strings if not using Managed Identity
  - Event Grid topic keys only if key-based publishing is required
  - Any upstream/shared service credentials referenced by `services.config`
- Prefer **Managed Identity + RBAC** over secrets wherever possible:
  - Key Vault access via Managed Identity
  - Cosmos DB data-plane access via Entra ID / RBAC where supported
  - Service Bus access via Managed Identity
  - Storage access via Managed Identity
- Do not embed table names, queue names, or endpoint URLs as secrets; use configuration settings or Key Vault references only for sensitive values.

## Identity

- Use a **system-assigned Managed Identity** for the Function App by default.
- Grant least-privilege access to:
  - Cosmos DB container read/write for the request state container
  - Blob Storage read/write for any storage-backed artifacts
  - Service Bus send rights for downstream validator/event publication
  - Event Grid publish rights if publishing directly to a topic
  - Key Vault secret get/list only as needed
- Recommended role pattern:
  - `Cosmos DB Built-in Data Contributor` or equivalent scoped to the target container/database
  - `Storage Blob Data Contributor` scoped to required containers
  - `Azure Service Bus Data Sender` scoped to the target namespace/topic/queue
  - `Key Vault Secrets User` scoped to the vault
- If the module must read from multiple state containers, keep the permissions scoped per container/database rather than at subscription level.

## IaC (Bicep)

- Create one Azure Function App with:
  - runtime appropriate for the implementation language
  - Application Insights enabled
  - system-assigned Managed Identity
  - app settings for container names, topic names, and environment-specific config
- Provision supporting resources:
  - **Cosmos DB account**
  - **Cosmos DB database and containers** for the DynamoDB-equivalent state
  - **Storage account / blob containers** for S3-equivalent artifacts
  - **Event Grid topic/subscription** for upstream EventBridge and downstream validator events
  - **Service Bus namespace/queues/topics** if any SQS/SNS semantics require queue/topic behavior
  - **Key Vault** for secrets
  - **Application Insights** for telemetry
- Use Bicep modules for:
  - `functionApp`
  - `cosmos`
  - `storage`
  - `eventGrid`
  - `serviceBus`
  - `keyVault`
- Ensure the deployment assigns RBAC roles to the Function App identity.
- Keep infrastructure names parameterized and environment-specific.

## Observability

- Use **Application Insights** for all function telemetry.
- Emit structured logs with consistent fields:
  - `module`
  - `operation`
  - `duration_ms`
  - `status`
  - `ddbId`
  - correlation/event ID
- Recommended logging points:
  - event received
  - request lookup started/completed
  - transformation started/completed
  - state update started/completed
  - downstream event publish started/completed
  - failure path with exception context
- Propagate correlation IDs from the Event Grid message into logs and outbound events.
- Track custom metrics:
  - transformation latency
  - Cosmos read/write latency
  - downstream publish latency
  - success/failure counts
- Alert on:
  - repeated missing `ddbId`
  - request-not-found errors
  - transformation failures
  - persistence failures
  - downstream event publish failures