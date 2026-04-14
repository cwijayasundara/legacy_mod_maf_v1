## Purpose
Sends notifications.
## Triggers
- SNS: payment-events
## Inputs
SNS record.
## Outputs
Webhook POST.
## Business Rules
- Retry on webhook failure.
## Side Effects
- reads secrets_manager_secret:webhook/url
## Error Paths
- dead-letter after 3 retries.
## Non-Functionals
- Best-effort delivery.
## PII/Compliance
- Webhook URL is a secret.
