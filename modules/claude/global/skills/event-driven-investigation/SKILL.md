---
name: event-driven-investigation
description: Investigation methodology for event-driven, pub-sub, and queue-based systems. Use when the task involves queue, queue worker, queue consumer, pub/sub, topic, subscriber, publisher, event-driven, event handler, event bus, event subscriber, message-driven, message handler, SQS, SNS, Kafka, RabbitMQ, BullMQ, Sidekiq, Celery, NATS, EventBridge, Google Pub/Sub, Redis streams, Lambda triggered by queue/topic, NestJS @EventPattern, @MessagePattern, or equivalent decorator-based handlers.
---

# Event-Driven Investigation

$ARGUMENTS

## Core Failure Mode

**Caller-tracing methodology assumes synchronous call graphs. Event-driven systems are designed to defeat this.**

Producers and consumers are decoupled by construction. Grep for function callers, find none, conclude "no users" — wrong. The producer enqueues to a channel; the runtime triggers the consumer. Standard caller-tracing on a consumer finds nothing because there is no direct import or function call to find. The trigger flows through a channel identifier, not a code path.

Always perform both consumer-side discovery AND producer-side discovery as distinct, independent sweeps.

---

## Trigger Keywords

Load this skill and apply the four-phase methodology when the task description or codebase mentions any of:

**Queue/worker patterns:** queue, queue worker, queue consumer, job queue, job worker, deferred job

**Pub/sub patterns:** pub/sub, topic, subscriber, publisher, fanout, broadcast

**Event patterns:** event-driven, event handler, event bus, event subscriber, event listener, event emitter (infrastructure-level, not in-process)

**Message patterns:** message-driven, message handler, message broker, message bus

**Specific stacks:** SQS, SNS, Kafka, KafkaJS, RabbitMQ, AMQP, BullMQ, Bull, Sidekiq, Celery, NATS, JetStream, EventBridge, Google Pub/Sub, Redis streams, NATS streaming, Lambda (when triggered by SQS event source, SNS, EventBridge, etc.)

**Framework decorators:** `@EventPattern`, `@MessagePattern`, `@SqsMessage`, `@KafkaListener`, `@RabbitMQListener`, or any decorator-based handler pattern

---

## The Four-Phase Methodology

### Phase 1: Identify the Trigger Contract

For each consumer, document:

1. **Channel/queue/topic identifier** — the exact name the consumer subscribes to. Capture both the full ARN (e.g., `arn:aws:sqs:us-east-1:123456789:my-queue`) and the short name (`my-queue`) when both forms appear. The consumer's own code is the most reliable source; check the subscription declaration, `@EventPattern` decorator, `queueUrl`, `topic`, or equivalent.

2. **Message shape / event schema** — what fields does the consumer expect in the payload? Document the type definition, interface, or example message structure. This is required for producer-side matching (a producer sending to the right queue with the wrong schema is a partial match).

3. **Trigger mechanism** — how is the consumer invoked? Lambda event source mapping, polling loop, framework-managed subscription, cron-triggered batch drain, etc. Different mechanisms carry different operational constraints.

The consumer's declared subscription is the ground truth. Do not rely on README claims alone — verify by reading the consumer's source.

---

### Phase 2: Producer-Side Discovery

**This is a separate sweep from caller tracing. Run it independently.**

Grep the channel/queue/topic identifier from Phase 1 across the **entire repository scope**, including:

- All service/application directories
- Sibling component directories (lambdas, workers, microservices at the same depth as the consumer)
- Migration and one-off script directories (`scripts/`, `db/`, `migrations/`, `ops/`, `tools/`)
- IaC and infrastructure directories (`terraform/`, `infra/`, `cdk/`, `pulumi/`, `cloudformation/`)
- Scheduled job definitions (cron configs, Kubernetes CronJobs, ECS scheduled tasks)
- CI/CD pipeline definitions (`.github/`, `.buildkite/`, `Jenkinsfile`)

**If the codebase spans multiple repositories** (e.g., monorepo + separate infra repo, microservices split across repos), the sweep MUST span all of them. A producer in a sibling repo is still a producer.

Use write-pattern grep patterns specific to the messaging technology. See § Grep Patterns by Stack below.

Cross-check infrastructure for producer-side access:
- **AWS:** who has IAM `sqs:SendMessage`, `sns:Publish`, `events:PutEvents` on the relevant resource?
- **GCP:** who has Pub/Sub `pubsub.topics.publish` binding?
- **Kafka/RabbitMQ:** who has producer-role access to the broker?

IAM/RBAC cross-checks reveal producers that may not use the short queue name directly (they may derive it from an environment variable or SSM parameter — trace those too).

---

### Phase 3: Documentation as Hypothesis, Not Answer

When a README, inline comment, design doc, or ADR makes a definitive negative claim about system behavior — "no callers," "deprecated," "manual only," "unused," "triggered externally," "never called in production" — treat it as a **hypothesis to verify empirically**, not an answer.

Always run the Phase 2 producer-side sweep regardless of what documentation says. Documentation becomes stale; code does not lie about what it imports.

