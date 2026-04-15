```markdown
# Migration Analysis: order-processor

## Summary
- Language: Python
- Complexity: HIGH
- Estimated effort: 12 hours
- Migration order priority: 1
- Inbound dependencies: None
- Outbound dependencies: AWS DynamoDB, S3, SQS

## AWS Dependencies
| AWS Service | SDK Package | Usage | Azure Equivalent | Azure SDK | Migration Notes |
|-------------|-------------|-------|------------------|-----------|-----------------|
| DynamoDB    | boto3       | Data storage | Cosmos DB | azure-cosmos | Requires schema migration |
| S3          | boto3       | File storage | Blob Storage | azure-storage-blob | Adapt storage operations |
| SQS         | boto3       | Message queue | Queue Storage | azure-storage-queue | Adjust message format |

## Business Logic
- Core functions: `lambda_handler`, `create_order`, `get_order`, `generate_receipt`, `response`
- Input/output contracts (request schema -> response schema):
  - `POST /orders`: JSON order input -> JSON order confirmation
  - `GET /orders/{id}`: order ID -> JSON order data
- Side effects (writes to DB, publishes events, uploads files):
  - Write order to DynamoDB
  - Upload receipt to S3
  - Send notification to SQS
- Edge cases found in code:
  - Invalid JSON payloads
  - Missing or invalid required fields
  - Non-existent order retrieval

## Inter-Service Dependencies
- Upstream (who calls us): Invoked via API Gateway
- Downstream (who we call): DynamoDB, S3, SQS for processing orders
- Shared libraries: None

## Recommended Migration Approach
- Migrate AWS SDK usage to Azure SDK equivalents.
- Adjust environment variable handling in Azure Functions.
- Transform API Gateway logic to Azure HTTP Trigger functions.
- Validate integration with Cosmos DB, Azure Blob Storage, and Azure Queue Storage.

## Risks & Blockers
- Data model changes required for Cosmos DB.
- Azure services behavior differences may need business logic adjustments.

## Learned Rules Applied
- [Pending to insert any existing learned rules relevant to this module]
```
