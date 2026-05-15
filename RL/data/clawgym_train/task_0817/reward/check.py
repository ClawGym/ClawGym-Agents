import json
import csv
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        return json.loads(data), None
    except Exception as e:
        return None, f"json_parse_error:{e}"


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"read_error:{e}"


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_iso8601(s: str) -> bool:
    try:
        s2 = s
        if isinstance(s2, str) and s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _load_spdx_index(spdx_json: Any) -> Dict[str, Dict[str, Optional[Any]]]:
    index: Dict[str, Dict[str, Optional[Any]]] = {}
    if not isinstance(spdx_json, dict):
        return index
    licenses = spdx_json.get("licenses")
    if not isinstance(licenses, list):
        return index
    for lic in licenses:
        if not isinstance(lic, dict):
            continue
        lic_id = lic.get("licenseId")
        name = lic.get("name")
        if isinstance(lic_id, str) and isinstance(name, str):
            is_osi = lic.get("isOsiApproved", None)
            if not isinstance(is_osi, bool):
                is_osi = None
            is_depr = lic.get("isDeprecatedLicenseId", None)
            if not isinstance(is_depr, bool):
                is_depr = None
            index[lic_id] = {
                "name": name,
                "isOsiApproved": is_osi,
                "isDeprecatedLicenseId": is_depr,
            }
    return index


def _parse_rules_yaml_like(text: str) -> Tuple[List[Tuple[str, List[str]]], Optional[str]]:
    normalized = text.replace("\\n", "\n")
    lines = [ln.rstrip("\r") for ln in normalized.split("\n")]
    in_rules = False
    order: List[Tuple[str, List[str]]] = []
    current_category: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not in_rules:
            if line.startswith("risk_rules:"):
                in_rules = True
            continue
        if not line:
            continue
        if line.endswith(":") and not line.startswith("-"):
            cat = line[:-1].strip()
            if cat:
                current_category = cat
                order.append((current_category, []))
            continue
        if current_category is not None and line.startswith("-"):
            patt = line[1:].strip()
            if (patt.startswith('"') and patt.endswith('"')) or (patt.startswith("'") and patt.endswith("'")):
                patt = patt[1:-1]
            if order and order[-1][0] == current_category:
                order[-1][1].append(patt)
            continue
        if current_category is not None and raw_line.lstrip().startswith("-"):
            patt = raw_line.lstrip()[1:].strip()
            if (patt.startswith('"') and patt.endswith('"')) or (patt.startswith("'") and patt.endswith("'")):
                patt = patt[1:-1]
            if order and order[-1][0] == current_category:
                order[-1][1].append(patt)
            continue

    if not in_rules or not order:
        return [], "parse_error"
    cleaned: List[Tuple[str, List[str]]] = []
    for cat, pats in order:
        if not pats:
            cleaned.append((cat, []))
        else:
            cleaned.append((cat, pats))
    return cleaned, None


def _classify_license(license_id: str, ordered_rules: List[Tuple[str, List[str]]]) -> str:
    for category, patterns in ordered_rules:
        for patt in patterns:
            try:
                if re.search(patt, license_id):
                    return category
            except re.error:
                continue
    return "unknown"


def _parse_csv_bool(value: str) -> Optional[bool]:
    if value is None:
        return None
    s = value.strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f"):
        return False
    if s in ("", "null", "none", "na", "n/a"):
        return None
    return None


