# Kafka Readiness and Integration Exercise

Inputs:
- topics.csv lists the topics to prepare in the cluster
- messages.jsonl contains the records to produce (fields: topic, key (optional), message object)
- This spec defines the per-topic consumption limit and expectations

Requirements:
- Create topics as specified in topics.csv
- Produce all messages from messages.jsonl
- Verify by consuming the first N messages per topic from the beginning
- Preserve keys if present during consumption
- Use plain-English planning (no command lines) for the setup/produce/consume plan

consume_count: 2