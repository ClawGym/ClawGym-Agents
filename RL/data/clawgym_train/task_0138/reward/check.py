import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def validate_record_basic(rec):
    # For stored.json and new_memory.json (no score)
    if not isinstance(rec, dict):
        return False
    if not isinstance(rec.get("id"), str) or not rec.get("id"):
        return False
    if not isinstance(rec.get("text"), str):
        return False
    if not isinstance(rec.get("category"), str):
        return False
    if not is_number(rec.get("importance")):
        return False
    if not is_number(rec.get("createdAt")):
        return False
    return True

def validate_result_item(res):
    # For search results (includes score)
    if not isinstance(res, dict):
        return False
    base_ok = (
        isinstance(res.get("id"), str) and res.get("id") and
        isinstance(res.get("text"), str) and
        isinstance(res.get("category"), str) and
        is_number(res.get("importance")) and
        is_number(res.get("createdAt"))
    )
    if not base_ok:
        return False
    score = res.get("score")
    if not is_number(score):
        return False
    if score < 0 or score > 1:
        return False
    return True

def is_sorted_desc_by_score(arr):
    prev = None
    for item in arr:
        if not isinstance(item, dict) or "score" not in item:
            return False
        score = item["score"]
        if not is_number(score):
            return False
        if prev is not None and score > prev + 1e-12:
            return False
        prev = score
    return True

