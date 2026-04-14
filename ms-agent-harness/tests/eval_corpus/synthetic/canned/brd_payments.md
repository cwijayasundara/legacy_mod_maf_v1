## Purpose
Processes payments.
## Triggers
- SQS: payments-queue
## Inputs
Message with order id.
## Outputs
Payment record.
## Business Rules
- One payment per order.
## Side Effects
- reads dynamodb_table:Orders
- writes dynamodb_table:Payments
- produces sns_topic:payment-events
## Error Paths
- retries on transient failure.
## Non-Functionals
- Ordering preserved per-order.
## PII/Compliance
- No PAN stored.
