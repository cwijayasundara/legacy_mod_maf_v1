## Purpose
Receives orders.
## Triggers
- API Gateway POST /orders.
## Inputs
JSON body.
## Outputs
201 + order id.
## Business Rules
- Idempotent on order id.
## Side Effects
- writes dynamodb_table:Orders
- produces sqs_queue:payments-queue
## Error Paths
- returns 500 on DynamoDB failure.
## Non-Functionals
- p95 < 200ms.
## PII/Compliance
- Payment-related PII flagged for retention policy.