**If documentation and empirical evidence disagree:**
- Empirical evidence wins.
- Flag the documentation as stale.
- Include a specific note in findings: "README claims X; empirical sweep found Y — documentation requires update."

Be especially skeptical of:
- Old, lightly maintained, or unattributed documentation
- Documentation written before a system was wired up
- README sections that describe the intended future state, not the current state

The goal is synthesis from evidence, not narration of what someone wrote.

---

### Phase 4: Synthesis

Report the complete picture — both sides:

1. **Consumer(s):** what subscribes, on which channel, with what trigger mechanism
2. **Producer(s):** what enqueues/publishes, from which code path, with what payload
3. **Trigger contract:** channel identifier, message schema, trigger mechanism
4. **Documentation alignment:** any docs that contradict the empirical findings — flag for update

Do not report only one side. A consumer without a producer is an operational mystery. A producer without a consumer is a data-loss risk. Both gaps are findings.

---

## Grep Patterns by Stack

Use these patterns in Phase 2 producer-side discovery. Run against the full repo scope.

| Stack | Write-side patterns to grep |
|---|---|
| **AWS SQS** | `SendMessageCommand`, `sendMessage`, `sqs.send_message`, `sqs:SendMessage` |
| **AWS SNS** | `PublishCommand`, `sns.publish`, `sns:Publish` |
| **AWS EventBridge** | `PutEventsCommand`, `events.put_events`, `putEvents`, `events:PutEvents` |
| **Kafka / KafkaJS** | `producer.send`, `kafka.send`, `@kafkajs/producer`, `kafkaProducer` |
| **RabbitMQ / AMQP** | `channel.publish`, `channel.sendToQueue`, `amqp.connect`, `amqplib` |
| **BullMQ** | `queue.add`, `new Queue(`, `bullmq`, `addJob` |
| **Sidekiq** | `.perform_async`, `.perform_later`, `.perform_in` |
| **Celery** | `.delay(`, `.apply_async(`, `@task`, `@shared_task` |
| **NATS** | `nats.publish`, `js.publish`, `nc.publish`, `nats.connect` |
| **Google Pub/Sub** | `pubsub.publish`, `topic.publish`, `PublisherClient` |
| **Redis streams** | `XADD`, `xadd`, `redis.xadd` |

When the channel identifier includes both a full ARN and a short name, grep for both forms separately — many producers use only the short name or derive the ARN from it.

---

## Anti-Patterns

**Caller-tracing on event-driven systems** — searching for function imports or invocations of the consumer handler finds nothing by construction. The producer enqueues to a channel; it never imports the consumer. Caller-tracing is the wrong tool for event-driven boundaries. Always use channel-identifier grep (Phase 2) instead.

**Documentation-as-answer** — treating a README or inline comment claim ("unused," "manual only," "no callers") as proof rather than as a hypothesis. Documentation becomes stale. Run Phase 2 regardless.

**Search scope limited by directory convention** — restricting the producer sweep to main service or shared package directories and missing sibling components, migration scripts, IaC directories, or ops tooling. Producers live anywhere that has write access to the channel.

**Single-technology assumption** — assuming the codebase uses only one messaging stack when in practice many systems mix technologies (e.g., SQS for async queues + EventBridge for domain events + Redis streams for telemetry). Check all stacks present in the dependency manifest.

---

## Worked Example

**Scenario:** A Lambda consumer is declared with an SQS event source. Documentation in `lambdas/processor/README.md` states "this Lambda is triggered manually for testing only — no automated callers." Investigation uses the four-phase methodology.

**Phase 1 — Trigger contract:**
Read `lambdas/processor/serverless.yml`. Event source: `arn:aws:sqs:us-east-1:123456789:document-ingestion-queue`. Short name: `document-ingestion-queue`. Message schema: `{ documentId: string, s3Key: string }` (from the handler's TypeScript input type).

**Phase 2 — Producer-side discovery:**
Grep `document-ingestion-queue` and `SendMessageCommand` across the full repo scope, including sibling `lambdas/` directories.

```
rg 'document-ingestion-queue|SendMessageCommand' lambdas/ scripts/ terraform/
```

Result: `lambdas/ingestor/src/handler.ts` imports `SendMessageCommand` and constructs a `QueueUrl` containing `document-ingestion-queue`. The ingestor Lambda runs on S3 object-creation events — it is an automated producer.

**Phase 3 — Documentation as hypothesis:**
README claims "manual only." Empirical sweep found an automated producer. README is stale — the ingestor Lambda has been wiring this queue since the S3 trigger was added. Flag for update.

**Phase 4 — Synthesis:**
- **Consumer:** `lambdas/processor` — triggered by SQS `document-ingestion-queue` event source
- **Producer:** `lambdas/ingestor/src/handler.ts` — enqueues on S3 object-creation via `SendMessageCommand` to `document-ingestion-queue`
- **Trigger contract:** SQS queue ARN `arn:aws:sqs:us-east-1:123456789:document-ingestion-queue`; payload `{ documentId, s3Key }`
- **Documentation gap:** `lambdas/processor/README.md` incorrectly states "manual only" — update required
