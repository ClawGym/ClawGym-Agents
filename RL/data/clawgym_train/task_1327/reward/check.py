import json
import sys
import re
import csv
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_manifest_images(text: str) -> List[str]:
    images: List[str] = []
    for line in text.splitlines():
        # strip comments
        line_no_comment = line.split("#", 1)[0]
        m = re.match(r'^\s*image:\s*(.+?)\s*$', line_no_comment)
        if m:
            val = m.group(1).strip()
            # strip surrounding quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if val:
                images.append(val)
    return images


def _parse_policy_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Very simple YAML parser for the specific structure in license_policy.yaml
    allowed: List[str] = []
    banned: List[str] = []
    restricted_map: Dict[str, Dict[str, Any]] = {}

    lines = text.splitlines()
    section = None
    i = 0
    current_restricted_id = None
    in_obligations = False

    while i < len(lines):
        raw = lines[i]
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            i += 1
            continue

        # Enter sections (we ignore parent "rules:" and match by key names)
        if re.match(r'^\s*allowed:\s*$', line):
            section = "allowed"
            in_obligations = False
            current_restricted_id = None
            i += 1
            continue
        if re.match(r'^\s*restricted:\s*$', line):
            section = "restricted"
            in_obligations = False
            current_restricted_id = None
            i += 1
            continue
        if re.match(r'^\s*banned:\s*$', line):
            section = "banned"
            in_obligations = False
            current_restricted_id = None
            i += 1
            continue

        if section == "allowed":
            m = re.match(r'^\s*-\s*(\S+)\s*$', line)
            if m:
                allowed.append(m.group(1))
        elif section == "banned":
            m = re.match(r'^\s*-\s*(\S+)\s*$', line)
            if m:
                banned.append(m.group(1))
        elif section == "restricted":
            # Detect new item "- id: <id>"
            m_item = re.match(r'^\s*-\s*id:\s*(\S+)\s*$', line)
            if m_item:
                current_restricted_id = m_item.group(1)
                restricted_map[current_restricted_id] = {"obligations": [], "condition": None}
                in_obligations = False
                i += 1
                continue
            if current_restricted_id is not None:
                if re.match(r'^\s*obligations:\s*$', line):
                    in_obligations = True
                    i += 1
                    continue
                if in_obligations:
                    m_ob = re.match(r'^\s*-\s*(\S+)\s*$', line)
                    if m_ob:
                        restricted_map[current_restricted_id]["obligations"].append(m_ob.group(1))
                        i += 1
                        continue
                    else:
                        in_obligations = False
                m_cond = re.match(r'^\s*condition:\s*(.+?)\s*$', line)
                if m_cond:
                    restricted_map[current_restricted_id]["condition"] = m_cond.group(1)
        i += 1

    return {
        "allowed": set(allowed),
        "banned": set(banned),
        "restricted": restricted_map,
    }


def _parse_overrides_yaml(text: str) -> Optional[Dict[str, Dict[str, Any]]]:
    # Parse overrides: - image: <...> \n exceptions: \n   key: value
    overrides: Dict[str, Dict[str, Any]] = {}
    lines = text.splitlines()
    current_image: Optional[str] = None
    in_exceptions = False
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m_img = re.match(r'^\s*-\s*image:\s*(\S+)\s*$', line)
        if m_img:
            current_image = m_img.group(1)
            overrides[current_image] = {}
            in_exceptions = False
            continue
        if current_image is not None:
            if re.match(r'^\s*exceptions:\s*$', line):
                in_exceptions = True
                continue
            if in_exceptions:
                m_kv = re.match(r'^\s*([A-Za-z0-9_.-]+)\s*:\s*(\S+)\s*$', line)
                if m_kv:
                    key = m_kv.group(1)
                    val = m_kv.group(2)
                    if val.lower() in ("true", "false"):
                        parsed_val: Any = val.lower() == "true"
                    else:
                        parsed_val = val
                    overrides[current_image][key] = parsed_val
    return overrides


def _load_sboms(sbom_dir: Path) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    if not sbom_dir.exists() or not sbom_dir.is_dir():
        return mapping
    for p in sbom_dir.glob("*.json"):
        obj = _load_json(p)
        if isinstance(obj, dict) and "image" in obj and "packages" in obj:
            img = obj["image"]
            if isinstance(img, str) and isinstance(obj["packages"], list):
                mapping[img] = obj
    return mapping


def _evaluate_condition(condition: Optional[str], image_exceptions: Dict[str, Any]) -> bool:
    if not condition:
        return True
    cond = condition.strip()
    # Support: exceptions.key == true|false
    m = re.match(r'^exceptions\.([A-Za-z0-9_.-]+)\s*==\s*(true|false)\s*$', cond, flags=re.IGNORECASE)
    if not m:
        return False
    key = m.group(1)
    expected = m.group(2).lower() == "true"
    actual = image_exceptions.get(key, False)
    # Normalize string bool
    if isinstance(actual, str):
        val = actual.lower() == "true"
    else:
        val = bool(actual)
    return val == expected


