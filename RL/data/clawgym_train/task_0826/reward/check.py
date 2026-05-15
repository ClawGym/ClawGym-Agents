import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_files(root: str, rel_glob: str) -> List[str]:
    # simple recursive matcher for *.json
    out = []
    base = os.path.join(root, rel_glob.split("/")[0])
    if not os.path.exists(base):
        return out
    # Support only one-level wildcard for our use-case input/ci_runs/*.json
    parts = rel_glob.split("/")
    if len(parts) == 3 and parts[2].endswith(".json"):
        dir_path = os.path.join(root, parts[0], parts[1])
        if os.path.isdir(dir_path):
            for name in sorted(os.listdir(dir_path)):
                if name.endswith(".json"):
                    out.append(os.path.join(dir_path, name))
    else:
        # fallback: walk all under base and match suffix
        suffix = rel_glob.split("*")[-1] if "*" in rel_glob else ""
        for dirpath, _, filenames in os.walk(base):
            for fn in filenames:
                if suffix and fn.endswith(suffix):
                    out.append(os.path.join(dirpath, fn))
    return sorted(out)

def check_memory_md(content: str) -> bool:
    # Check required sections/fields in memory.md
    lc = content.lower()
    required_phrases = [
        "## status",
        "phase:",
        "## the move",
        "origin:",
        "destination:",
        "target_date:",
        "visa_type:",
        "visa_status:",
        "## situation",
        "## key dates",
        "visa application deadline",
        "lease end date (origin)",
        "flight booked",
        "registration deadline (destination)",
        "## preferences",
        "## notes",
        "updated:"
    ]
    for phrase in required_phrases:
        if phrase not in lc:
            return False
    return True

def table_header_present(doc: str, header: str) -> bool:
    lines = [l.strip().lower() for l in doc.splitlines()]
    target = "|".join([p.strip() for p in header.lower().split("|")])
    for line in lines:
        if "|" in line:
            normalized = "|".join([p.strip() for p in line.split("|")])
            if normalized == target:
                return True
    return False

def check_documents_md(content: str) -> bool:
    lc = content.lower()
    if "## status legend" not in lc:
        return False
    # Check four tables with correct headers
    personal_hdr = "Document | Status | Expiry | Location | Notes"
    visa_hdr = "Document | Status | Submitted | Notes"
    origin_hdr = "Task | Status | Deadline | Notes"
    dest_hdr = "Task | Status | Deadline | Notes"
    ok = True
    ok = ok and table_header_present(content, personal_hdr)
    ok = ok and table_header_present(content, visa_hdr)
    ok = ok and table_header_present(content, origin_hdr)
    ok = ok and table_header_present(content, dest_hdr)
    return ok

def check_country_md(content: str) -> bool:
    lc = content.lower()
    sections = [
        "# portugal research",
        "## visa options",
        "## key requirements",
        "## tax situation",
        "## banking",
        "## healthcare",
        "## housing",
        "## registration",
        "## useful links",
        "## personal notes",
        "researched:"
    ]
    for s in sections:
        if s not in lc:
            return False
    return True

