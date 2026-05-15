import os
import sys
import json
import csv

def is_number(x):
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_csv_with_header(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
            return headers, rows, None
    except Exception as e:
        return None, None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_model_selection_json": False,
        "model_selection_json_valid": False,
        "model_selection_sources_ok": False,
        "model_selection_cost_assumptions_ok": False,
        "model_selection_orchestration_keys_ok": False,
        "model_selection_orchestration_phase_fields_ok": False,
        "model_recommendations_count_ok": False,
        "has_summary_csv": False,
        "summary_csv_header_ok": False,
        "summary_csv_rows_count_ok": False,
        "summary_csv_phases_ok": False,
        "summary_csv_costs_numeric_ok": False,
        "has_decision_memo_md": False,
        "decision_memo_wordcount_ok": False,
        "decision_memo_keywords_ok": False,
        "has_audit_checklist_md": False,
        "audit_checklist_keywords_ok": False,
    }

    # Paths to required outputs
    model_selection_path = os.path.join(output_dir, "model_selection.json")
    summary_csv_path = os.path.join(output_dir, "summary.csv")
    decision_memo_path = os.path.join(output_dir, "decision_memo.md")
    audit_checklist_path = os.path.join(output_dir, "audit_checklist.md")

    # 1) Check model_selection.json
    if os.path.isfile(model_selection_path):
        checks["has_model_selection_json"] = True
        data, err = load_json_file(model_selection_path)
        if isinstance(data, dict):
            # Validate top-level keys
            required_top_keys = ["project_overview", "constraints", "sources", "cost_assumptions", "orchestration", "model_recommendations"]
            top_ok = all(k in data for k in required_top_keys)
            # Types
            types_ok = (
                isinstance(data.get("project_overview"), str) and
                isinstance(data.get("constraints"), dict) and
                isinstance(data.get("sources"), list) and
                isinstance(data.get("cost_assumptions"), dict) and
                isinstance(data.get("orchestration"), dict) and
                isinstance(data.get("model_recommendations"), list)
            )
            if top_ok and types_ok:
                checks["model_selection_json_valid"] = True

            # Sources must contain the three input paths
            sources_required = {"input/project_brief.md", "input/model_prices.csv", "input/constraints.json"}
            src_list = data.get("sources") if isinstance(data.get("sources"), list) else []
            src_set = set([str(s) for s in src_list])
            if sources_required.issubset(src_set):
                checks["model_selection_sources_ok"] = True

            # cost_assumptions numeric fields
            ca = data.get("cost_assumptions", {})
            nums_ok = (
                is_number(ca.get("tokens_in_per_request")) and
                is_number(ca.get("tokens_out_per_request")) and
                is_number(ca.get("requests_per_day"))
            )
            if nums_ok:
                checks["model_selection_cost_assumptions_ok"] = True

            # orchestration object checks
            orch = data.get("orchestration", {})
            if isinstance(orch, dict):
                # Must include exactly keys: planning, execution, review
                expected_keys = {"planning", "execution", "review"}
                orch_keys = set(orch.keys())
                if orch_keys == expected_keys:
                    checks["model_selection_orchestration_keys_ok"] = True

                # For each phase, validate fields and cost_estimate
                phases_ok = True
                for phase in ["planning", "execution", "review"]:
                    phase_obj = orch.get(phase)
                    if not isinstance(phase_obj, dict):
                        phases_ok = False
                        break
                    if not isinstance(phase_obj.get("default_choice"), str):
                        phases_ok = False
                        break
                    if not (isinstance(phase_obj.get("candidate_models"), list) and len(phase_obj.get("candidate_models")) >= 2):
                        phases_ok = False
                        break
                    if not isinstance(phase_obj.get("rationale"), str):
                        phases_ok = False
                        break
                    ce = phase_obj.get("cost_estimate")
                    if not isinstance(ce, dict):
                        phases_ok = False
                        break
                    ce_fields = [
                        "tokens_in_per_request",
                        "tokens_out_per_request",
                        "requests_per_day",
                        "input_cost_per_token_usd",
                        "output_cost_per_token_usd",
                        "total_daily_cost_usd",
                    ]
                    if not all(field in ce for field in ce_fields):
                        phases_ok = False
                        break
                    # Numeric checks
                    if not all(is_number(ce.get(field)) for field in ce_fields):
                        phases_ok = False
                        break
                    try:
                        if float(ce.get("total_daily_cost_usd")) <= 0:
                            phases_ok = False
                            break
                        # also ensure other numeric conversions are possible
                        _ = float(ce.get("tokens_in_per_request"))
                        _ = float(ce.get("tokens_out_per_request"))
                        _ = float(ce.get("requests_per_day"))
                        _ = float(ce.get("input_cost_per_token_usd"))
                        _ = float(ce.get("output_cost_per_token_usd"))
                    except Exception:
                        phases_ok = False
                        break
                if phases_ok:
                    checks["model_selection_orchestration_phase_fields_ok"] = True

            # model_recommendations length
            mr = data.get("model_recommendations")
            if isinstance(mr, list) and len(mr) >= 3:
                checks["model_recommendations_count_ok"] = True

    # 2) Check summary.csv
    if os.path.isfile(summary_csv_path):
        checks["has_summary_csv"] = True
        header, rows, err = parse_csv_with_header(summary_csv_path)
        expected_header = ["phase", "default_choice", "alt_1", "alt_2", "est_daily_cost_usd", "notes"]
        if header == expected_header:
            checks["summary_csv_header_ok"] = True
        # At least 3 rows
        if rows is not None and isinstance(rows, list) and len(rows) >= 3:
            checks["summary_csv_rows_count_ok"] = True
            # Phases include planning, execution, review (case-insensitive)
            phases_lower = set([str(r.get("phase", "")).strip().lower() for r in rows])
            if {"planning", "execution", "review"}.issubset(phases_lower):
                checks["summary_csv_phases_ok"] = True
            # est_daily_cost_usd numeric and >0 for all rows
            costs_ok = True
            for r in rows:
                val = r.get("est_daily_cost_usd")
                if not is_number(val):
                    costs_ok = False
                    break
                try:
                    if float(val) <= 0:
                        costs_ok = False
                        break
                except Exception:
                    costs_ok = False
                    break
            if costs_ok:
                checks["summary_csv_costs_numeric_ok"] = True

    # 3) Check decision_memo.md
    if os.path.isfile(decision_memo_path):
        checks["has_decision_memo_md"] = True
        content, err = read_text(decision_memo_path)
        if isinstance(content, str):
            # Word count >= 400
            words = [w for w in content.split() if w.strip()]
            if len(words) >= 400:
                checks["decision_memo_wordcount_ok"] = True
            # Keywords (case-insensitive)
            lc = content.lower()
            required_phrases = [
                "prompt caching",
                "batch apis",
                "context window",
                "open source",
                "mid-tier",
                "frontier",
                "orchestration",
                "verification and reassessment",
            ]
            if all(phrase in lc for phrase in required_phrases):
                checks["decision_memo_keywords_ok"] = True

    # 4) Check audit_checklist.md
    if os.path.isfile(audit_checklist_path):
        checks["has_audit_checklist_md"] = True
        content, err = read_text(audit_checklist_path)
        if isinstance(content, str):
            lc = content.lower()
            required_phrases = [
                "cost tracking",
                "verification in pipeline",
                "quarterly reassessment",
                "context limits",
            ]
            if all(phrase in lc for phrase in required_phrases):
                checks["audit_checklist_keywords_ok"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Ensure 0.0 if no artifacts produced (baseline no-op)
    # If none of the "has_*" are true, set reward to 0.0
    has_any_artifact = checks["has_model_selection_json"] or checks["has_summary_csv"] or checks["has_decision_memo_md"] or checks["has_audit_checklist_md"]
    if not has_any_artifact:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()