def _ensure_bool_or_none(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "provenance_fields_present": 0.0,
        "provenance_retrieved_at_iso8601": 0.0,
        "spdx_source_domain_acceptable": 0.0,
        "provenance_local_path_correct": 0.0,
        "spdx_download_hash_matches_provenance": 0.0,
        "spdx_json_valid_structure": 0.0,
        "search_queries_documented": 0.0,
        "report_json_valid_structure": 0.0,
        "report_fields_consistency": 0.0,
        "report_spdx_recognition_correct": 0.0,
        "report_risk_classification_correct": 0.0,
        "summary_json_valid_structure": 0.0,
        "summary_counts_correct": 0.0,
        "csv_valid_structure": 0.0,
        "dependencies_covered_unique": 0.0,
        "csv_classification_matches": 0.0,
    }

    input_deps_path = workspace / "input" / "game_dependencies.json"
    deps_json, _ = _read_json(input_deps_path)
    deps_list: List[Dict[str, Any]] = []
    if isinstance(deps_json, dict) and isinstance(deps_json.get("dependencies"), list):
        deps_list = deps_json["dependencies"]

    rules_path = workspace / "input" / "license_risk_rules.yaml"
    rules_text, _ = _read_text(rules_path)
    ordered_rules: List[Tuple[str, List[str]]] = []
    if rules_text is not None:
        ordered_rules, rules_parse_err = _parse_rules_yaml_like(rules_text)
        if rules_parse_err is not None:
            ordered_rules = []

    provenance_path = workspace / "outputs" / "provenance.json"
    spdx_path = workspace / "outputs" / "spdx_license_list.json"
    report_path = workspace / "outputs" / "license_risk_report.json"
    summary_path = workspace / "outputs" / "license_risk_summary.json"
    csv_path = workspace / "outputs" / "classified_licenses.csv"

    prov_json, _ = _read_json(provenance_path)
    spdx_json, _ = _read_json(spdx_path)
    report_json, _ = _read_json(report_path)
    summary_json, _ = _read_json(summary_path)

    spdx_index: Dict[str, Dict[str, Optional[Any]]] = {}
    if spdx_json is not None and isinstance(spdx_json, dict):
        spdx_index = _load_spdx_index(spdx_json)

    prov_required_fields = ["organization", "resource_name", "retrieved_from_domain", "retrieved_at", "local_path", "sha256"]
    prov_ok = False
    if isinstance(prov_json, dict):
        missing = [k for k in prov_required_fields if k not in prov_json]
        if not missing:
            prov_ok = True
    if prov_ok:
        scores["provenance_fields_present"] = 1.0
        r_at = prov_json.get("retrieved_at")
        if isinstance(r_at, str) and _parse_iso8601(r_at):
            scores["provenance_retrieved_at_iso8601"] = 1.0
        if prov_json.get("local_path") == "outputs/spdx_license_list.json":
            scores["provenance_local_path_correct"] = 1.0
        domain = prov_json.get("retrieved_from_domain")
        if isinstance(domain, str):
            dom = domain.lower()
            if ("spdx.org" in dom) or ("github.com" in dom) or ("raw.githubusercontent.com" in dom) or ("git.spdx.org" in dom):
                scores["spdx_source_domain_acceptable"] = 1.0
        spdx_hash = _sha256_file(spdx_path)
        prov_sha = prov_json.get("sha256") if isinstance(prov_json.get("sha256"), str) else None
        if spdx_hash is not None and prov_sha is not None and spdx_hash == prov_sha:
            scores["spdx_download_hash_matches_provenance"] = 1.0
        documented = False
        for key in ["search_queries", "queries", "searches", "search_terms", "search_query"]:
            if key in prov_json:
                val = prov_json[key]
                if isinstance(val, list):
                    if all(isinstance(x, str) and x.strip() for x in val) and len(val) > 0:
                        documented = True
                elif isinstance(val, str):
                    if val.strip():
                        documented = True
        if documented:
            scores["search_queries_documented"] = 1.0

    if isinstance(spdx_json, dict) and isinstance(spdx_json.get("licenses"), list):
        licenses = spdx_json.get("licenses")
        valid_any = False
        for lic in licenses:
            if isinstance(lic, dict) and isinstance(lic.get("licenseId"), str) and isinstance(lic.get("name"), str):
                valid_any = True
                break
        if valid_any:
            scores["spdx_json_valid_structure"] = 1.0

    report_valid_structure = False
    if isinstance(report_json, list) and isinstance(deps_list, list) and deps_list:
        if len(report_json) == len(deps_list):
            required_fields = [
                "name",
                "version",
                "license_id",
                "license_name",
                "risk_category",
                "is_spdx_recognized",
                "is_osi_approved",
                "is_deprecated_license_id",
                "source",
                "notes",
            ]
            types_ok = True
            for item in report_json:
                if not isinstance(item, dict):
                    types_ok = False
                    break
                for k in required_fields:
                    if k not in item:
                        types_ok = False
                        break
                if not types_ok:
                    break
            if types_ok:
                report_valid_structure = True
                scores["report_json_valid_structure"] = 1.0

    if report_valid_structure and spdx_index is not None:
        fields_consistent = True
        spdx_recognition_ok = True
        classification_ok = True
        rules_available = len(ordered_rules) > 0

        for i, dep in enumerate(deps_list):
            rep = report_json[i]
            if rep.get("name") != dep.get("name") or rep.get("version") != dep.get("version") or rep.get("license_id") != dep.get("license") or rep.get("source") != dep.get("source"):
                fields_consistent = False
            if "notes" not in rep:
                fields_consistent = False

            lic_id = dep.get("license")
            recognized = lic_id in spdx_index
            if rep.get("is_spdx_recognized") is not recognized:
                spdx_recognition_ok = False
            if recognized:
                expected_name = spdx_index[lic_id]["name"]
                expected_osi = _ensure_bool_or_none(spdx_index[lic_id]["isOsiApproved"])
                expected_depr = _ensure_bool_or_none(spdx_index[lic_id]["isDeprecatedLicenseId"])
                if rep.get("license_name") != expected_name:
                    spdx_recognition_ok = False
                if rep.get("is_osi_approved") is not expected_osi:
                    spdx_recognition_ok = False
                if rep.get("is_deprecated_license_id") is not expected_depr:
                    spdx_recognition_ok = False
            else:
                if rep.get("license_name") is not None:
                    spdx_recognition_ok = False
                if rep.get("is_osi_approved") is not None:
                    spdx_recognition_ok = False
                if rep.get("is_deprecated_license_id") is not None:
                    spdx_recognition_ok = False
            if rules_available:
                expected_category = _classify_license(lic_id, ordered_rules)
                if rep.get("risk_category") != expected_category:
                    classification_ok = False

        if fields_consistent:
            scores["report_fields_consistency"] = 1.0
        if spdx_recognition_ok:
            scores["report_spdx_recognition_correct"] = 1.0
        if classification_ok and rules_available:
            scores["report_risk_classification_correct"] = 1.0

    summary_valid = False
    if isinstance(summary_json, dict):
        required_sum = ["total_dependencies", "recognized_spdx", "unrecognized_spdx", "deprecated_licenses", "osi_approved", "by_risk_category"]
        if all(k in summary_json for k in required_sum) and isinstance(summary_json.get("by_risk_category"), dict):
            summary_valid = True
            scores["summary_json_valid_structure"] = 1.0

    if summary_valid and report_valid_structure:
        total = len(report_json)
        recognized = sum(1 for item in report_json if item.get("is_spdx_recognized") is True)
        unrecognized = sum(1 for item in report_json if item.get("is_spdx_recognized") is False)
        deprecated = sum(1 for item in report_json if item.get("is_deprecated_license_id") is True)
        osi_approved = sum(1 for item in report_json if item.get("is_osi_approved") is True)
        by_cat: Dict[str, int] = {}
        for item in report_json:
            cat = item.get("risk_category")
            if isinstance(cat, str):
                by_cat[cat] = by_cat.get(cat, 0) + 1
        summary_ok = True
        summary_ok = summary_ok and (summary_json.get("total_dependencies") == total)
        summary_ok = summary_ok and (summary_json.get("recognized_spdx") == recognized)
        summary_ok = summary_ok and (summary_json.get("unrecognized_spdx") == unrecognized)
        summary_ok = summary_ok and (summary_json.get("deprecated_licenses") == deprecated)
        summary_ok = summary_ok and (summary_json.get("osi_approved") == osi_approved)
        by_cat_json = summary_json.get("by_risk_category")
        if isinstance(by_cat_json, dict):
            for k, v in by_cat.items():
                if by_cat_json.get(k) != v:
                    summary_ok = False
                    break
        else:
            summary_ok = False
        if summary_ok:
            scores["summary_counts_correct"] = 1.0

    csv_structure_ok = False
    csv_rows: List[Dict[str, str]] = []
    if csv_path.exists():
        try:
            with csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                expected_header = ["license_id", "license_name", "risk_category", "is_osi_approved", "is_deprecated", "spdx_recognized"]
                if header == expected_header:
                    for row in reader:
                        csv_rows.append(row)
                    csv_structure_ok = True
                    scores["csv_valid_structure"] = 1.0
        except Exception:
            csv_structure_ok = False

    if csv_structure_ok and deps_list:
        unique_licenses = []
        seen = set()
        for dep in deps_list:
            lic = dep.get("license")
            if isinstance(lic, str) and lic not in seen:
                unique_licenses.append(lic)
                seen.add(lic)
        csv_ids = [row.get("license_id") for row in csv_rows if isinstance(row, dict)]
        if set(csv_ids) == set(unique_licenses) and len(csv_ids) == len(unique_licenses):
            scores["dependencies_covered_unique"] = 1.0

        class_ok = True
        rules_available = len(ordered_rules) > 0
        for row in csv_rows:
            lic_id = row.get("license_id", "")
            rec_flag = _parse_csv_bool(row.get("spdx_recognized", ""))
            recognized = lic_id in spdx_index
            if rec_flag is None or rec_flag != recognized:
                class_ok = False
            if rules_available:
                expected_cat = _classify_license(lic_id, ordered_rules)
                if row.get("risk_category") != expected_cat:
                    class_ok = False
            if recognized:
                expected_name = spdx_index[lic_id]["name"]
                if row.get("license_name") != expected_name:
                    class_ok = False
                exp_osi = _ensure_bool_or_none(spdx_index[lic_id]["isOsiApproved"])
                exp_depr = _ensure_bool_or_none(spdx_index[lic_id]["isDeprecatedLicenseId"])
                got_osi = _parse_csv_bool(row.get("is_osi_approved", ""))
                got_depr = _parse_csv_bool(row.get("is_deprecated", ""))
                if got_osi is None or got_osi != exp_osi:
                    class_ok = False
                if got_depr is None or got_depr != exp_depr:
                    class_ok = False
            else:
                name_val = row.get("license_name")
                if name_val not in ("", None):
                    class_ok = False
                osi_val = _parse_csv_bool(row.get("is_osi_approved", ""))
                depr_val = _parse_csv_bool(row.get("is_deprecated", ""))
                if osi_val is not None or depr_val is not None:
                    class_ok = False
        if class_ok and rules_available:
            scores["csv_classification_matches"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()