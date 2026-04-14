## Function Plan
Flex consumption.
## Trigger Bindings
- HTTP trigger.
## State Mapping
- dynamodb_table:Orders → Cosmos DB NoSQL container Orders.
- sqs_queue:payments-queue → Service Bus queue payments-queue.
## Secrets
- Cosmos key in Key Vault.
## Identity
- Managed Identity.
## IaC
- Bicep.
## Observability
- App Insights.
