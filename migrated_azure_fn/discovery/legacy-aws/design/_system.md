## Function Plan
- Treat `request_creator`, `validation`, `filing_queue_status`, and `data_generator` as four bounded-context Azure Functions modules, each owning one stage of the workflow.
- Use one function app per module or a clearly separated function group per module to preserve the current read-transform-write ownership model.
- Preserve the staged handoff:
  - `request_creator` starts request intake and emits the first downstream work item.
  - `validation` validates request/state and persists validation outcomes.
  - `filing_queue_status` computes queue/status transitions and publishes follow-up work.
  - `data_generator` assembles generated data, persists outputs, and emits downstream notifications.
- Keep upstream reads behind module-local anti-corruption layers so Azure-native code never leaks AWS-specific concepts into business logic.
- Use queue-triggered functions for SQS-driven hops and HTTP-triggered functions for direct invocation paths.

## Trigger Bindings
- `request_creator`
  - HTTP trigger for direct invocation.
  - Service Bus queue trigger for the current SQS-driven path.
  - Service Bus output binding for its downstream queue handoff.
- `validation`
  - HTTP trigger for direct invocation.
  - Service Bus queue trigger for its two queue inputs.
  - Service Bus output binding for downstream queue publication.
- `filing_queue_status`
  - HTTP trigger for direct invocation.
  - Service Bus queue trigger for its two queue inputs.
  - Service Bus output binding for downstream queue publication.
- `data_generator`
  - HTTP trigger for direct invocation.
  - Service Bus queue trigger for its two queue inputs.
  - Service Bus output binding for downstream queue publication.
- For SNS fan-out, prefer Event Grid when the event is notification-like; use Service Bus topics when the current consumers require durable subscription semantics.

## State Mapping
- `data_generator`: DynamoDB tables `<unknown:14031bd5>`, `<unknown:14af6c1a>`, `<unknown:7f721743>`, `<unknown:9df589fe>`, `<unknown:bbab3a38>`, `<unknown:c5f15d58>`, `<unknown:d70b2210>`, `<unknown:fe06ed03>`, `<unknown:fedcae95>` -> Cosmos DB NoSQL containers.
- `data_generator`: DynamoDB table `<unknown:212cef05>` -> Cosmos DB NoSQL container.
- `data_generator`: S3 bucket `<unknown:4a72a035>` -> Blob Storage container.
- `data_generator`: S3 bucket `<unknown:811a67cb>` -> Blob Storage container.
- `data_generator`: SQS queues `<unknown:bb43b9e4>`, `<unknown:ef951409>`, `<unknown:6d07956e>` -> Service Bus queues.
- `data_generator`: SNS topic `<unknown:c6cc3dc0>` -> Event Grid topic or Service Bus topic.
- `filing_queue_status`: DynamoDB tables `<unknown:05060438>`, `<unknown:0a8c1172>`, `<unknown:10940326>`, `<unknown:491e9a30>`, `<unknown:4ad5977e>`, `<unknown:8425985b>`, `<unknown:999cbbc9>`, `<unknown:bc835f4a>`, `<unknown:c67c3b06>` -> Cosmos DB NoSQL containers.
- `filing_queue_status`: DynamoDB table `<unknown:9326a15c>` -> Cosmos DB NoSQL container.
- `filing_queue_status`: S3 bucket `<unknown:0aba5933>` -> Blob Storage container.
- `filing_queue_status`: S3 bucket `<unknown:7cfb575f>` -> Blob Storage container.
- `filing_queue_status`: SQS queues `<unknown:00b2db8f>`, `<unknown:294ef9eb>`, `<unknown:9dd11495>` -> Service Bus queues.
- `filing_queue_status`: SNS topic `<unknown:21c94b21>` -> Event Grid topic or Service Bus topic.
- `request_creator`: DynamoDB tables `<unknown:0c296b2b>`, `<unknown:1a04c780>`, `<unknown:511dce5f>`, `<unknown:5ef17d53>`, `<unknown:798bb231>`, `<unknown:89a55f48>`, `<unknown:d425d1be>`, `<unknown:d8d0a56d>`, `<unknown:e0da9853>` -> Cosmos DB NoSQL containers.
- `request_creator`: DynamoDB table `<unknown:91c11e2e>` -> Cosmos DB NoSQL container.
- `request_creator`: S3 bucket `<unknown:49455859>` -> Blob Storage container.
- `request_creator`: S3 bucket `<unknown:c5d90f3d>` -> Blob Storage container.
- `request_creator`: SQS queues `<unknown:12f44477>`, `<unknown:c0d18561>`, `<unknown:53539e15>` -> Service Bus queues.
- `request_creator`: SNS topic `<unknown:8b05176d>` -> Event Grid topic or Service Bus topic.
- `validation`: DynamoDB tables `<unknown:0777f615>`, `<unknown:1fe03425>`, `<unknown:2c69309e>`, `<unknown:2fda0f5f>`, `<unknown:a53cf482>`, `<unknown:b9b1d13e>`, `<unknown:ca4ec176>`, `<unknown:e81fe267>`, `<unknown:ff66c0de>` -> Cosmos DB NoSQL containers.
- `validation`: DynamoDB table `<unknown:229f3a26>` -> Cosmos DB NoSQL container.
- `validation`: S3 bucket `<unknown:9c31390d>` -> Blob Storage container.
- `validation`: S3 bucket `<unknown:41bdf426>` -> Blob Storage container.
- `validation`: SQS queues `<unknown:24726cb7>`, `<unknown:e3aba6c2>`, `<unknown:8d415f52>` -> Service Bus queues.
- `validation`: SNS topic `<unknown:3824d1de>` -> Event Grid topic or Service Bus topic.

