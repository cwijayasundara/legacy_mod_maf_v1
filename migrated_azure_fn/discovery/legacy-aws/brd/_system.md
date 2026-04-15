 ## Purpose
This system consists of four Lambda modules that form a staged workflow around request generation, validation, queue/status handling, and filing-related data generation.

- `request_creator` creates request records and related artifacts.
- `validation` reads those requests/data, validates them, and persists validation outcomes.
- `filing_queue_status` reads queue/state data, updates filing queue status information, and publishes follow-up work.
- `data_generator` consumes queue work, assembles generated data from source tables and S3, persists output, and publishes downstream notifications/messages.

Across modules, the shared pattern is: read from upstream AWS data stores, transform or validate data, write to a module-owned target store, and emit events/messages to SNS and/or SQS for the next stage.

## Triggers
- `request_creator` is triggered by its Lambda invocation and may also be driven by SQS messages it consumes.
- `validation` is triggered by its Lambda invocation and may also be driven by SQS messages it consumes.
- `filing_queue_status` is triggered by its Lambda invocation and may also be driven by SQS messages it consumes.
- `data_generator` is triggered by its Lambda invocation and may also be driven by SQS messages it consumes.

The workflow is event-driven and multi-hop:
1. A request is created.
2. Validation processes the request and writes validation output.
3. Filing queue status updates are computed from stored state and may enqueue downstream work.
4. Data generation consumes queue work, reads source data, writes generated artifacts, and emits events for subsequent consumers.

## Inputs
Shared input categories across the modules include:

- DynamoDB tables used as source state or lookup data
  - `data_generator` reads from multiple DynamoDB tables and writes to one DynamoDB table.
  - `filing_queue_status` reads from multiple DynamoDB tables and writes to one DynamoDB table.
  - `request_creator` reads from multiple DynamoDB tables and writes to one DynamoDB table.
  - `validation` reads from multiple DynamoDB tables and writes to one DynamoDB table.
- S3 buckets used as source objects and output storage
  - Each module reads from one S3 bucket and `get_object`.
  - `data_generator`, `filing_queue_status`, `request_creator`, and `validation` each write to one S3 bucket.
- SQS queue messages
  - `data_generator` consumes two SQS queues and produces one SQS queue.
  - `filing_queue_status` consumes two SQS queues and produces one SQS queue.
  - `request_creator` consumes one SQS queue and produces one SQS queue.
  - `validation` consumes two SQS queues and produces one SQS queue.
- Imported shared code
  - `services`
  - `services.aws_clients`
  - `services.config`
  - `services.constants`
  - `services.helper`
  - `services.transformer`
  - `services.validators` only for `validation`

## Outputs
Module outputs fall into three categories:

- Persistent state writes
  - Each module writes to one DynamoDB table.
  - Each module writes to one S3 bucket.
- Eventing outputs
  - `data_generator` produces to one SNS topic and one SQS queue.
  - `filing_queue_status` produces to one SNS topic and one SQS queue.
  - `request_creator` produces to one SNS topic and one SQS queue.
  - `validation` produces to one SNS topic and one SQS queue.
- Derived runtime outputs
  - Each module likely returns or logs operational results from the Lambda execution, but the shared dependency edges only confirm AWS-side persistence and messaging outputs.

## Business Rules
- Each module follows a read-transform-write pattern: it reads source tables and/or objects, computes derived state, then writes results to its owned destination store.
- Queue-based orchestration is central: modules consume SQS messages to continue processing and produce SQS messages to hand off work to another stage.
- SNS is used as a publish mechanism in all four modules, implying fan-out or notification behavior after core processing completes.
- `validation` is the only module that imports `services.validators`, indicating it performs explicit validation logic beyond generic transformation.
- `data_generator` is the only module that imports `services.transformer`, indicating it performs data shaping/assembly work before output.

## Side Effects
- `data_generator`
  - Reads from DynamoDB tables: `<unknown:14031bd5>`, `<unknown:14af6c1a>`, `<unknown:7f721743>`, `<unknown:9df589fe>`, `<unknown:bbab3a38>`, `<unknown:c5f15d58>`, `<unknown:d70b2210>`, `<unknown:fe06ed03>`, `<unknown:fedcae95>`
  - Writes to DynamoDB table: `<unknown:212cef05>`
  - Reads from S3 bucket: `<unknown:4a72a035>` and `get_object`
  - Writes to S3 bucket: `<unknown:811a67cb>`
  - Imports: `services`, `services.aws_clients`, `services.config`, `services.constants`, `services.helper`, `services.transformer`
  - Produces to SNS topic: `<unknown:c6cc3dc0>`
  - Produces to SQS queue: `<unknown:6d07956e>`
  - Consumes SQS queues: `<unknown:bb43b9e4>`, `<unknown:ef951409>`