def _compute_expected(images: List[str], sbom_map: Dict[str, Dict[str, Any]], policy: Dict[str, Any], overrides: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # Ensure SBOMs exist for all images
    for img in images:
        if img not in sbom_map:
            return None

    allowed: set = policy.get("allowed", set())
    banned: set = policy.get("banned", set())
    restricted_map: Dict[str, Dict[str, Any]] = policy.get("restricted", {})

    result_by_image: Dict[str, Dict[str, Any]] = {}
    totals = {"pass": 0, "fail": 0}

    for img in images:
        sbom = sbom_map[img]
        packages = sbom.get("packages", [])
        license_counts: Dict[str, int] = {}
        violations: List[Dict[str, str]] = []
        obligations_met: List[str] = []
        exceptions = overrides.get(img, {}) if overrides else {}

        for pkg in packages:
            name = pkg.get("name")
            lic = pkg.get("license")
            if not isinstance(name, str) or not isinstance(lic, str):
                # Malformed package entry, treat as non-compliant for safety
                violations.append({"package": str(name), "license": str(lic), "rule": "banned"})
                continue
            license_counts[lic] = license_counts.get(lic, 0) + 1
            if lic in banned:
                violations.append({"package": name, "license": lic, "rule": "banned"})
            elif lic in allowed:
                pass
            elif lic in restricted_map:
                rinfo = restricted_map[lic]
                cond = rinfo.get("condition")
                obligations = rinfo.get("obligations", []) if isinstance(rinfo.get("obligations"), list) else []
                if cond:
                    if _evaluate_condition(cond, exceptions):
                        for ob in obligations:
                            if ob not in obligations_met:
                                obligations_met.append(ob)
                    else:
                        violations.append({"package": name, "license": lic, "rule": "restricted_unmet"})
                else:
                    for ob in obligations:
                        if ob not in obligations_met:
                            obligations_met.append(ob)
            else:
                # Unknown license per policy: treat as allowed (no rule), per task spec does not ban unknown.
                pass

        status = "fail" if len(violations) > 0 else "pass"
        totals[status] += 1
        result_by_image[img] = {
            "image": img,
            "status": status,
            "license_counts": license_counts,
            "violations": violations,
            "obligations_met": obligations_met if status == "pass" else [],
        }

    expected = {
        "total_images": len(images),
        "pass": totals["pass"],
        "fail": totals["fail"],
        "images": result_by_image,
    }
    return expected


def _safe_int(val) -> Optional[int]:
    try:
        if isinstance(val, bool):
            return None
        return int(val)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "manifest_images_extracted": 0.0,
        "sboms_available_for_all_images": 0.0,
        "compliance_summary_present_and_well_formed": 0.0,
        "json_images_coverage_exact": 0.0,
        "json_statuses_correct": 0.0,
        "json_totals_correct": 0.0,
        "json_license_counts_correct": 0.0,
        "json_violations_correct": 0.0,
        "json_obligations_met_correct_for_passing": 0.0,
        "violations_csv_header_and_count_correct": 0.0,
        "violations_csv_matches_json": 0.0,
        "report_file_exists_and_non_empty": 0.0,
        "status_summary_sentences_and_content": 0.0,
        "validation_log_contains_pass_line": 0.0,
    }

    # Paths
    manifest_path = workspace / "input" / "k8s" / "deploy.yaml"
    policy_path = workspace / "input" / "policy" / "license_policy.yaml"
    overrides_path = workspace / "input" / "policy" / "compliance_overrides.yaml"
    sbom_dir = workspace / "input" / "sbom"

    # Outputs
    summary_json_path = workspace / "outputs" / "compliance_summary.json"
    violations_csv_path = workspace / "outputs" / "violations.csv"
    report_md_path = workspace / "outputs" / "compliance_report.md"
    status_txt_path = workspace / "outputs" / "status_summary.txt"
    validation_log_path = workspace / "logs" / "validation.txt"

    # Parse manifest images
    manifest_text = _read_text(manifest_path)
    manifest_images: List[str] = []
    if manifest_text is not None:
        manifest_images = _parse_manifest_images(manifest_text)

    # Load policy and overrides
    policy_text = _read_text(policy_path)
    policy = _parse_policy_yaml(policy_text) if policy_text is not None else None
    overrides_text = _read_text(overrides_path)
    overrides = _parse_overrides_yaml(overrides_text) if overrides_text is not None else None

    # Load SBOMs
    sbom_map = _load_sboms(sbom_dir)

    # Determine if SBOMs are available for all manifest images
    have_all_sboms = False
    if manifest_images:
        have_all_sboms = all(img in sbom_map for img in manifest_images)

    # Only award input-derived checks when there is at least one produced output (to avoid rewarding scaffolding)
    produced_any_output = summary_json_path.exists() or violations_csv_path.exists() or report_md_path.exists() or status_txt_path.exists()
    if produced_any_output:
        if len(manifest_images) > 0:
            scores["manifest_images_extracted"] = 1.0
        if have_all_sboms:
            scores["sboms_available_for_all_images"] = 1.0

    # Compute expected results if possible
    expected = None
    if manifest_images and policy is not None and overrides is not None and have_all_sboms:
        expected = _compute_expected(manifest_images, sbom_map, policy, overrides)

    # Read actual compliance_summary.json
    actual_summary = None
    if summary_json_path.exists():
        actual_summary = _load_json(summary_json_path)

    # Validate summary structure
    actual_images_list: List[dict] = []
    if isinstance(actual_summary, dict):
        has_keys = (
            "total_images" in actual_summary and
            "pass" in actual_summary and
            "fail" in actual_summary and
            "images" in actual_summary and
            isinstance(actual_summary.get("images"), list)
        )
        # Basic type checks
        if has_keys and _safe_int(actual_summary.get("total_images")) is not None and _safe_int(actual_summary.get("pass")) is not None and _safe_int(actual_summary.get("fail")) is not None:
            # Validate each image entry has expected fields
            good_images_entries = True
            for item in actual_summary["images"]:
                if not isinstance(item, dict):
                    good_images_entries = False
                    break
                if not all(k in item for k in ["image", "status", "license_counts", "violations", "obligations_met"]):
                    good_images_entries = False
                    break
                if not isinstance(item["image"], str):
                    good_images_entries = False
                    break
                if item["status"] not in ("pass", "fail"):
                    good_images_entries = False
                    break
                if not isinstance(item["license_counts"], dict):
                    good_images_entries = False
                    break
                if not isinstance(item["violations"], list):
                    good_images_entries = False
                    break
                if not isinstance(item["obligations_met"], list):
                    good_images_entries = False
                    break
                # Validate violations structure
                for v in item["violations"]:
                    if not isinstance(v, dict):
                        good_images_entries = False
                        break
                    if not all(k in v for k in ["package", "license", "rule"]):
                        good_images_entries = False
                        break
                    if v.get("rule") not in ("banned", "restricted_unmet"):
                        good_images_entries = False
                        break
                if not good_images_entries:
                    break
            if good_images_entries:
                scores["compliance_summary_present_and_well_formed"] = 1.0
                actual_images_list = actual_summary["images"]

    # Build actual mapping for quick lookup
    actual_by_image: Dict[str, dict] = {}
    if actual_images_list:
        for item in actual_images_list:
            img = item.get("image")
            if isinstance(img, str):
                if img not in actual_by_image:
                    actual_by_image[img] = item

    # json_images_coverage_exact
    if manifest_images and actual_images_list:
        manifest_set = set(manifest_images)
        actual_set = set(actual_by_image.keys())
        if actual_set == manifest_set and len(actual_images_list) == len(manifest_images):
            scores["json_images_coverage_exact"] = 1.0

    # json_totals_correct
    if actual_images_list and isinstance(actual_summary, dict):
        total_images = _safe_int(actual_summary.get("total_images"))
        total_pass = _safe_int(actual_summary.get("pass"))
        total_fail = _safe_int(actual_summary.get("fail"))
        if total_images is not None and total_pass is not None and total_fail is not None:
            if total_images == len(actual_images_list) and total_pass + total_fail == total_images:
                # If expected is available, ensure totals match expected
                if expected is not None:
                    if (expected["total_images"] == total_images and
                        expected["pass"] == total_pass and
                        expected["fail"] == total_fail):
                        scores["json_totals_correct"] = 1.0
                else:
                    # At least internal consistency
                    scores["json_totals_correct"] = 1.0 if scores["json_totals_correct"] == 0.0 else scores["json_totals_correct"]

    # json_statuses_correct, json_license_counts_correct, json_violations_correct, json_obligations_met_correct_for_passing
    if expected is not None and actual_images_list:
        status_ok = True
        lic_counts_ok = True
        violations_ok = True
        obligations_ok = True
        for img in manifest_images:
            exp = expected["images"][img]
            act = actual_by_image.get(img)
            if not act:
                status_ok = False
                lic_counts_ok = False
                violations_ok = False
                obligations_ok = False
                continue
            # status
            if exp["status"] != act.get("status"):
                status_ok = False
            # license counts
            exp_counts = exp["license_counts"]
            act_counts = act.get("license_counts", {})
            # Ensure act_counts values are ints
            def normalize_counts(d):
                out = {}
                if isinstance(d, dict):
                    for k, v in d.items():
                        iv = _safe_int(v)
                        if iv is None:
                            return None
                        out[str(k)] = iv
                    return out
                return None
            n_act_counts = normalize_counts(act_counts)
            if n_act_counts is None or n_act_counts != exp_counts:
                lic_counts_ok = False
            # violations compare as set of tuples (package, license, rule)
            def vset(lst):
                s = set()
                for v in lst:
                    if isinstance(v, dict) and "package" in v and "license" in v and "rule" in v:
                        s.add((v["package"], v["license"], v["rule"]))
                return s
            if vset(exp["violations"]) != vset(act.get("violations", [])):
                violations_ok = False
            # obligations for passing images
            if exp["status"] == "pass":
                exp_ob = set(exp["obligations_met"])
                act_ob_list = act.get("obligations_met", [])
                if not isinstance(act_ob_list, list):
                    obligations_ok = False
                else:
                    act_ob = set([str(x) for x in act_ob_list])
                    if exp_ob != act_ob:
                        obligations_ok = False
            else:
                # For failing images, obligations list must be empty
                act_ob_list = act.get("obligations_met", [])
                if isinstance(act_ob_list, list) and len(act_ob_list) == 0:
                    pass
                else:
                    obligations_ok = False
        if status_ok:
            scores["json_statuses_correct"] = 1.0
        if lic_counts_ok:
            scores["json_license_counts_correct"] = 1.0
        if violations_ok:
            scores["json_violations_correct"] = 1.0
        if obligations_ok:
            scores["json_obligations_met_correct_for_passing"] = 1.0

    # violations_csv_header_and_count_correct and matches json
    csv_exists = violations_csv_path.exists()
    csv_rows: List[Tuple[str, str, str, str]] = []
    if csv_exists and actual_images_list:
        try:
            with violations_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["image", "package", "license", "rule"]:
                    # collect
                    ok_rows = True
                    for r in rows[1:]:
                        if len(r) != 4:
                            ok_rows = False
                            break
                        csv_rows.append((r[0], r[1], r[2], r[3]))
                    if ok_rows:
                        # Count should equal total number of violations in json
                        total_violations = 0
                        for item in actual_images_list:
                            v = item.get("violations", [])
                            if isinstance(v, list):
                                total_violations += len(v)
                        if len(csv_rows) == total_violations:
                            scores["violations_csv_header_and_count_correct"] = 1.0
        except Exception:
            pass

        # Compare content with JSON
        if scores["violations_csv_header_and_count_correct"] == 1.0:
            json_viols_set = set()
            for item in actual_images_list:
                img = item.get("image")
                for v in item.get("violations", []):
                    if isinstance(v, dict) and all(k in v for k in ("package", "license", "rule")):
                        json_viols_set.add((img, v["package"], v["license"], v["rule"]))
            if set(csv_rows) == json_viols_set:
                scores["violations_csv_matches_json"] = 1.0

    # report_file_exists_and_non_empty
    if report_md_path.exists():
        content = _read_text(report_md_path) or ""
        if content.strip():
            scores["report_file_exists_and_non_empty"] = 1.0

    # status_summary_sentences_and_content
    if status_txt_path.exists():
        txt = _read_text(status_txt_path) or ""
        if txt.strip():
            # Count sentences (basic)
            parts = re.split(r'[.!?]+', txt)
            sentences = [p.strip() for p in parts if p.strip()]
            count_ok = 3 <= len(sentences) <= 6
            content_ok = False
            pass_fail_ok = bool(re.search(r'\bpass(ed)?\b', txt, flags=re.IGNORECASE)) and bool(re.search(r'\bfail(ed|ure)?\b', txt, flags=re.IGNORECASE))
            obligations_ok = True
            action_ok = True
            if expected is not None:
                any_obligations = any(len(v["obligations_met"]) > 0 and v["status"] == "pass" for v in expected["images"].values())
                if any_obligations:
                    obligations_ok = bool(re.search(r'\bobligat', txt, flags=re.IGNORECASE)) or bool(re.search(r'\bsource_offer\b', txt, flags=re.IGNORECASE)) or bool(re.search(r'\bnotice\b', txt, flags=re.IGNORECASE))
                if expected["fail"] > 0:
                    action_ok = bool(re.search(r'\b(recommend|action|should|fix|remedi|investigat)\b', txt, flags=re.IGNORECASE))
            content_ok = pass_fail_ok and obligations_ok and action_ok
            if count_ok and content_ok:
                scores["status_summary_sentences_and_content"] = 1.0

    # validation_log_contains_pass_line
    if validation_log_path.exists():
        log_text = _read_text(validation_log_path) or ""
        lines = [ln.strip() for ln in log_text.splitlines()]
        if any(ln == "VALIDATION PASSED" for ln in lines):
            scores["validation_log_contains_pass_line"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()