## Secrets
- Move all AWS credentials and configuration secrets from `services.config` / `services.aws_clients` dependencies to Azure Key Vault.
- Store connection strings, API keys, and any environment-specific routing parameters in Key Vault references or app settings backed by Key Vault.
- Prefer managed identity plus RBAC over secret-based access wherever possible.
- If the current implementation reads service endpoints or encryption settings from config, split those into non-secret app settings and secret Key Vault entries.

## Identity
- Replace IAM role assumptions with Azure Managed Identity for all function apps.
- Grant least-privilege access to:
  - Cosmos DB data plane for the owning module’s containers.
  - Blob Storage data plane for the module’s buckets/containers.
  - Service Bus send/receive permissions for the module’s queues/topics.
  - Event Grid publish permissions where SNS fan-out is retained as Event Grid.
- Keep one identity boundary per module to preserve the single-owner write model for persistent state.

## IaC
- Provision each module’s Azure Functions, bindings, and dependencies in IaC rather than manual portal configuration.
- Recommended stack: Bicep or Terraform with separate modules for:
  - Function App
  - Storage account
  - Service Bus namespace, queues, and topics
  - Cosmos DB account and containers
  - Blob containers
  - Key Vault
  - Application Insights
- Define explicit ownership so each module writes only to its designated Cosmos DB container and Blob container.
- Model the AWS-to-Azure mapping in IaC names and outputs to keep the strangler seam clear during coexistence.
- If coexistence is required, route upstream AWS events to Azure ingress through a bridge layer, then migrate consumers one module at a time.

## Observability
- Use Application Insights for all modules in place of CloudWatch.
- Emit structured logs with consistent fields:
  - `module`
  - `operation`
  - `duration_ms`
  - `status`
  - `correlation_id`
- Propagate correlation IDs across HTTP, queue, and event boundaries.
- Add dependency telemetry for Cosmos DB, Blob Storage, Service Bus, and Event Grid calls.
- Track per-stage success/failure rates so the strangler seam can be measured during migration.
- Alert on poison messages, repeated retries, and missing upstream state to catch anti-corruption failures early.