import json
import os
import sys
import re

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def list_files_with_ext(directory, ext):
    try:
        return [os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith(ext)]
    except Exception:
        return []

def get_most_recent_file(paths):
    if not paths:
        return None
    try:
        return max(paths, key=lambda p: os.path.getmtime(p))
    except Exception:
        return None

def word_count(text):
    # Count words using a simple regex to approximate words
    tokens = re.findall(r"\b[\w']+\b", text)
    return len(tokens)

def contains_placeholder_labels(text):
    if not isinstance(text, str):
        return True
    patterns = [
        r"\bResponse [A-Z]\b",
        r"\bCandidate \d+\b",
        r"\bOutput [A-Z]\b",
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    results_dir = os.path.join(output_dir, "modelshow-results")
    analysis_dir = os.path.join(output_dir, "analysis")

    checks = {
        "results_dir_exists": False,
        "results_has_json": False,
        "results_has_md": False,
        "latest_results_json_parses": False,
        "results_json_has_required_keys": False,
        "results_metadata_fields_ok": False,
        "ranked_results_structure_ok": False,
        "deanonymized_output_has_no_placeholders": False,
        "overview_exists": False,
        "overview_parses": False,
        "overview_fields_valid": False,
        "overview_models_match_results": False,
        "overview_top_matches_results": False,
        "notes_exists": False,
        "notes_wordcount_ok": False,
    }

    results_json_data = None

    # Check results directory existence
    if os.path.isdir(results_dir):
        checks["results_dir_exists"] = True

        # Find JSON and Markdown files
        json_files = list_files_with_ext(results_dir, ".json")
        md_files = list_files_with_ext(results_dir, ".md")

        if len(json_files) > 0:
            checks["results_has_json"] = True

        if len(md_files) > 0:
            checks["results_has_md"] = True

        # Parse most recent JSON
        latest_json = get_most_recent_file(json_files)
        if latest_json and os.path.isfile(latest_json):
            data = read_json_file(latest_json)
            if data is not None:
                checks["latest_results_json_parses"] = True
                results_json_data = data

                # Validate required top-level keys and types
                required_ok = True
                # prompt
                if not isinstance(data.get("prompt"), str):
                    required_ok = False
                # models
                models = data.get("models")
                if not (isinstance(models, list) and len(models) >= 2 and all(isinstance(m, str) for m in models)):
                    required_ok = False
                # judge_model
                if not isinstance(data.get("judge_model"), str):
                    required_ok = False
                # ranked_results
                ranked_results = data.get("ranked_results")
                if not (isinstance(ranked_results, list) and len(ranked_results) >= 2):
                    required_ok = False
                # deanonymized_judge_output
                if not isinstance(data.get("deanonymized_judge_output"), str):
                    required_ok = False
                # anonymization_map
                if not isinstance(data.get("anonymization_map"), dict):
                    required_ok = False
                # metadata
                metadata = data.get("metadata")
                if not isinstance(metadata, dict):
                    required_ok = False

                if required_ok:
                    checks["results_json_has_required_keys"] = True

                # metadata fields
                metadata_ok = False
                if isinstance(metadata, dict):
                    tdm = metadata.get("total_duration_ms")
                    sm = metadata.get("successful_models")
                    if is_number(tdm) and is_number(sm):
                        metadata_ok = True
                if metadata_ok:
                    checks["results_metadata_fields_ok"] = True

                # ranked_results structure
                rr_ok = True
                if isinstance(ranked_results, list) and len(ranked_results) >= 2:
                    for item in ranked_results:
                        if not isinstance(item, dict):
                            rr_ok = False
                            break
                        if not is_number(item.get("rank")):
                            rr_ok = False
                            break
                        if not isinstance(item.get("model"), str):
                            rr_ok = False
                            break
                        if not is_number(item.get("score")):
                            rr_ok = False
                            break
                else:
                    rr_ok = False
                if rr_ok:
                    checks["ranked_results_structure_ok"] = True

                # deanonymized no placeholders
                djo = data.get("deanonymized_judge_output")
                if isinstance(djo, str) and not contains_placeholder_labels(djo):
                    checks["deanonymized_output_has_no_placeholders"] = True

    # Overview checks
    overview_path = os.path.join(analysis_dir, "overview.json")
    overview_data = None
    if os.path.isfile(overview_path):
        checks["overview_exists"] = True
        overview_data = read_json_file(overview_path)
        if overview_data is not None:
            checks["overview_parses"] = True
            # Validate overview fields
            fields_ok = True
            if not isinstance(overview_data.get("top_model"), str):
                fields_ok = False
            if not is_number(overview_data.get("top_score")) and not isinstance(overview_data.get("top_score"), int):
                fields_ok = False
            if not isinstance(overview_data.get("overall_assessment"), str) or len(overview_data.get("overall_assessment", "")) < 40:
                fields_ok = False
            mc = overview_data.get("models_compared")
            if not (isinstance(mc, list) and len(mc) >= 2 and all(isinstance(x, str) for x in mc)):
                fields_ok = False
            if fields_ok:
                checks["overview_fields_valid"] = True

            # Consistency with results JSON
            if results_json_data is not None and fields_ok and checks["ranked_results_structure_ok"]:
                # models compared set equality
                res_models = results_json_data.get("models", [])
                ov_models = overview_data.get("models_compared", [])
                try:
                    if set(res_models) == set(ov_models):
                        checks["overview_models_match_results"] = True
                except Exception:
                    pass

                # top model and score consistency
                try:
                    ranked = results_json_data.get("ranked_results", [])
                    scores = [float(item.get("score")) for item in ranked if is_number(item.get("score"))]
                    if scores:
                        max_score = max(scores)
                        tied_models = set(item.get("model") for item in ranked if is_number(item.get("score")) and float(item.get("score")) == max_score and isinstance(item.get("model"), str))
                        ov_top_score = overview_data.get("top_score")
                        ov_top_model = overview_data.get("top_model")
                        score_match = False
                        if is_number(ov_top_score):
                            # Use tolerance for float comparison
                            score_match = abs(float(ov_top_score) - float(max_score)) < 1e-6
                        model_match = isinstance(ov_top_model, str) and ov_top_model in tied_models
                        if score_match and model_match:
                            checks["overview_top_matches_results"] = True
                except Exception:
                    pass

    # Notes checks
    notes_path = os.path.join(analysis_dir, "notes.md")
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes_text = f.read()
            wc = word_count(notes_text)
            if 120 <= wc <= 180:
                checks["notes_wordcount_ok"] = True
        except Exception:
            pass

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Enforce no-op baseline: if no meaningful artifacts present, reward must be 0.0
    if not (checks["results_has_json"] or checks["results_has_md"] or checks["overview_exists"] or checks["notes_exists"]):
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result_obj = {"reward": reward}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()