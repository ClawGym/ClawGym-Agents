import json
import os
import sys

def read_file_lower(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().lower()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    queries_path = os.path.join(output_dir, "queries.sql.txt")
    indexes_path = os.path.join(output_dir, "indexes.sql.txt")

    checks = {
        # Existence checks
        "queries_file_exists": False,
        "indexes_file_exists": False,

        # Queries content checks (dependent on queries file)
        "queries_has_skip_locked_limit1": False,
        "queries_has_distinct_on_latest": False,
        "queries_has_lower_email_compare": False,
        "queries_has_is_not_distinct_from": False,

        # Indexes content checks (dependent on indexes file)
        "indexes_has_users_email_expression": False,
        "indexes_has_messages_partial_not_deleted": False,
        "indexes_has_messages_covering_include": False,
        "indexes_has_job_queue_index": False,
    }

    # Verify queries.sql.txt
    if os.path.isfile(queries_path):
        checks["queries_file_exists"] = True
        q_content = read_file_lower(queries_path)

        # Job-claiming query using FOR UPDATE SKIP LOCKED and LIMIT 1
        if ("for update skip locked" in q_content) and ("limit 1" in q_content):
            checks["queries_has_skip_locked_limit1"] = True

        # Latest-per-conversation using DISTINCT ON (conversation_id) and ORDER BY mentioning created_at
        if ("distinct on (conversation_id)" in q_content) and ("order by" in q_content) and ("created_at" in q_content):
            checks["queries_has_distinct_on_latest"] = True

        # Case-insensitive email lookup pattern
        if "lower(email) = lower(" in q_content:
            checks["queries_has_lower_email_compare"] = True

        # NULL-safe equality using IS NOT DISTINCT FROM
        if " is not distinct from " in q_content:
            checks["queries_has_is_not_distinct_from"] = True

    # Verify indexes.sql.txt
    if os.path.isfile(indexes_path):
        checks["indexes_file_exists"] = True
        i_content = read_file_lower(indexes_path)

        # Expression index for case-insensitive email lookup on users
        if ("create index" in i_content) and ("on users" in i_content) and ("lower(email)" in i_content):
            checks["indexes_has_users_email_expression"] = True

        # Partial index on messages excluding deleted records
        if ("create index" in i_content) and ("on messages" in i_content) and ("where is_deleted = false" in i_content):
            checks["indexes_has_messages_partial_not_deleted"] = True

        # Covering index via INCLUDE for messages
        if ("create index" in i_content) and ("on messages" in i_content) and ("include" in i_content):
            checks["indexes_has_messages_covering_include"] = True

        # Index to support job-claim ordering and filtering
        if ("on job_queue" in i_content) and ("priority" in i_content) and ("where locked_at is null" in i_content):
            checks["indexes_has_job_queue_index"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v is True)

    # Ensure no-op baseline: if no output files exist, reward must be 0.0
    if not checks["queries_file_exists"] and not checks["indexes_file_exists"]:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Clamp reward between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()