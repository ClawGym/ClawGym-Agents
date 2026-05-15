import json
import os
import sys
from urllib.parse import quote

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def build_expected_from_spec(spec):
    """
    Build expected URLs per brief based on the rules in the task.
    """
    bases = {
        "google": "https://www.google.com/search?q=",
        "duckduckgo": "https://duckduckgo.com/html/?q=",
        "brave": "https://search.brave.com/search?q=",
        "startpage": "https://www.startpage.com/sp/search?query=",
        "wolframalpha": "https://www.wolframalpha.com/input?i=",
    }

    expected = {}

    briefs = spec if isinstance(spec, list) else spec.get("briefs", [])
    for b in briefs:
        if not isinstance(b, dict):
            continue
        bid = b.get("id")
        query = b.get("query", "")
        if not bid or not isinstance(query, str):
            continue

        encoded = quote(query, safe="")  # strict UTF-8 encoding, encode spaces and special chars
        out = {}
        # Google
        g = bases["google"] + encoded
        time_filter = b.get("time_filter")
        if time_filter == "week":
            g += "&tbs=qdr:w"
        elif time_filter == "year":
            g += "&tbs=qdr:y"
        out["google"] = g

        # DuckDuckGo
        ddg = bases["duckduckgo"] + encoded
        ddg_params = b.get("duckduckgo_params") or {}
        # Append in exact order: kp then kl if present
        if "kp" in ddg_params:
            ddg += f"&kp={ddg_params['kp']}"
        if "kl" in ddg_params:
            ddg += f"&kl={ddg_params['kl']}"
        out["duckduckgo"] = ddg

        # Brave
        br = bases["brave"] + encoded
        if time_filter == "week":
            br += "&tf=pw"
        elif time_filter == "year":
            br += "&tf=py"
        out["brave"] = br

        # Startpage
        sp = bases["startpage"] + encoded
        if time_filter == "week":
            sp += "&time=week"
        elif time_filter == "year":
            sp += "&time=year"
        out["startpage"] = sp

        # WolframAlpha if compute
        if b.get("type") == "compute":
            out["wolframalpha"] = bases["wolframalpha"] + encoded

        expected[bid] = out

    return expected

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "search_urls_json_exists": False,
        "search_urls_json_valid": False,
        "briefs_length_4": False,
        "repo_profiling_correct": False,
        "ml_pdf_year_correct": False,
        "fx_compute_correct": False,
        "privacy_tools_us_correct": False,
        "readme_exists": False,
        "readme_mentions_all_ids": False,
        "no_extra_fields": False,
    }

    # Paths
    spec_path = os.path.join(input_dir, "spec.json")
    output_json_path = os.path.join(output_dir, "search_urls.json")
    output_readme_path = os.path.join(output_dir, "README.md")

    # Load spec
    spec_data, spec_err = load_json(spec_path)
    if spec_data is None:
        # If spec is missing or invalid, we cannot compute expected; keep all False
        result = {**checks}
        # Compute reward with gating if needed
        passed = sum(1 for v in checks.values() if v)
        reward = 0.0
        print(json.dumps({"reward": reward, **result}))
        return

    expected_map = build_expected_from_spec(spec_data)

    # Determine which IDs must be present (from spec)
    # Also align with task's expected four IDs for more deterministic checks
    # We will use the IDs known from the task to set per-brief checks.
    expected_ids = ["repo_profiling", "ml_pdf_year", "fx_compute", "privacy_tools_us"]

    # Load output JSON
    if os.path.isfile(output_json_path):
        checks["search_urls_json_exists"] = True
        out_json, out_err = load_json(output_json_path)
        if out_json is not None and isinstance(out_json, dict) and "briefs" in out_json and isinstance(out_json["briefs"], list):
            checks["search_urls_json_valid"] = True
            briefs_list = out_json["briefs"]
            if len(briefs_list) == 4:
                checks["briefs_length_4"] = True

            # Index by id
            by_id = {}
            for item in briefs_list:
                if isinstance(item, dict) and "id" in item:
                    by_id[item["id"]] = item

            # Validate each expected brief
            all_no_extra = True
            for bid in expected_ids:
                expected = expected_map.get(bid)
                item = by_id.get(bid)
                # Determine allowed keys
                expect_keys = {"id", "google", "duckduckgo", "brave", "startpage"}
                if expected and "wolframalpha" in expected:
                    expect_keys.add("wolframalpha")

                correct = False
                if expected is not None and item is not None:
                    # Check keys exactly
                    item_keys = set(item.keys())
                    if item_keys == expect_keys:
                        # Compare each required URL exactly
                        urls_match = True
                        for k in expect_keys:
                            if k == "id":
                                continue
                            if item.get(k) != expected.get(k, ""):
                                urls_match = False
                                break
                        # For non-compute briefs ensure there is no wolframalpha in expected or item (keys check already ensures)
                        if urls_match:
                            correct = True
                    else:
                        all_no_extra = False
                else:
                    # Missing item or expected brief not defined
                    all_no_extra = False

                if bid == "repo_profiling":
                    checks["repo_profiling_correct"] = correct
                elif bid == "ml_pdf_year":
                    checks["ml_pdf_year_correct"] = correct
                elif bid == "fx_compute":
                    checks["fx_compute_correct"] = correct
                elif bid == "privacy_tools_us":
                    checks["privacy_tools_us_correct"] = correct

            # If we did not detect any extra fields and all items had exact key sets, mark true
            # Note: If some items missing, all_no_extra already set to False above.
            checks["no_extra_fields"] = all_no_extra
        else:
            checks["search_urls_json_valid"] = False
    else:
        checks["search_urls_json_exists"] = False

    # README checks
    if os.path.isfile(output_readme_path):
        checks["readme_exists"] = True
        try:
            with open(output_readme_path, "r", encoding="utf-8") as f:
                readme_txt = f.read()
            mentions = all(bid in readme_txt for bid in expected_ids)
            checks["readme_mentions_all_ids"] = mentions
        except Exception:
            checks["readme_mentions_all_ids"] = False
    else:
        checks["readme_exists"] = False

    # Compute reward
    # Enforce baseline: if required artifacts are missing or invalid, reward is 0.0
    required_ok = checks["search_urls_json_exists"] and checks["search_urls_json_valid"] and checks["readme_exists"]
    if not required_ok:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        # Normalize to [0,1]
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    output = {"reward": round(reward, 6)}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()