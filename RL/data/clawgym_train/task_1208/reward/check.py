import json
import os
import sys
import csv

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                items.append(obj)
            except Exception:
                # If any line is invalid JSON, propagate by raising
                raise
    return items

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def almost_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def compute_effective_input_tokens(input_tokens, system_prompt_tokens):
    if system_prompt_tokens is None:
        return input_tokens
    try:
        it = float(input_tokens)
        spt = float(system_prompt_tokens)
    except Exception:
        return input_tokens
    if spt > 1024:
        eff = it - spt
        if eff < 0:
            eff = 0.0
        return eff
    return it

def compute_cost(effective_input_tokens, output_tokens, pricing_for_model):
    # pricing_for_model: dict with input_cost_per_1M and output_cost_per_1M
    try:
        in_cost = float(pricing_for_model["input_cost_per_1M"])
        out_cost = float(pricing_for_model["output_cost_per_1M"])
        eff_in = float(effective_input_tokens)
        out_t = float(output_tokens)
    except Exception:
        return None
    return (eff_in / 1_000_000.0) * in_cost + (out_t / 1_000_000.0) * out_cost

def safe_get(d, key, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "files_present": False,
        "tracker_structure_valid": False,
        "tracker_embeds_config": False,
        "tracker_embeds_pricing": False,
        "decision_log_count_and_order": False,
        "routing_logic_correct": False,
        "effective_tokens_correct": False,
        "success_ids_match_records": False,
        "costs_correct_vs_pricing": False,
        "csv_matches_tracker": False,
        "total_cost_matches_sum": False,
        "budget_logic_enforced": False,
        "no_failed_or_skipped_in_records": False,
    }

    # Required output paths
    tracker_path = os.path.join(output_dir, "tracker.json")
    csv_path = os.path.join(output_dir, "records.csv")
    log_path = os.path.join(output_dir, "decision_log.jsonl")

    # Required input paths
    config_path = os.path.join(input_dir, "config.json")
    pricing_path = os.path.join(input_dir, "pricing.json")
    requests_path = os.path.join(input_dir, "requests.jsonl")
    errors_path = os.path.join(input_dir, "errors.jsonl")

    # Check presence of outputs first
    if os.path.isfile(tracker_path) and os.path.isfile(csv_path) and os.path.isfile(log_path):
        checks["files_present"] = True
    else:
        # If missing outputs, reward must be 0. Print JSON and exit.
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Load inputs and outputs
    try:
        config = read_json(config_path)
        pricing = read_json(pricing_path)
        requests = read_jsonl(requests_path)
        errors = read_jsonl(errors_path)
        tracker = read_json(tracker_path)
    except Exception:
        # If parsing fails for any required file, cannot award
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Validate tracker structure
    required_tracker_keys = ["budgetLimit", "totalCost", "overBudget", "stoppedAtId", "records", "config", "pricing"]
    tracker_struct_ok = all(k in tracker for k in required_tracker_keys)
    tracker_types_ok = (
        tracker_struct_ok
        and is_number(tracker["budgetLimit"])
        and is_number(tracker["totalCost"])
        and isinstance(tracker["overBudget"], bool)
        and (tracker["stoppedAtId"] is None or isinstance(tracker["stoppedAtId"], str))
        and isinstance(tracker["records"], list)
    )
    # Validate each record has required fields and types
    record_fields_ok = True
    if tracker_types_ok:
        for rec in tracker["records"]:
            if not isinstance(rec, dict):
                record_fields_ok = False
                break
            for rf in ["id", "model", "inputTokens", "effectiveInputTokens", "outputTokens", "costUsd"]:
                if rf not in rec:
                    record_fields_ok = False
                    break
            if not record_fields_ok:
                break
            if not (isinstance(rec["id"], str) and isinstance(rec["model"], str)):
                record_fields_ok = False
                break
            if not (is_number(rec["inputTokens"]) and is_number(rec["effectiveInputTokens"]) and is_number(rec["outputTokens"]) and is_number(rec["costUsd"])):
                record_fields_ok = False
                break
    checks["tracker_structure_valid"] = bool(tracker_types_ok and record_fields_ok)

    # Check embedded config/pricing exact match
    try:
        checks["tracker_embeds_config"] = tracker_struct_ok and tracker["config"] == config
    except Exception:
        checks["tracker_embeds_config"] = False
    try:
        checks["tracker_embeds_pricing"] = tracker_struct_ok and tracker["pricing"] == pricing
    except Exception:
        checks["tracker_embeds_pricing"] = False

    # Read decision log
    try:
        decision_log = read_jsonl(log_path)
    except Exception:
        decision_log = []

    # Build error map
    error_by_id = {e.get("id"): e.get("errorName") for e in errors if isinstance(e, dict) and "id" in e}

    # Compute expected outcomes from inputs
    budget_limit = safe_get(config, "budgetLimit", 0)
    sonnet_text_th = safe_get(config, "sonnet_text_threshold", None)
    sonnet_item_th = safe_get(config, "sonnet_item_threshold", None)
    retryable = set(safe_get(config, "retryableErrors", []) or [])
    models_cfg = safe_get(config, "models", {}) or {}
    model_simple = safe_get(models_cfg, "simple", None)
    model_complex = safe_get(models_cfg, "complex", None)

    expected_logs = []
    expected_records = []
    running_total = 0.0
    over_budget_expected = False
    stopped_at_expected = None

    # Prepare expected per-request
    for idx, req in enumerate(requests):
        rid = req.get("id")
        text_len = req.get("textLength")
        item_cnt = req.get("itemCount")
        force_model = req.get("forceModel", None)
        input_tokens = req.get("inputTokens")
        output_tokens = req.get("outputTokens")
        spt = req.get("systemPromptTokens")

        # Determine selected model and reason
        if force_model is not None and force_model != "":
            selected_model = force_model
            reason = "forceModel"
        else:
            # Determine thresholds
            trig_text = (sonnet_text_th is not None and is_number(text_len) and float(text_len) >= float(sonnet_text_th))
            trig_item = (sonnet_item_th is not None and is_number(item_cnt) and float(item_cnt) >= float(sonnet_item_th))
            if trig_text:
                selected_model = model_complex
                reason = "textThreshold"
            elif trig_item:
                selected_model = model_complex
                reason = "itemThreshold"
            else:
                selected_model = model_simple
                reason = "default"

        # effectiveInputTokens by caching rule
        eff_in = compute_effective_input_tokens(input_tokens, spt)

        # Determine status and retries before budget
        err_name = error_by_id.get(rid, "none")
        if over_budget_expected:
            status = "skipped_budget"
            retries = 0
        else:
            if err_name == "none":
                status = "success"
                retries = 0
            elif err_name in retryable:
                status = "success"
                retries = 1
            else:
                status = "failed"
                retries = 0

        # If candidate is success and not yet over budget, compute cost & check budget
        if not over_budget_expected and status == "success":
            # Ensure pricing exists for selected model
            p_for_model = pricing.get(selected_model) if isinstance(pricing, dict) else None
            cost = None
            if isinstance(p_for_model, dict) and "input_cost_per_1M" in p_for_model and "output_cost_per_1M" in p_for_model:
                cost = compute_cost(eff_in, output_tokens, p_for_model)
            # If cost cannot be computed (missing pricing), treat as failed for expected comparison
            if cost is None:
                # Treat as failed (no record), but log failed
                status = "failed"
                retries = 0

        # If success and not yet over budget and cost computed, then consider budget stop
        if not over_budget_expected and status == "success":
            # cost is computed above
            # Recompute cost to be safe
            p_for_model2 = pricing.get(selected_model) if isinstance(pricing, dict) else None
            cost2 = compute_cost(eff_in, output_tokens, p_for_model2) if isinstance(p_for_model2, dict) else None
            if cost2 is None:
                status = "failed"
                retries = 0
            else:
                # Check if adding exceeds budget
                if is_number(budget_limit) and (running_total + cost2) > float(budget_limit):
                    over_budget_expected = True
                    stopped_at_expected = rid
                    status = "skipped_budget"
                    retries = 0
                else:
                    # Include in expected records
                    expected_records.append({
                        "id": rid,
                        "model": selected_model,
                        "inputTokens": input_tokens,
                        "effectiveInputTokens": eff_in,
                        "outputTokens": output_tokens,
                        "costUsd": cost2
                    })
                    running_total += cost2

        # Append expected log entry
        expected_logs.append({
            "id": rid,
            "selectedModel": selected_model,
            "reason": reason,
            "status": status,
            "retries": retries,
            "effectiveInputTokens": eff_in
        })

        # If over budget now, remaining will be skipped
        # The loop will handle setting status to skipped_budget due to over_budget_expected flag

    # Verify decision_log count and order
    ids_requests = [r.get("id") for r in requests]
    ids_logs = [l.get("id") for l in decision_log]
    # Require non-empty lines equal to number of requests and in same order
    if len(decision_log) == len(requests) and ids_logs == ids_requests:
        checks["decision_log_count_and_order"] = True

    # Validate routing logic correctness and decision log fields
    routing_ok = True
    effective_tokens_ok = True
    # also check retries and status correctness according to expected
    statuses_ok = True
    for i, exp in enumerate(expected_logs):
        if i >= len(decision_log):
            routing_ok = False
            effective_tokens_ok = False
            statuses_ok = False
            break
        got = decision_log[i]
        # required keys
        for key in ["id", "selectedModel", "reason", "status", "retries", "effectiveInputTokens"]:
            if key not in got:
                routing_ok = False
                effective_tokens_ok = False
                statuses_ok = False
                break
        if got.get("id") != exp["id"]:
            routing_ok = False
        if got.get("selectedModel") != exp["selectedModel"]:
            routing_ok = False
        if got.get("reason") != exp["reason"]:
            routing_ok = False
        if got.get("status") != exp["status"]:
            statuses_ok = False
        # retries numeric equality
        try:
            if int(got.get("retries")) != int(exp["retries"]):
                statuses_ok = False
        except Exception:
            statuses_ok = False
        # effective input tokens tolerance check
        if not almost_equal(got.get("effectiveInputTokens"), exp["effectiveInputTokens"], tol=1e-6):
            effective_tokens_ok = False
    checks["routing_logic_correct"] = bool(routing_ok)
    checks["effective_tokens_correct"] = bool(effective_tokens_ok)

    # Extract success ids from decision log
    success_ids = [l.get("id") for l in decision_log if l.get("status") == "success"]

    # Verify success ids match tracker.records ids and CSV rows exactly (order doesn't have to match, but set equality required)
    tracker_rec_ids = [rec.get("id") for rec in tracker.get("records", []) if isinstance(rec, dict)]
    # Read CSV
    csv_rows = []
    csv_header_ok = False
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == ["id", "model", "effectiveInputTokens", "outputTokens", "costUsd"]:
                csv_header_ok = True
            for row in reader:
                csv_rows.append(row)
    except Exception:
        csv_rows = []
        csv_header_ok = False

    csv_ids = [row.get("id") for row in csv_rows]
    # Ensure header ok and ids correspond
    if csv_header_ok:
        if set(success_ids) == set(tracker_rec_ids) == set(csv_ids):
            checks["success_ids_match_records"] = True

    # Costs correct vs pricing for each tracker record, and prepare mapping for csv comparison
    costs_ok = True
    # build mapping for pricing
    for rec in tracker.get("records", []):
        if not isinstance(rec, dict):
            costs_ok = False
            break
        rid = rec.get("id")
        model = rec.get("model")
        eff_in = rec.get("effectiveInputTokens")
        out_t = rec.get("outputTokens")
        cost_rec = rec.get("costUsd")
        p = pricing.get(model) if isinstance(pricing, dict) else None
        if not isinstance(p, dict) or "input_cost_per_1M" not in p or "output_cost_per_1M" not in p:
            costs_ok = False
            break
        expected_cost = compute_cost(eff_in, out_t, p)
        if expected_cost is None:
            costs_ok = False
            break
        if not almost_equal(cost_rec, expected_cost, tol=1e-6):
            costs_ok = False
            break
    checks["costs_correct_vs_pricing"] = bool(costs_ok)

    # CSV matches tracker: same rows, values align (cost within 1e-6 of tracker, eff_in and out_t equal numerically)
    csv_align_ok = True
    # Build tracker map by id
    tracker_map = {r.get("id"): r for r in tracker.get("records", []) if isinstance(r, dict) and "id" in r}
    if not csv_header_ok:
        csv_align_ok = False
    else:
        if len(csv_rows) != len(tracker_map):
            csv_align_ok = False
        else:
            for row in csv_rows:
                rid = row.get("id")
                if rid not in tracker_map:
                    csv_align_ok = False
                    break
                t = tracker_map[rid]
                # model equality
                if row.get("model") != t.get("model"):
                    csv_align_ok = False
                    break
                # effectiveInputTokens numeric equality
                try:
                    if not almost_equal(float(row.get("effectiveInputTokens")), t.get("effectiveInputTokens"), tol=1e-6):
                        csv_align_ok = False
                        break
                except Exception:
                    csv_align_ok = False
                    break
                # outputTokens numeric equality
                try:
                    if not almost_equal(float(row.get("outputTokens")), t.get("outputTokens"), tol=1e-6):
                        csv_align_ok = False
                        break
                except Exception:
                    csv_align_ok = False
                    break
                # costUsd rounded to 6 decimals; compare numeric within 1e-6 to tracker cost
                try:
                    csv_cost = float(row.get("costUsd"))
                    tr_cost = float(t.get("costUsd"))
                    if not almost_equal(csv_cost, tr_cost, tol=1e-6):
                        csv_align_ok = False
                        break
                except Exception:
                    csv_align_ok = False
                    break
    checks["csv_matches_tracker"] = bool(csv_align_ok)

    # totalCost equals sum of tracker record costs within tolerance
    total_cost_ok = False
    try:
        sum_costs = sum(float(r.get("costUsd")) for r in tracker.get("records", []) if is_number(r.get("costUsd")))
        total_cost_ok = almost_equal(sum_costs, tracker.get("totalCost"), tol=1e-6)
    except Exception:
        total_cost_ok = False
    checks["total_cost_matches_sum"] = bool(total_cost_ok)

    # Budget logic enforced
    budget_logic_ok = True
    # Compare tracker overBudget and stoppedAtId with expected
    if tracker.get("overBudget") != over_budget_expected:
        budget_logic_ok = False
    # stoppedAtId must match when over budget expected, else should be None
    if over_budget_expected:
        if tracker.get("stoppedAtId") != stopped_at_expected:
            budget_logic_ok = False
        # Ensure no record for stoppedAtId or subsequent ids
        if stopped_at_expected in tracker_map:
            budget_logic_ok = False
        if stopped_at_expected in csv_ids:
            budget_logic_ok = False
        # In decision log, from stoppedAtId onward, all should be skipped_budget
        if stopped_at_expected in ids_requests:
            stop_index = ids_requests.index(stopped_at_expected)
            for j in range(stop_index, len(decision_log)):
                if decision_log[j].get("status") != "skipped_budget":
                    budget_logic_ok = False
                    break
    else:
        # If not over budget, tracker stoppedAtId should be None
        if tracker.get("stoppedAtId") not in (None, ""):
            budget_logic_ok = False
    checks["budget_logic_enforced"] = bool(budget_logic_ok)

    # Ensure no failed or skipped ids are in tracker records or CSV
    rec_id_set = set(tracker_rec_ids)
    csv_id_set = set(csv_ids)
    bad_in_records = False
    for l in decision_log:
        if l.get("status") in ("failed", "skipped_budget"):
            if l.get("id") in rec_id_set or l.get("id") in csv_id_set:
                bad_in_records = True
                break
    checks["no_failed_or_skipped_in_records"] = (not bad_in_records)

    # Final reward calculation
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # If missing files, must be 0 (handled earlier); otherwise proportional
    reward = 0.0
    if checks["files_present"]:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print result as single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()