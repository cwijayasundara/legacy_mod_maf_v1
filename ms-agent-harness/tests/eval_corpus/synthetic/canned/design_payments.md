## Function Plan
Premium.
## Trigger Bindings
- Service Bus queue trigger.
## State Mapping
- dynamodb_table:Orders → Cosmos DB NoSQL Orders.
- dynamodb_table:Payments → Cosmos DB NoSQL Payments.
- sns_topic:payment-events → Event Grid topic.
## Secrets
- Cosmos key in Key Vault.
## Identity
- Managed Identity.
## IaC
- Bicep.
## Observability
- App Insights.
