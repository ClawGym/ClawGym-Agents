import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def load_json_file(path: str) -> Tuple[Any, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), ""
    except FileNotFoundError:
        return None, "not_found"
    except json.JSONDecodeError:
        return None, "invalid_json"
    except Exception as e:
        return None, f"error:{e}"

def load_text_file(path: str) -> Tuple[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), ""
    except FileNotFoundError:
        return "", "not_found"
    except Exception as e:
        return "", f"error:{e}"

def is_non_increasing(seq: List[int]) -> bool:
    return all(seq[i] >= seq[i+1] for i in range(len(seq)-1))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        "notes_exists": False,
        "notes_json_valid_array": False,
        "notes_items_schema_exact_fields": False,
        "notes_kind_is_1_for_all": False,
        "notes_ids_unique": False,
        "notes_sorted_desc": False,
        "notes_created_at_integers": False,
        "provenance_exists": False,
        "provenance_json_valid": False,
        "provenance_relays_valid": False,
        "provenance_queries_valid": False,
        "provenance_cmd_log_nonempty": False,
        "provenance_timestamp_has_T": False,
        "summary_exists": False,
        "summary_contains_sections": False,
        "summary_total_matches_notes_length": False,
    }

    # Paths
    notes_path = os.path.join(output_dir, "notes.json")
    provenance_path = os.path.join(output_dir, "provenance.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Load and validate notes.json
    notes_data, notes_err = load_json_file(notes_path)
    if notes_err == "":
        checks["notes_exists"] = True
        if isinstance(notes_data, list):
            checks["notes_json_valid_array"] = True
            expected_fields = {"id", "pubkey", "created_at", "kind", "content"}
            all_schema_ok = True
            all_kind_ok = True
            all_created_at_int = True
            ids: List[str] = []
            created_ats: List[int] = []
            for item in notes_data:
                if not isinstance(item, dict):
                    all_schema_ok = False
                    break
                keys = set(item.keys())
                if keys != expected_fields:
                    all_schema_ok = False
                    break
                # type checks
                if not isinstance(item.get("id"), str):
                    all_schema_ok = False
                    break
                if not isinstance(item.get("pubkey"), str):
                    all_schema_ok = False
                    break
                if not isinstance(item.get("content"), str):
                    all_schema_ok = False
                    break
                if not isinstance(item.get("kind"), int):
                    all_schema_ok = False
                    break
                if item.get("kind") != 1:
                    all_kind_ok = False
                if not isinstance(item.get("created_at"), int):
                    all_created_at_int = False
                else:
                    created_ats.append(item["created_at"])
                ids.append(item.get("id"))

            if all_schema_ok:
                checks["notes_items_schema_exact_fields"] = True
            if all_kind_ok and all_schema_ok:
                checks["notes_kind_is_1_for_all"] = True
            if all_created_at_int and all_schema_ok:
                checks["notes_created_at_integers"] = True
            if ids and len(ids) == len(set(ids)) and all_schema_ok:
                checks["notes_ids_unique"] = True
            # Sorting check only if we have created_at integers for all
            if checks["notes_created_at_integers"]:
                if is_non_increasing(created_ats):
                    checks["notes_sorted_desc"] = True
        else:
            # notes_json_valid_array remains False
            pass
    else:
        # notes_exists remains False
        pass

    # Load and validate provenance.json
    provenance_data, prov_err = load_json_file(provenance_path)
    if prov_err == "":
        checks["provenance_exists"] = True
        if isinstance(provenance_data, dict):
            # Must contain keys: relays (array), queries (array), cmd_log (array), timestamp (string)
            required_keys = {"relays", "queries", "cmd_log", "timestamp"}
            has_required = required_keys.issubset(set(provenance_data.keys()))
            if has_required:
                checks["provenance_json_valid"] = True
                # relays
                relays = provenance_data.get("relays")
                if isinstance(relays, list) and len(relays) >= 1 and all(isinstance(r, str) and r.startswith("wss://") for r in relays):
                    checks["provenance_relays_valid"] = True
                # queries
                queries = provenance_data.get("queries")
                q_ok = False
                if isinstance(queries, list) and len(queries) >= 1:
                    q_ok = True
                    for q in queries:
                        if not isinstance(q, dict):
                            q_ok = False
                            break
                        author = q.get("author")
                        limit = q.get("limit")
                        if not isinstance(author, str):
                            q_ok = False
                            break
                        if not isinstance(limit, int) or limit <= 0:
                            q_ok = False
                            break
                if q_ok:
                    checks["provenance_queries_valid"] = True
                # cmd_log
                cmd_log = provenance_data.get("cmd_log")
                if isinstance(cmd_log, list) and any(isinstance(c, str) and c.strip() for c in cmd_log):
                    checks["provenance_cmd_log_nonempty"] = True
                # timestamp
                timestamp = provenance_data.get("timestamp")
                if isinstance(timestamp, str) and "T" in timestamp:
                    checks["provenance_timestamp_has_T"] = True
        else:
            # provenance_json_valid remains False
            pass
    else:
        # provenance_exists remains False
        pass

    # Load and validate summary.md
    summary_text, sum_err = load_text_file(summary_path)
    if sum_err == "":
        checks["summary_exists"] = True
        # Check required section labels
        required_labels = ["Overview", "Per-author", "Top words", "Relays used"]
        if all(label in summary_text for label in required_labels):
            checks["summary_contains_sections"] = True
        # Check "Total notes:" count equals len(notes.json) if notes_json_valid_array
        m = re.search(r"Total notes:\s*(\d+)", summary_text)
        if m and isinstance(notes_data, list):
            try:
                total_in_summary = int(m.group(1))
                if total_in_summary == len(notes_data):
                    checks["summary_total_matches_notes_length"] = True
            except ValueError:
                pass
    else:
        # summary_exists remains False
        pass

    # Determine reward
    # If any required artifact missing, reward must be exactly 0.0
    required_present = checks["notes_exists"] and checks["provenance_exists"] and checks["summary_exists"]
    if not required_present:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()