def check_taxonomy_json(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    required = [
        "validation",
        "authentication",
        "authorization",
        "not_found",
        "conflict",
        "rate_limit",
        "dependency_failure",
        "internal",
    ]
    for key in required:
        if key not in payload:
            return False
        entry = payload[key]
        if not isinstance(entry, dict):
            return False
        # Expect stable code and owner
        if "code" not in entry or "owner" not in entry:
            return False
        if not isinstance(entry["code"], str) or not entry["code"]:
            return False
        if not isinstance(entry["owner"], str) or not entry["owner"]:
            return False
    return True

def check_transport_md(content: str) -> bool:
    lc = content.lower()
    # Must mention HTTP status codes and support reference id guidance
    codes = ["400", "401", "403", "404", "409", "429", "500"]
    if not all(code in lc for code in codes):
        return False
    # user-safe messages and opaque support reference ID
    if ("support reference id" not in lc and "reference id" not in lc and "correlation id" not in lc):
        return False
    # Should discourage leaking internal details
    if ("stack trace" not in lc and "internal" not in lc):
        # be lenient but expect mention of safety
        pass
    return True

def check_retry_md(content: str) -> bool:
    lc = content.lower()
    required_terms = ["exponential", "jitter", "idempotency", "idempotency key"]
    return all(term in lc for term in required_terms)

def check_observability_md(content: str) -> bool:
    lc = content.lower()
    return ("error.code" in lc and "trace_id" in lc and "user_id" in lc and "metrics" in lc and ("alert" in lc or "slo" in lc))

def check_manifest_json(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("domain") != "expat_helper":
        return False
    if not isinstance(payload.get("name"), str):
        return False
    if not isinstance(payload.get("version"), str):
        return False
    if payload.get("config_flow") is not True:
        return False
    return True

def check_services_yaml(content: str) -> bool:
    lc = content.lower()
    # Ensure at least one service consistent with returning data (get_status or get_full_config)
    return ("get_status" in lc) or ("get_full_config" in lc)

def check_init_service(content: str) -> bool:
    lc = content.lower()
    # Must register a service capable of returning data
    # Look for supports_response and a non-empty return
    has_supports_response = ("supports_response" in lc) or ("supportsresponse" in lc)
    # Non-empty return: not returning {} or []
    has_return_data = ("return {" in content) or ("return {" in content) or ("return dict(" in lc)
    returns_empty_dict = "return {}" in lc
    returns_empty_list = "return []" in lc
    return has_supports_response and has_return_data and not (returns_empty_dict or returns_empty_list)

def check_http_view(content: str) -> bool:
    lc = content.lower()
    # Authenticated endpoint returning JSON
    auth = "requires_auth = true" in lc or "requires_auth=True" in content
    returns_json = ("json_response(" in content) or ("return {" in content) or ("application/json" in lc)
    return auth and returns_json

def check_no_private_api(content_files: List[str]) -> bool:
    # Ensure no underscore-prefixed internal API reference string
    for path in content_files:
        txt = read_text(path)
        if "_storage_collection" in txt:
            return False
    return True

def check_storage_public_reference(content_files: List[str]) -> bool:
    # At least one file references public storage helper concept "Store" or "storage helper"
    for path in content_files:
        txt = read_text(path)
        if "Store" in txt or "storage helper" in txt.lower():
            return True
    return False

def is_sorted_desc_by_risk(groups: List[Dict[str, Any]]) -> bool:
    last = float("inf")
    for g in groups:
        rs = g.get("risk_score")
        try:
            rsf = float(rs)
        except Exception:
            return False
        if rsf > last + 1e-9:
            return False
        last = rsf
    return True

def check_ci_report_structure(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
    if "summary" not in report or "groups" not in report:
        return False
    summary = report.get("summary")
    groups = report.get("groups")
    if not isinstance(summary, dict) or not isinstance(groups, list):
        return False
    required_summary = ["files_scanned", "groups", "critical_groups", "evaluated_at"]
    for k in required_summary:
        if k not in summary:
            return False
    # validate groups entries
    for g in groups:
        if not isinstance(g, dict):
            return False
        req_fields = ["workflow", "rerun_runs", "total_runs", "rerun_rate", "rerun_success_rate", "wasted_minutes", "severity", "risk_score"]
        for f in req_fields:
            if f not in g:
                return False
        try:
            rr = float(g["rerun_rate"])
            rs = float(g["rerun_success_rate"])
            wm = float(g["wasted_minutes"])
            if not (0.0 <= rr <= 1.0):
                return False
            if not (0.0 <= rs <= 1.0):
                return False
            if wm < 0:
                return False
        except Exception:
            return False
        if not isinstance(g["workflow"], str):
            return False
    # Check sorted by risk_score desc
    if not is_sorted_desc_by_risk(groups):
        return False
    return True

def compute_input_ci_counts(input_ci_dir: str) -> int:
    if not os.path.isdir(input_ci_dir):
        return 0
    cnt = 0
    for name in os.listdir(input_ci_dir):
        if name.endswith(".json") and os.path.isfile(os.path.join(input_ci_dir, name)):
            cnt += 1
    return cnt

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Paths
    memory_md = os.path.join(output_dir, "expat", "memory.md")
    documents_md = os.path.join(output_dir, "expat", "documents.md")
    portugal_md = os.path.join(output_dir, "expat", "countries", "Portugal.md")

    taxonomy_json = os.path.join(output_dir, "error_handling", "taxonomy.json")
    transport_md = os.path.join(output_dir, "error_handling", "transport.md")
    retry_md = os.path.join(output_dir, "error_handling", "retry.md")
    observability_md = os.path.join(output_dir, "error_handling", "observability.md")

    ha_root = os.path.join(output_dir, "ha_integration")
    ha_readme = os.path.join(ha_root, "README.md")
    ha_comp_dir = os.path.join(ha_root, "custom_components", "expat_helper")
    ha_init = os.path.join(ha_comp_dir, "__init__.py")
    ha_config_flow = os.path.join(ha_comp_dir, "config_flow.py")
    ha_manifest = os.path.join(ha_comp_dir, "manifest.json")
    ha_services = os.path.join(ha_comp_dir, "services.yaml")
    ha_http_view = os.path.join(ha_comp_dir, "http_view.py")

    ci_report = os.path.join(output_dir, "ci", "audit", "report.json")
    assumptions_md = os.path.join(output_dir, "assumptions.md")

    # Existence checks for required files/directories
    checks["expat_memory_exists"] = os.path.isfile(memory_md)
    checks["expat_documents_exists"] = os.path.isfile(documents_md)
    checks["expat_country_portugal_exists"] = os.path.isfile(portugal_md)

    checks["error_taxonomy_exists"] = os.path.isfile(taxonomy_json)
    checks["error_transport_exists"] = os.path.isfile(transport_md)
    checks["error_retry_exists"] = os.path.isfile(retry_md)
    checks["error_observability_exists"] = os.path.isfile(observability_md)

    checks["ha_init_exists"] = os.path.isfile(ha_init)
    checks["ha_config_flow_exists"] = os.path.isfile(ha_config_flow)
    checks["ha_manifest_exists"] = os.path.isfile(ha_manifest)
    checks["ha_services_exists"] = os.path.isfile(ha_services)
    checks["ha_http_view_exists"] = os.path.isfile(ha_http_view)
    checks["ha_readme_exists"] = os.path.isfile(ha_readme)

    checks["ci_report_exists"] = os.path.isfile(ci_report)
    checks["assumptions_optional_exists"] = os.path.isfile(assumptions_md)

    # Content validations
    checks["expat_memory_fields_valid"] = False
    checks["expat_documents_tables_valid"] = False
    checks["expat_country_sections_valid"] = False
    if checks["expat_memory_exists"]:
        mem_txt = read_text(memory_md)
        checks["expat_memory_fields_valid"] = check_memory_md(mem_txt)
    if checks["expat_documents_exists"]:
        docs_txt = read_text(documents_md)
        checks["expat_documents_tables_valid"] = check_documents_md(docs_txt)
    if checks["expat_country_portugal_exists"]:
        country_txt = read_text(portugal_md)
        checks["expat_country_sections_valid"] = check_country_md(country_txt)

    checks["error_taxonomy_valid"] = False
    if checks["error_taxonomy_exists"]:
        taxonomy = load_json(taxonomy_json)
        checks["error_taxonomy_valid"] = check_taxonomy_json(taxonomy)

    checks["error_transport_valid"] = False
    if checks["error_transport_exists"]:
        checks["error_transport_valid"] = check_transport_md(read_text(transport_md))

    checks["error_retry_valid"] = False
    if checks["error_retry_exists"]:
        checks["error_retry_valid"] = check_retry_md(read_text(retry_md))

    checks["error_observability_valid"] = False
    if checks["error_observability_exists"]:
        checks["error_observability_valid"] = check_observability_md(read_text(observability_md))

    checks["ha_manifest_valid"] = False
    if checks["ha_manifest_exists"]:
        checks["ha_manifest_valid"] = check_manifest_json(load_json(ha_manifest))

    checks["ha_services_valid"] = False
    if checks["ha_services_exists"]:
        checks["ha_services_valid"] = check_services_yaml(read_text(ha_services))

    checks["ha_init_service_returns_data"] = False
    if checks["ha_init_exists"]:
        checks["ha_init_service_returns_data"] = check_init_service(read_text(ha_init))

    checks["ha_http_view_auth_json"] = False
    if checks["ha_http_view_exists"]:
        checks["ha_http_view_auth_json"] = check_http_view(read_text(ha_http_view))

    # Check for no private API usage and public storage reference
    ha_files_to_scan = []
    if os.path.isdir(ha_comp_dir):
        for name in os.listdir(ha_comp_dir):
            if name.endswith(".py") or name.endswith(".yaml") or name.endswith(".json") or name.endswith(".md"):
                ha_files_to_scan.append(os.path.join(ha_comp_dir, name))
    checks["ha_no_private_api"] = check_no_private_api(ha_files_to_scan)
    checks["ha_storage_public_reference"] = check_storage_public_reference(ha_files_to_scan)

    checks["ha_readme_checklist"] = False
    if checks["ha_readme_exists"]:
        rd = read_text(ha_readme).lower()
        checks["ha_readme_checklist"] = (("service returns data" in rd) and (("authenticated http endpoint" in rd) or ("requires_auth" in rd)))

    # CI report validations
    checks["ci_report_structure_valid"] = False
    checks["ci_report_files_scanned_match"] = False
    if checks["ci_report_exists"]:
        report = load_json(ci_report)
        if check_ci_report_structure(report):
            checks["ci_report_structure_valid"] = True
            # Check files_scanned matches input/ci_runs/*.json count
            input_ci_dir = os.path.join(input_dir, "ci_runs")
            expected_files_scanned = compute_input_ci_counts(input_ci_dir)
            try:
                checks["ci_report_files_scanned_match"] = (int(report["summary"]["files_scanned"]) == expected_files_scanned)
            except Exception:
                checks["ci_report_files_scanned_match"] = False

    # Determine scored checks
    scored_keys = [
        "expat_memory_exists",
        "expat_memory_fields_valid",
        "expat_documents_exists",
        "expat_documents_tables_valid",
        "expat_country_portugal_exists",
        "expat_country_sections_valid",
        "error_taxonomy_exists",
        "error_taxonomy_valid",
        "error_transport_exists",
        "error_transport_valid",
        "error_retry_exists",
        "error_retry_valid",
        "error_observability_exists",
        "error_observability_valid",
        "ha_init_exists",
        "ha_init_service_returns_data",
        "ha_config_flow_exists",
        "ha_manifest_exists",
        "ha_manifest_valid",
        "ha_services_exists",
        "ha_services_valid",
        "ha_http_view_exists",
        "ha_http_view_auth_json",
        "ha_no_private_api",
        "ha_storage_public_reference",
        "ha_readme_exists",
        "ha_readme_checklist",
        "ci_report_exists",
        "ci_report_structure_valid",
        "ci_report_files_scanned_match",
    ]

    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    reward = (passed / total) if total > 0 else 0.0

    # Ensure exact 0.0 for no-op baseline (empty or missing output)
    output_exists = os.path.isdir(output_dir) and any(os.scandir(output_dir))
    if not output_exists:
        reward = 0.0
        # Set all checks to False explicitly
        for k in scored_keys:
            checks[k] = False

    result = {"reward": round(reward, 6)}
    # Append all checks
    result.update({k: bool(v) for k, v in checks.items()})
    print(json.dumps(result))

if __name__ == "__main__":
    main()