## Function Plan (Consumption/Premium/Flex)

- **Recommended plan: Consumption**
  - The module is a single event-driven validator with short-lived synchronous work: one record read, one validation call, one record update, and optional queue publish.
  - No long-running processing, VNET requirement, or heavy warm-state dependency is indicated in the BRD.
- **Use Premium only if**:
  - the module must join a VNET,
  - the shared validator or downstream queue path requires consistently low cold-start latency,
  - or there are enterprise networking constraints around the storage/queue endpoints.
- **Use Flex only if**:
  - the migration target standardizes on Flex for event-driven workloads and you want simpler scaling controls than Consumption while preserving serverless semantics.

## Trigger Bindings (one entry per source AWS trigger)

- **EventBridge-style event** → **Event Grid trigger**
  - Source: prior `dataGenerator` step emits an event containing `detail.ddbId`
  - Azure design: Event Grid subscription to the processing topic/event source
  - Behavior: function exits early with a failure response when `detail.ddbId` is missing
- **No direct trigger from SQS/SNS/S3/DynamoDB streams**
  - These appear in the module edges as related dependencies, but the BRD describes the primary invocation path as event-based from the prior step
  - Any queue publish is a downstream side effect, not the inbound trigger for this module

## State Mapping (one entry per AWS resource the module touches)

- **dynamodb_table:<unknown:0777f615>** → **Cosmos DB NoSQL container**  
  Read path for the stored record associated with `ddbId`.
- **dynamodb_table:<unknown:229f3a26>** → **Cosmos DB NoSQL container**  
  Write path for validation status, validation errors, and final status updates.
- **dynamodb_table:<unknown:1fe03425>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; treat as a dependent NoSQL state store if used by shared validation/data access logic.
- **dynamodb_table:<unknown:2c69309e>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **dynamodb_table:<unknown:2fda0f5f>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **dynamodb_table:<unknown:a53cf482>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **dynamodb_table:<unknown:b9b1d13e>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **dynamodb_table:<unknown:ca4ec176>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **dynamodb_table:<unknown:e81fe267>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **dynamodb_table:<unknown:ff66c0de>** → **Cosmos DB NoSQL container**  
  Referenced in module edges; map as a read-only supporting state store.
- **s3_bucket:<unknown:41bdf426>** → **Blob Storage container**  
  Write-side dependency in the edges; if still required by the broader workflow, use Blob Storage plus Event Grid notifications.
- **s3_bucket:<unknown:9c31390d>** → **Blob Storage container**  
  Read-side dependency in the edges; use Blob Storage for object retrieval.
- **s3_bucket:get_object** → **Blob Storage SDK read**  
  Corresponds to object fetch operations against Azure Blob Storage.
- **sns_topic:<unknown:3824d1de>** → **Event Grid topic or Service Bus topic**  
  Outbound publish dependency; prefer Service Bus topic if delivery semantics and ordering matter more than broadcast.
- **sqs_queue:<unknown:24726cb7>** → **Service Bus queue**  
  Consumed dependency in module edges; map to a queue-triggered or queue-interacting Azure Service Bus entity as used by the broader chain.
- **sqs_queue:<unknown:8d415f52>** → **Service Bus queue**  
  Primary downstream queue for successful validations.
- **sqs_queue:<unknown:e3aba6c2>** → **Service Bus queue**  
  Consumed dependency in module edges; map to a Service Bus queue if this module or shared helpers read from it.

## Secrets

- Store runtime connection details in **Key Vault**:
  - Cosmos DB endpoint/key or use managed identity where supported
  - Service Bus connection settings if not fully identity-based
  - Any shared validator configuration secrets if they are not plain constants
- Prefer **managed identity + RBAC** over secret-based access wherever the Azure service supports it.
- Do not store validation payloads, `mergedJSON`, or validation errors in Key Vault.

## Identity

- Use **Managed Identity** for the Function App.
- Grant the identity:
  - read/write access to the Cosmos DB container(s) used for validation state
  - send access to the Service Bus queue used for downstream processing
  - read access to Blob Storage if the module’s shared dependencies still require the S3-equivalent paths
- If the shared validator depends on other platform services, scope permissions to the minimum required resources.
- The function should never use embedded credentials in code or configuration files.

## IaC (Bicep)

- Provision:
  - Function App on the selected plan
  - Event Grid subscription for the inbound `detail.ddbId` event source
  - Cosmos DB NoSQL account/container(s) for the validation record state
  - Service Bus queue for the successful-validation handoff
  - Key Vault for any unavoidable secrets
  - Application Insights for telemetry
- Bicep modules should be split by responsibility:
  - function host
  - messaging
  - data
  - secrets
  - monitoring
- Use a user-assigned or system-assigned managed identity on the Function App.
- Configure app settings for:
  - Cosmos DB container/database names
  - Service Bus entity names
  - Event Grid topic/subscription identifiers
  - validator configuration flags
- Keep resource names parameterized so the `validation` module can be deployed per environment without code changes.

## Observability

- Send all logs to **Application Insights**.
- Include structured fields consistently:
  - `module`
  - `operation`
  - `ddbId`
  - `duration_ms`
  - `status`
- Log at least these operations:
  - event received
  - missing `ddbId` early exit
  - record read
  - validation result
  - state update
  - downstream queue publish
  - error handling
- Include correlation IDs from the inbound Event Grid payload or execution context.
- Track failure categories separately:
  - missing identifier
  - record not found
  - validation failure
  - persistence failure
  - queue publish failure
- Emit custom metrics for:
  - validation success rate
  - validation failure rate
  - queue publish success/failure
  - end-to-end duration
- Never log raw `mergedJSON`, secrets, or full validation payloads.