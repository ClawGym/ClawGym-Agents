Messaging app logical schema (PostgreSQL 14+)

Overview
- This is a high-volume messaging system: ~2M users, ~500K conversations, ~50M messages.
- Soft deletes are used on messages (is_deleted).
- Background jobs are processed via a simple job_queue table.
- A lightweight tasks table tracks product work items; filters need to handle optional (nullable) parameters.

Tables and columns

1) users
- id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
- email TEXT NOT NULL               -- case-insensitive login/lookup; logical uniqueness at app level
- name TEXT                         -- display name
- active BOOLEAN NOT NULL DEFAULT true
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- last_login_at TIMESTAMPTZ NULL

Notes:
- Email lookups are frequent and must be case-insensitive.
- About 1–2% of accounts are inactive (active = false).

2) conversations
- id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
- title TEXT NOT NULL
- created_by_user_id BIGINT NOT NULL REFERENCES users(id)
- is_archived BOOLEAN NOT NULL DEFAULT false
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
- last_message_at TIMESTAMPTZ NULL   -- denormalized pointer to help sort conversation lists

3) conversation_participants
- conversation_id BIGINT NOT NULL REFERENCES conversations(id)
- user_id BIGINT NOT NULL REFERENCES users(id)
- role TEXT NOT NULL DEFAULT 'member'  -- e.g., owner, admin, member
- added_at TIMESTAMPTZ NOT NULL DEFAULT now()
Primary key (conversation_id, user_id)

Notes:
- Queries often filter conversations by a given user’s participation.
- Joins to messages are common to fetch latest message per conversation.

4) messages
- id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
- conversation_id BIGINT NOT NULL REFERENCES conversations(id)
- sender_user_id BIGINT NOT NULL REFERENCES users(id)
- body TEXT NOT NULL
- is_deleted BOOLEAN NOT NULL DEFAULT false   -- soft delete flag
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- edited_at TIMESTAMPTZ NULL
- attachments JSONB NULL

Notes:
- About 20–30% of messages may be soft-deleted over time (is_deleted = true).
- A very common pattern: “latest message per conversation for a given user”, excluding deleted messages.
- Returning only a handful of columns (id, sender_user_id, body, created_at) per row is typical for conversation lists.

5) job_queue
- id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
- task_type TEXT NOT NULL                     -- e.g., 'send_email', 'push_notification'
- payload JSONB NOT NULL                      -- structured job arguments
- priority INTEGER NOT NULL DEFAULT 100       -- lower numbers = higher priority
- run_at TIMESTAMPTZ NOT NULL DEFAULT now()   -- scheduled time
- locked_at TIMESTAMPTZ NULL                  -- null means available
- locked_by TEXT NULL                         -- worker name/ID that locked the job
- attempts SMALLINT NOT NULL DEFAULT 0
- max_attempts SMALLINT NOT NULL DEFAULT 5
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()

Notes:
- Workers claim jobs in priority order; ties broken by run_at then id.
- Claiming must avoid thundering herds and blocking; use SELECT ... FOR UPDATE SKIP LOCKED.

6) tasks
- id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
- title TEXT NOT NULL
- description TEXT NULL
- assignee_id BIGINT NULL REFERENCES users(id)   -- can be NULL for unassigned tasks
- due_date DATE NULL
- status TEXT NOT NULL DEFAULT 'open'            -- e.g., open, in_progress, done
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- completed_at TIMESTAMPTZ NULL

Notes:
- Reporting queries filter by status and optionally by assignee_id, which may be NULL; require NULL-safe equality.
- Sometimes also filter by due_date cutoff if provided.

Relationships and typical joins
- users (1) — (many) conversations via created_by_user_id
- users (many) — (many) conversations via conversation_participants
- conversations (1) — (many) messages via conversation_id
- users (1) — (many) messages via sender_user_id
- users (1) — (many) tasks via assignee_id

Current indexing baseline (assume minimal)
- Primary keys on all id columns.
- No additional secondary indexes currently exist.
- We rely on the deliverables to propose appropriate expression/partial/covering indexes for the primary query patterns described below.

Data distribution notes
- messages.is_deleted = true for roughly 25% of rows (partial index on non-deleted rows would reduce index size and improve scans).
- job_queue has a small active working set (locked_at IS NULL), with frequent ordered scans on priority/run_at.
- users.email lookups are case-insensitive and frequent; an expression index on lower(email) is expected.