- `filing_queue_status`
  - Reads from DynamoDB tables: `<unknown:05060438>`, `<unknown:0a8c1172>`, `<unknown:10940326>`, `<unknown:491e9a30>`, `<unknown:4ad5977e>`, `<unknown:8425985b>`, `<unknown:999cbbc9>`, `<unknown:bc835f4a>`, `<unknown:c67c3b06>`
  - Writes to DynamoDB table: `<unknown:9326a15c>`
  - Reads from S3 bucket: `<unknown:0aba5933>` and `get_object`
  - Writes to S3 bucket: `<unknown:7cfb575f>`
  - Imports: `services`, `services.aws_clients`, `services.config`, `services.constants`, `services.helper`
  - Produces to SNS topic: `<unknown:21c94b21>`
  - Consumes SQS queues: `<unknown:00b2db8f>`, `<unknown:294ef9eb>`
  - Produces to SQS queue: `<unknown:9dd11495>`

- `request_creator`
  - Reads from DynamoDB tables: `<unknown:0c296b2b>`, `<unknown:1a04c780>`, `<unknown:511dce5f>`, `<unknown:5ef17d53>`, `<unknown:798bb231>`, `<unknown:89a55f48>`, `<unknown:d425d1be>`, `<unknown:d8d0a56d>`, `<unknown:e0da9853>`
  - Writes to DynamoDB table: `<unknown:91c11e2e>`
  - Reads from S3 bucket: `<unknown:49455859>` and `get_object`
  - Writes to S3 bucket: `<unknown:c5d90f3d>`
  - Imports: `services`, `services.aws_clients`, `services.config`, `services.constants`, `services.helper`
  - Produces to SNS topic: `<unknown:8b05176d>`
  - Consumes SQS queue: `<unknown:12f44477>`
  - Produces to SQS queue: `<unknown:53539e15>`
  - Consumes SQS queue: `<unknown:c0d18561>`

- `validation`
  - Reads from DynamoDB tables: `<unknown:0777f615>`, `<unknown:1fe03425>`, `<unknown:2c69309e>`, `<unknown:2fda0f5f>`, `<unknown:a53cf482>`, `<unknown:b9b1d13e>`, `<unknown:ca4ec176>`, `<unknown:e81fe267>`, `<unknown:ff66c0de>`
  - Writes to DynamoDB table: `<unknown:229f3a26>`
  - Writes to S3 bucket: `<unknown:41bdf426>`
  - Reads from S3 bucket: `<unknown:9c31390d>` and `get_object`
  - Imports: `services`, `services.aws_clients`, `services.config`, `services.constants`, `services.helper`, `services.validators`
  - Produces to SNS topic: `<unknown:3824d1de>`
  - Consumes SQS queues: `<unknown:24726cb7>`, `<unknown:e3aba6c2>`
  - Produces to SQS queue: `<unknown:8d415f52>`

## Error Paths
- If any required upstream DynamoDB item, S3 object, or SQS message is missing or malformed, the module must fail or skip processing according to its internal handling logic; the edge list confirms dependencies but not the exact recovery behavior.
- If a module cannot read from its source S3 bucket or `get_object` call, downstream writes and publications for that invocation cannot complete.
- If a module cannot write to its owned DynamoDB table, S3 bucket, SNS topic, or SQS queue, the workflow stage cannot reliably hand off to the next stage.
- If imported shared services (`services.*`) fail to load or behave unexpectedly, all four modules are affected because they rely on shared configuration, AWS client wiring, and helper logic.

## Non-Functionals
- Latency: Each module is designed for event-driven, per-invocation processing rather than long-running batch orchestration.
- Idempotency: Because modules can consume SQS messages and write to persistent stores, repeated delivery may occur; the workflow should be treated as potentially retryable and therefore should tolerate duplicate invocation patterns where the implementation supports it.
- Ordering: SQS-based handoffs imply that message ordering may matter within a queue, but the edge data alone does not guarantee FIFO semantics; downstream consumers must not assume strict global ordering across modules.
- Scalability: The design is horizontally scalable at the Lambda level, with each module independently consuming events and publishing follow-on work.

## PII/Compliance
- The dependency graph shows storage, queueing, and publication to AWS services, but it does not expose the actual payload schema or whether personal data is present.
- Because each module reads from and writes to DynamoDB and S3, payloads may contain regulated business data; handling must respect whatever data classification is encoded in the unseen module logic.
- Shared imports include configuration and helpers, which may control encryption, bucket names, or redaction behavior, but no direct compliance mechanism is visible from the edges alone.
- No explicit PII fields are identifiable from the provided edges, so no specific personal-data handling can be asserted from this information alone.