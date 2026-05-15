Deliverables
- Produce three files:
  1) output/queries.sql.txt — the requested SQL statements.
  2) output/indexes.sql.txt — CREATE INDEX statements you recommend for the query patterns below.
  3) output/notes.md — brief rationale for the chosen queries and indexes.

General SQL guidance
- Target PostgreSQL 14+.
- Prefer PostgreSQL-native patterns: DISTINCT ON, IS NOT DISTINCT FROM, SELECT FOR UPDATE SKIP LOCKED.
- Use stable/immutable expressions in indexes where appropriate (e.g., lower(email)).
- Favor partial and covering indexes with INCLUDE to enable index-only scans and reduce bloat.

Query tasks (place each as a separate query in output/queries.sql.txt)

1) Job claiming (queue consumer)
- Claim the next available job from job_queue for a given worker name/ID.
- Requirements:
  - Only consider rows where locked_at IS NULL and run_at <= now().
  - Order by priority ASC, run_at ASC, id ASC to break ties.
  - Use SELECT ... FOR UPDATE SKIP LOCKED to avoid blocking and enable concurrent workers.
  - LIMIT 1.
  - On claim, set locked_at = now() and locked_by = $1 (worker name).
  - Return id, task_type, payload, priority, run_at.
- Pattern hint:
  - A common approach is a CTE (WITH next AS (... SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)) followed by UPDATE ... FROM next RETURNING ...; or a single UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING ... . Any equivalent pattern is acceptable as long as it uses FOR UPDATE SKIP LOCKED and LIMIT 1.

2) Latest message per conversation (conversation list)
- For a given user_id ($1), return the latest non-deleted message from each conversation the user participates in.
- Requirements:
  - Use DISTINCT ON (conversation_id) to pick the latest per conversation.
  - Exclude messages where is_deleted = true.
  - Consider only conversations where the user is a participant (join through conversation_participants).
  - Sort so that within each conversation the “latest” is by created_at DESC (use id DESC as a tiebreaker).
  - Return: conversation_id, id AS message_id, sender_user_id, body, created_at.
- Pattern hint:
  - SELECT DISTINCT ON (m.conversation_id) ... FROM messages m JOIN conversation_participants cp ON cp.conversation_id = m.conversation_id WHERE cp.user_id = $1 AND m.is_deleted = false ORDER BY m.conversation_id, m.created_at DESC, m.id DESC;

3) Case-insensitive email lookup (login)
- Find a single active user by email.
- Requirements:
  - Use lower(email) = lower($1).
  - Filter on active = true.
  - LIMIT 1.
  - Return: id, email, created_at.

4) NULL-safe equality filter for tasks
- List tasks by status and an optional assignee_id parameter ($2), which may be NULL. If $2 is NULL, return only tasks where assignee_id IS NULL; if $2 is not NULL, return only tasks where assignee_id = $2.
- Requirements:
  - Use IS NOT DISTINCT FROM for the assignee_id comparison: t.assignee_id IS NOT DISTINCT FROM $2.
  - Filter by status = $1.
  - Optionally support an upper due_date cutoff parameter ($3) that, if provided (non-NULL), restricts to t.due_date <= $3; otherwise, do not filter on due_date. You may implement this with ($3 IS NULL OR t.due_date <= $3).
  - Return: id, title, assignee_id, due_date, status, created_at.

Indexing goals (place DDL in output/indexes.sql.txt)
- Expression index for case-insensitive email lookup:
  - CREATE INDEX on users using lower(email). Prefer a unique index if the application enforces case-insensitive uniqueness.
- Partial and covering index for latest-per-conversation message scans:
  - Create an index on messages that excludes deleted rows: WHERE is_deleted = false.
  - Order leading columns to support DISTINCT ON (conversation_id) with ORDER BY created_at DESC.
  - Use INCLUDE to cover frequently selected columns (e.g., id, sender_user_id, body) to enable index-only scans.
  - Example direction: (conversation_id, created_at DESC) INCLUDE (id, sender_user_id, body) WHERE is_deleted = false.
- Job claiming index for fast filtering/ordering:
  - Create a partial index on job_queue that covers available jobs: WHERE locked_at IS NULL.
  - Include columns to support the ORDER BY priority, run_at, id.
  - Example column order: (priority ASC, run_at ASC, id ASC) WHERE locked_at IS NULL.
- Additional supportive indexes (optional but reasonable):
  - conversation_participants(user_id, conversation_id) to accelerate participant membership checks.
  - messages(conversation_id, id DESC) for occasional pagination by id; only if justified by workload.

Output notes (place in output/notes.md)
- For each index, add a brief rationale: what query it supports and why column order/INCLUDE/partial predicate was chosen.
- Mention that lower(email) matches queries using lower(email) = lower($1) exactly.
- Mention that the messages covering index reduces “Heap Fetches” and enables index-only scans for the latest-per-conversation query.
- Mention the SKIP LOCKED job-claiming pattern and how the partial job_queue index reduces the scanned set.

Parameter summary
- Job claiming: $1 = worker name (TEXT).
- Latest messages per conversation: $1 = user_id (BIGINT).
- Email lookup: $1 = email (TEXT).
- Task list: $1 = status (TEXT), $2 = assignee_id (BIGINT or NULL), $3 = due_date cutoff (DATE or NULL).