def read_text_single_line(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        # Must be exactly one non-empty line
        if len(lines) != 1:
            return None
        content = lines[0].strip()
        if not content:
            return None
        return content
    except Exception:
        return None

def list_all_files(root):
    files = []
    for base, _, fns in os.walk(root):
        for fn in fns:
            files.append(os.path.relpath(os.path.join(base, fn), root))
    return set(files)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {}

    # Expected files
    required_files_rel = {
        os.path.join("memory", "stored.json"),
        os.path.join("memory", "search_initial.json"),
        os.path.join("memory", "deleted_id.txt"),
        os.path.join("memory", "new_memory.json"),
        os.path.join("memory", "search_after.json"),
    }
    # Existence checks
    def out_path(rel): return os.path.join(output_dir, rel)
    exist_map = {rel: os.path.isfile(out_path(rel)) for rel in required_files_rel}

    checks["stored_exists"] = exist_map[os.path.join("memory", "stored.json")]
    checks["search_initial_exists"] = exist_map[os.path.join("memory", "search_initial.json")]
    checks["deleted_id_exists"] = exist_map[os.path.join("memory", "deleted_id.txt")]
    checks["new_memory_exists"] = exist_map[os.path.join("memory", "new_memory.json")]
    checks["search_after_exists"] = exist_map[os.path.join("memory", "search_after.json")]

    # No extra files check (only if output exists)
    if os.path.isdir(output_dir):
        found_files = list_all_files(output_dir)
        checks["no_extra_files"] = (found_files == required_files_rel)
    else:
        checks["no_extra_files"] = False

    # Gate: if any required file missing, reward must be 0.0
    all_required_exist = all(exist_map.values())

    # Stored.json validations
    stored = None
    checks["stored_schema_valid"] = False
    checks["stored_length_ge_6"] = False
    checks["stored_length_eq_6"] = False
    checks["stored_ids_unique"] = False
    checks["stored_match_input"] = False

    if checks["stored_exists"]:
        stored = load_json(out_path(os.path.join("memory", "stored.json")))
        if isinstance(stored, list):
            # Schema for each
            schema_ok = True
            ids = []
            for rec in stored:
                if not validate_record_basic(rec):
                    schema_ok = False
                    break
                ids.append(rec["id"])
            checks["stored_schema_valid"] = schema_ok
            if isinstance(ids, list):
                checks["stored_ids_unique"] = (len(ids) == len(set(ids)) and all(isinstance(i, str) and i for i in ids))
            checks["stored_length_ge_6"] = len(stored) >= 6
            checks["stored_length_eq_6"] = len(stored) == 6

            # Compare with input/memories.json if present
            input_mem_path = os.path.join(input_dir, "memories.json")
            if os.path.isfile(input_mem_path):
                inp = load_json(input_mem_path)
                if isinstance(inp, list) and len(inp) == 6 and checks["stored_schema_valid"]:
                    def rec_key(r): return (r.get("text"), r.get("category"), float(r.get("importance")) if is_number(r.get("importance")) else r.get("importance"))
                    stored_keys = sorted(rec_key(r) for r in stored)
                    input_keys = sorted(rec_key(r) for r in inp)
                    checks["stored_match_input"] = (stored_keys == input_keys)

    # search_initial.json validations
    initial = None
    checks["search_initial_keys_exact"] = False
    checks["search_initial_results_schema"] = False
    checks["search_initial_sorted"] = False
    checks["search_initial_scores_range"] = False
    checks["search_initial_top_branching_gitflow"] = False
    checks["search_initial_top_coffee_vanilla"] = False
    checks["search_initial_top_phoenix_date"] = False
    checks["search_initial_ids_subset_of_stored"] = False

    branching_top_id = None
    if checks["search_initial_exists"]:
        initial = load_json(out_path(os.path.join("memory", "search_initial.json")))
        required_keys = {"branching strategy we use", "morning coffee order", "Phoenix go-live date"}
        if isinstance(initial, dict) and set(initial.keys()) == required_keys:
            checks["search_initial_keys_exact"] = True

            schema_ok = True
            sorted_ok = True
            scores_ok = True

            # Validate each results list
            subset_ok = True
            ids_in_stored = set([rec["id"] for rec in stored]) if isinstance(stored, list) and checks["stored_schema_valid"] else None
            for key in ["branching strategy we use", "morning coffee order", "Phoenix go-live date"]:
                arr = initial.get(key)
                if not isinstance(arr, list) or not (1 <= len(arr) <= 3):
                    schema_ok = False
                    break
                # Validate items
                for item in arr:
                    if not validate_result_item(item):
                        schema_ok = False
                        break
                if not schema_ok:
                    break
                # Sorted by score descending
                if not is_sorted_desc_by_score(arr):
                    sorted_ok = False
                # Scores range already checked in validate_result_item
                # Subset check for initial searches: results should come from initially stored set
                if ids_in_stored is not None:
                    for item in arr:
                        if item["id"] not in ids_in_stored:
                            subset_ok = False

            checks["search_initial_results_schema"] = schema_ok
            checks["search_initial_sorted"] = sorted_ok
            checks["search_initial_scores_range"] = schema_ok  # since validate_result_item enforces [0,1]
            checks["search_initial_ids_subset_of_stored"] = subset_ok if ids_in_stored is not None else False

            # Top-result content checks
            if checks["search_initial_results_schema"]:
                # branching
                b_arr = initial["branching strategy we use"]
                if len(b_arr) >= 1:
                    branching_top = b_arr[0]
                    text = branching_top.get("text", "")
                    if isinstance(text, str) and ("gitflow" in text.lower()):
                        checks["search_initial_top_branching_gitflow"] = True
                    if isinstance(branching_top.get("id"), str) and branching_top.get("id"):
                        branching_top_id = branching_top.get("id")
                # coffee
                c_arr = initial["morning coffee order"]
                if len(c_arr) >= 1:
                    text = c_arr[0].get("text", "")
                    if isinstance(text, str) and ("vanilla lattes" in text.lower()):
                        checks["search_initial_top_coffee_vanilla"] = True
                # phoenix date
                p_arr = initial["Phoenix go-live date"]
                if len(p_arr) >= 1:
                    text = p_arr[0].get("text", "")
                    if isinstance(text, str) and ("2026-05-01" in text):
                        checks["search_initial_top_phoenix_date"] = True

    # deleted_id.txt validations
    checks["deleted_id_matches_top"] = False
    if checks["deleted_id_exists"] and branching_top_id:
        deleted_id = read_text_single_line(out_path(os.path.join("memory", "deleted_id.txt")))
        if isinstance(deleted_id, str) and deleted_id == branching_top_id:
            checks["deleted_id_matches_top"] = True

    # new_memory.json validations
    new_mem = None
    checks["new_memory_schema_valid"] = False
    checks["new_memory_text_trunk_based"] = False

    if checks["new_memory_exists"]:
        new_mem = load_json(out_path(os.path.join("memory", "new_memory.json")))
        if isinstance(new_mem, dict) and validate_record_basic(new_mem):
            checks["new_memory_schema_valid"] = True
            txt = new_mem.get("text", "")
            if isinstance(txt, str) and ("trunk-based development" in txt.lower()):
                checks["new_memory_text_trunk_based"] = True

    # search_after.json validations
    after = None
    checks["search_after_keys_exact"] = False
    checks["search_after_results_schema"] = False
    checks["search_after_sorted"] = False
    checks["search_after_scores_range"] = False
    checks["search_after_deleted_absent"] = False
    checks["search_after_trunk_based_present"] = False
    checks["search_after_contains_new_memory_id"] = False

    if checks["search_after_exists"]:
        after = load_json(out_path(os.path.join("memory", "search_after.json")))
        if isinstance(after, dict) and set(after.keys()) == {"branching strategy we use"}:
            checks["search_after_keys_exact"] = True
            arr = after.get("branching strategy we use")
            if isinstance(arr, list) and 1 <= len(arr) <= 3:
                schema_ok = all(validate_result_item(item) for item in arr)
                checks["search_after_results_schema"] = schema_ok
                if schema_ok:
                    checks["search_after_sorted"] = is_sorted_desc_by_score(arr)
                    checks["search_after_scores_range"] = True  # enforced by validate_result_item

                    # Deleted id must not appear
                    if checks["deleted_id_exists"]:
                        deleted_id = read_text_single_line(out_path(os.path.join("memory", "deleted_id.txt")))
                        if isinstance(deleted_id, str):
                            checks["search_after_deleted_absent"] = all(item.get("id") != deleted_id for item in arr)
                    else:
                        checks["search_after_deleted_absent"] = False

                    # Trunk-Based present in text
                    checks["search_after_trunk_based_present"] = any(
                        isinstance(item.get("text"), str) and ("trunk-based" in item["text"].lower())
                        for item in arr
                    )

                    # Contains new memory id (if new_mem valid)
                    if checks["new_memory_schema_valid"]:
                        nm_id = new_mem.get("id")
                        checks["search_after_contains_new_memory_id"] = any(
                            item.get("id") == nm_id for item in arr
                        )
                    else:
                        checks["search_after_contains_new_memory_id"] = False

    # Compute reward
    # If any required artifact missing, reward must be exactly 0.0
    if not all_required_exist:
        reward = 0.0
    else:
        # Count passed checks
        # Exclude pure existence gating? Include all in ratio.
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0

    # Ensure reward in [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()