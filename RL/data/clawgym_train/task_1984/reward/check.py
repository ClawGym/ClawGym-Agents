import json
import os
import sys
from typing import Any, Dict, List

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with all False
    checks: Dict[str, bool] = {
        # analysis.json checks
        "analysis_exists": False,
        "analysis_json_valid": False,
        "analysis_has_required_keys": False,
        "analysis_source_files_exact": False,
        "breakdown_min_entries": False,
        "breakdown_entries_valid": False,
        "breakdown_percent_sum_valid": False,
        "region_egress_min_entries": False,
        "region_egress_entries_valid": False,
        "opportunities_categories_present": False,
        "opportunities_entries_fields_valid": False,
        "roi_table_min_entries": False,
        "roi_table_entries_valid": False,
        "bicep_snippet_contains_resource": False,
        # recommendations.md checks
        "recommendations_exists": False,
        "recommendations_has_headings": False,
        "recommendations_has_phrase_cdn_cheaper": False,
        "recommendations_mentions_cdn_or_frontdoor": False,
        "recommendations_mentions_private_endpoint": False,
        "recommendations_min_length": False,
    }

    # Paths
    analysis_path = os.path.join(output_dir, "analysis.json")
    recommendations_path = os.path.join(output_dir, "recommendations.md")

    analysis_data: Dict[str, Any] = {}

    # Check analysis.json existence and validity
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                analysis_data = json.load(f)
            if isinstance(analysis_data, dict):
                checks["analysis_json_valid"] = True
        except Exception:
            checks["analysis_json_valid"] = False

    # Validate analysis.json structure if valid
    if checks["analysis_json_valid"]:
        required_keys = [
            "source_files",
            "bandwidth_breakdown",
            "region_egress",
            "opportunities",
            "roi_table",
            "bicep_snippet",
        ]
        has_keys = all(k in analysis_data for k in required_keys)
        if has_keys:
            checks["analysis_has_required_keys"] = True

            # source_files exact match
            if isinstance(analysis_data.get("source_files"), list):
                expected_sources = [
                    "input/cost_bandwidth.csv",
                    "input/usage_network.json",
                    "input/topology_vnets_private_endpoints.json",
                ]
                if analysis_data["source_files"] == expected_sources:
                    checks["analysis_source_files_exact"] = True

            # bandwidth_breakdown
            breakdown = analysis_data.get("bandwidth_breakdown")
            if isinstance(breakdown, list) and len(breakdown) >= 2:
                checks["breakdown_min_entries"] = True
                valid_types = {"inter-region", "internet_egress", "private_link", "other"}
                breakdown_valid = True
                pct_sum = 0.0
                for item in breakdown:
                    if not isinstance(item, dict):
                        breakdown_valid = False
                        break
                    t = item.get("type")
                    mc = item.get("monthly_cost")
                    pt = item.get("percent_of_total")
                    if not (isinstance(t, str) and t in valid_types):
                        breakdown_valid = False
                        break
                    if not (is_number(mc) and mc >= 0):
                        breakdown_valid = False
                        break
                    if not (is_number(pt) and 0 <= pt <= 100):
                        breakdown_valid = False
                        break
                    pct_sum += float(pt)
                if breakdown_valid:
                    checks["breakdown_entries_valid"] = True
                    # Sum between 90 and 110 inclusive
                    if 90.0 <= pct_sum <= 110.0:
                        checks["breakdown_percent_sum_valid"] = True

            # region_egress
            region_egress = analysis_data.get("region_egress")
            if isinstance(region_egress, list) and len(region_egress) >= 2:
                checks["region_egress_min_entries"] = True
                region_entries_valid = True
                for item in region_egress:
                    if not isinstance(item, dict):
                        region_entries_valid = False
                        break
                    region = item.get("region")
                    cost = item.get("egress_cost")
                    if not (isinstance(region, str) and region.strip() != ""):
                        region_entries_valid = False
                        break
                    if not (is_number(cost) and cost >= 0):
                        region_entries_valid = False
                        break
                if region_entries_valid:
                    checks["region_egress_entries_valid"] = True

            # opportunities
            opportunities = analysis_data.get("opportunities")
            if isinstance(opportunities, list) and len(opportunities) >= 1:
                # Check fields and category presence
                allowed_categories = {"CDN", "Front Door", "Private Endpoint", "Lifecycle Policy"}
                fields_valid = True
                has_cdn_or_fd = False
                has_pe = False
                for item in opportunities:
                    if not isinstance(item, dict):
                        fields_valid = False
                        break
                    cat = item.get("category")
                    desc = item.get("description")
                    off = item.get("est_offload_pct")
                    sav = item.get("est_savings_pct")
                    if not (isinstance(cat, str) and cat in allowed_categories):
                        fields_valid = False
                        break
                    if not isinstance(desc, str):
                        fields_valid = False
                        break
                    if off is not None and not is_number(off):
                        fields_valid = False
                        break
                    if sav is not None and not is_number(sav):
                        fields_valid = False
                        break
                    if cat in {"CDN", "Front Door"}:
                        has_cdn_or_fd = True
                    if cat == "Private Endpoint":
                        has_pe = True
                if fields_valid:
                    checks["opportunities_entries_fields_valid"] = True
                if has_cdn_or_fd and has_pe:
                    checks["opportunities_categories_present"] = True

            # roi_table
            roi_table = analysis_data.get("roi_table")
            if isinstance(roi_table, list) and len(roi_table) >= 2:
                checks["roi_table_min_entries"] = True
                roi_entries_valid = True
                for item in roi_table:
                    if not isinstance(item, dict):
                        roi_entries_valid = False
                        break
                    change = item.get("change")
                    effort = item.get("effort")
                    savings = item.get("est_monthly_savings_usd")
                    assumptions = item.get("assumptions")
                    if not isinstance(change, str):
                        roi_entries_valid = False
                        break
                    if effort not in {"Low", "Medium", "High"}:
                        roi_entries_valid = False
                        break
                    if not (is_number(savings) and savings > 0):
                        roi_entries_valid = False
                        break
                    if not (isinstance(assumptions, str) and assumptions.strip() != ""):
                        roi_entries_valid = False
                        break
                if roi_entries_valid:
                    checks["roi_table_entries_valid"] = True

            # bicep_snippet
            bicep_snippet = analysis_data.get("bicep_snippet")
            if isinstance(bicep_snippet, str) and ("Microsoft.Network/privateEndpoints" in bicep_snippet):
                checks["bicep_snippet_contains_resource"] = True

    # Validate recommendations.md
    if os.path.isfile(recommendations_path):
        checks["recommendations_exists"] = True
        try:
            with open(recommendations_path, "r", encoding="utf-8") as f:
                rec_text = f.read()
        except Exception:
            rec_text = ""

        if isinstance(rec_text, str) and rec_text:
            lower = rec_text.lower()

            # Headings presence (case-insensitive substring search)
            headings = [
                "bandwidth breakdown",
                "region egress heatmap",
                "optimization opportunities",
                "roi summary",
                "implementation snippet",
            ]
            if all(h in lower for h in headings):
                checks["recommendations_has_headings"] = True

            # Phrase check (case-insensitive, must contain hyphenated "30-50%")
            phrase = "cdn egress is typically 30-50% cheaper than direct blob egress"
            if phrase in lower:
                checks["recommendations_has_phrase_cdn_cheaper"] = True

            # Mentions CDN or Front Door
            if ("cdn" in lower) or ("front door" in lower):
                checks["recommendations_mentions_cdn_or_frontdoor"] = True

            # Mentions Private Endpoint
            if "private endpoint" in lower:
                checks["recommendations_mentions_private_endpoint"] = True

            # Minimum length
            if len(rec_text) >= 500:
                checks["recommendations_min_length"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if output dir missing or both required artifacts missing, reward = 0.0
    output_exists = os.path.isdir(output_dir)
    if not output_exists:
        reward = 0.0
    else:
        have_any_artifact = checks["analysis_exists"] or checks["recommendations_exists"]
        have_required_any = have_any_artifact
        if not have_required_any:
            reward = 0.0
        else:
            # Partial credit: fraction of passed checks
            reward = passed / total_checks if total_checks > 0 else 0.0

    # Clamp to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print exactly one JSON object as last line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()