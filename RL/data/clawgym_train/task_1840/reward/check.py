import json
import os
import sys

def read_nonempty(path):
    try:
        if os.path.getsize(path) > 0:
            return True
    except OSError:
        return False
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    graph_path = os.path.join(output_dir, "ontology", "graph.jsonl")
    feedback_path = os.path.join(output_dir, "feedback", "sync-feedback.md")

    checks = {
        "graph_exists": False,
        "graph_nonempty": False,
        "entity_alice": False,
        "org_acme": False,
        "project_alpha": False,
        "relate_alice_works_at_acme": False,
        "relate_alice_assigned_project_alpha": False,
        "entity_bob_missing_email": False,
        "feedback_exists": False,
        "feedback_nonempty": False,
        "feedback_contains_bob_missing_email": False,
    }

    # Check graph.jsonl existence and content
    if os.path.isfile(graph_path):
        checks["graph_exists"] = True
        if read_nonempty(graph_path):
            checks["graph_nonempty"] = True

            # Parse JSONL and verify required records
            try:
                with open(graph_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue

                        op = rec.get("op")
                        if op == "upsert":
                            entity = rec.get("entity", {})
                            eid = entity.get("id")
                            etype = entity.get("type")
                            props = entity.get("properties", {}) if isinstance(entity.get("properties", {}), dict) else {}
                            # Alice
                            if (
                                eid == "person_alice_johnson"
                                and etype == "Person"
                                and props.get("name") == "Alice Johnson"
                                and props.get("email") == "alice@company.com"
                            ):
                                checks["entity_alice"] = True
                            # Org Acme
                            if (
                                eid == "organization_acme_corp"
                                and etype == "Organization"
                                and props.get("name") == "Acme Corp"
                            ):
                                checks["org_acme"] = True
                            # Project Alpha
                            if (
                                eid == "project_project_alpha"
                                and etype == "Project"
                                and props.get("name") == "Project Alpha"
                            ):
                                checks["project_alpha"] = True
                            # Bob missing email
                            if (
                                eid == "person_bob"
                                and etype == "Person"
                            ):
                                # Email must be omitted or null
                                if "email" not in props or props.get("email") is None:
                                    checks["entity_bob_missing_email"] = True

                        elif op == "relate":
                            rel = rec.get("rel")
                            frm = rec.get("from")
                            to = rec.get("to")
                            if rel == "works_at" and frm == "person_alice_johnson" and to == "organization_acme_corp":
                                checks["relate_alice_works_at_acme"] = True
                            if rel == "assigned_to" and frm == "person_alice_johnson" and to == "project_project_alpha":
                                checks["relate_alice_assigned_project_alpha"] = True
            except Exception:
                # If reading fails unexpectedly, leave checks as-is (False)
                pass

    # Check feedback file
    if os.path.isfile(feedback_path):
        checks["feedback_exists"] = True
        try:
            with open(feedback_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                checks["feedback_nonempty"] = True
                # Must include exact substring
                if "- [ ] `Bob` missing email" in content:
                    checks["feedback_contains_bob_missing_email"] = True
        except Exception:
            pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure numeric bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()