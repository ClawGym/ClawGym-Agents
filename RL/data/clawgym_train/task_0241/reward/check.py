import json
import csv;
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_yaml_minimal(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for a simple top-level mapping and simple lists.
    Handles:
      key: value
      key:
        - item1
        - item2
    Scalar values are parsed as int if digits, otherwise string stripped of quotes.
    """
    text = read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    result: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    base_indent_for_list: Optional[int] = None

    def parse_scalar(val: str) -> Any:
        v = val.strip()
        if v == "":
            return ""
        # Strip surrounding quotes if present
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        # Int
        if re.fullmatch(r"-?\d+", v):
            try:
                return int(v)
            except Exception:
                return v
        return v

    for raw in lines:
        line = raw.rstrip("\n")
        # Skip comments and empty lines
        if not line.strip() or line.strip().startswith("#"):
            continue
        # If currently parsing a list
        if current_list_key is not None:
            # Determine indent
            indent = len(line) - len(line.lstrip(" "))
            if line.lstrip().startswith("- "):
                # Still in list (allow equal or greater indent than initial)
                if base_indent_for_list is None or indent >= base_indent_for_list:
                    item = line.lstrip()[2:].strip()
                    result[current_list_key].append(parse_scalar(item))
                    # Keep parsing list
                    continue
            # List ended if not a list item or indent decreased
            current_list_key = None
            base_indent_for_list = None

        # Parse key: value or key:
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            remainder = parts[1]
            if remainder.strip() == "":
                # Start of list or nested map (we only handle list with '-')
                current_list_key = key
                result[current_list_key] = []
                base_indent_for_list = len(line) - len(line.lstrip(" "))
            else:
                result[key] = parse_scalar(remainder)
        else:
            # Unsupported syntax; be lenient by ignoring
            continue

        # If line started a list but next lines may not have dashes, we will end list when encountering a new key
    return result


def load_config_file(path: Path) -> Optional[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_json_safe(path)
    elif suffix in (".yaml", ".yml"):
        return parse_yaml_minimal(path)
    else:
        return None


def walk_config_files(root: Path) -> List[Path]:
    files: List[Path] = []
    if not root.exists():
        return files
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".json", ".yaml", ".yml"):
            files.append(p)
    return files


def semver_tuple(ver: str) -> Tuple[int, int, int]:
    # Extract numeric components; missing parts treated as 0
    parts = re.findall(r"\d+", ver)
    nums = [int(x) for x in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def compare_semver(a: str, b: str) -> int:
    ta = semver_tuple(a)
    tb = semver_tuple(b)
    return (ta > tb) - (ta < tb)


def compute_deviations_for_config(cfg: Dict[str, Any], schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    deviations: List[Dict[str, Any]] = []
    required = schema.get("required", [])
    allowed_values = schema.get("allowed_values", {})
    min_versions = schema.get("min_versions", {}).get("spatializer_plugin", {})
    allowed_features = schema.get("allowed_features", [])

    # Missing required keys: treat None or "" as missing
    for key in required:
        val = cfg.get(key, None)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            deviations.append({
                "issue": "missing_required_key",
                "key": key,
                "current_value": "" if val is None else str(val),
                "expected": "present",
                "severity": "error",
            })

    # Invalid allowed_values (if present)
    for key, allowed in allowed_values.items():
        if key in cfg:
            val = cfg.get(key)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                # Already covered by missing required key logic for required keys; if optional, treat as missing (no error)
                continue
            # Normalize types for comparison
            if isinstance(val, str) and val.isdigit():
                try:
                    val_cmp = int(val)
                except Exception:
                    val_cmp = val
            else:
                val_cmp = val
            # Allowed values might be strings (e.g., "gen2_standard") or ints
            if val_cmp not in allowed:
                deviations.append({
                    "issue": "invalid_value",
                    "key": key,
                    "current_value": str(val),
                    "expected": ", ".join(str(x) for x in allowed),
                    "severity": "error",
                })

    # Spatializer plugin min versions
    plugin = cfg.get("spatializer_plugin")
    version = cfg.get("spatializer_version")
    if plugin and version:
        min_ver = min_versions.get(str(plugin))
        if min_ver:
            try:
                if compare_semver(str(version), str(min_ver)) < 0:
                    deviations.append({
                        "issue": "version_below_min",
                        "key": "spatializer_version",
                        "current_value": str(version),
                        "expected": f">= {min_ver}",
                        "severity": "error",
                    })
            except Exception:
                # In case version parsing fails, count as error
                deviations.append({
                    "issue": "version_below_min",
                    "key": "spatializer_version",
                    "current_value": str(version),
                    "expected": f">= {min_ver}",
                    "severity": "error",
                })

    # Allowed features: warnings for unknown features
    feats = cfg.get("enabled_features")
    if isinstance(feats, list):
        for f in feats:
            if f not in allowed_features:
                deviations.append({
                    "issue": "unknown_feature",
                    "key": "enabled_features",
                    "current_value": str(f),
                    "expected": ", ".join(allowed_features),
                    "severity": "warning",
                })

    return deviations


def load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def extract_baseline_from_release_notes(text: str) -> Dict[str, Any]:
    # Extract baseline artifacts from known release notes structure
    baseline: Dict[str, Any] = {}
    # Sample rate: 48 kHz
    m_sr = re.search(r"Sample rate:\s*([\d\s]+)kHz", text, re.IGNORECASE)
    if m_sr:
        sr_khz = "".join(re.findall(r"\d+", m_sr.group(1)))
        try:
            baseline["sample_rate_hz"] = int(sr_khz) * 1000
        except Exception:
            baseline["sample_rate_hz"] = 48000
    else:
        baseline["sample_rate_hz"] = 48000

    # Bit depth: 24-bit
    m_bd = re.search(r"Bit depth:\s*([0-9]+)-?bit", text, re.IGNORECASE)
    if m_bd:
        baseline["bit_depth"] = int(m_bd.group(1))
    else:
        baseline["bit_depth"] = 24

    # HRTF profiles: gen2_standard (default), gen2_wide
    m_hrtf = re.search(r"HRTF profiles:\s*([^\n]+)", text, re.IGNORECASE)
    if m_hrtf:
        hrtf_line = m_hrtf.group(1)
        profs = [p.strip() for p in re.split(r",\s*", hrtf_line)]
        baseline["hrtf_profiles_line"] = hrtf_line
        baseline["hrtf_profiles"] = []
        baseline["hrtf_default"] = None
        for p in profs:
            p_clean = p.strip()
            baseline["hrtf_profiles"].append(p_clean.split()[0])
            if "(default)" in p_clean:
                baseline["hrtf_default"] = p_clean.split()[0]
    else:
        baseline["hrtf_profiles_line"] = "gen2_standard (default), gen2_wide"
        baseline["hrtf_profiles"] = ["gen2_standard", "gen2_wide"]
        baseline["hrtf_default"] = "gen2_standard"

    # Spatializer plugin: AuralX version 2.3.0 or newer
    m_plug = re.search(r"Spatializer plugin:\s*([A-Za-z0-9_]+)\s+version\s+([0-9.]+)", text, re.IGNORECASE)
    if m_plug:
        baseline["plugin_name"] = m_plug.group(1)
        baseline["plugin_min_version"] = m_plug.group(2)
    else:
        baseline["plugin_name"] = "AuralX"
        baseline["plugin_min_version"] = "2.3.0"

    # Default enabled features: dynamic_occlusion, head_tracking
    m_def_feat = re.search(r"Default enabled features:\s*([^\n]+)", text, re.IGNORECASE)
    baseline["default_features"] = []
    if m_def_feat:
        baseline["default_features"] = [x.strip() for x in m_def_feat.group(1).split(",")]
    # Optional features: room_sim
    m_opt_feat = re.search(r"Optional features:\s*([^\n]+)", text, re.IGNORECASE)
    baseline["optional_features"] = []
    if m_opt_feat:
        baseline["optional_features"] = [x.strip() for x in m_opt_feat.group(1).split(",")]
    # Supported latency modes: low, standard
    m_lat = re.search(r"Supported latency modes:\s*([^\n]+)", text, re.IGNORECASE)
    if m_lat:
        baseline["latency_modes"] = [x.strip() for x in m_lat.group(1).split(",")]
    else:
        baseline["latency_modes"] = ["low", "standard"]
    # Deprecation note with legacy_
    baseline["has_deprecation_legacy"] = ("legacy_" in text and re.search(r"Deprecation|deprecated", text, re.IGNORECASE) is not None)
    return baseline


def get_relative_under_configs(path: Path, configs_root: Path) -> str:
    try:
        rel = path.relative_to(configs_root)
        return str(rel).replace("\\", "/")
    except Exception:
        # return normalized from workspace root
        return str(path).replace("\\", "/")


def expected_recommendation_tokens_for_deviations(deviations: List[Dict[str, Any]]) -> List[List[str]]:
    """
    For each deviation, produce a list of tokens that should appear in recommendation bullet.
    Each recommendation is represented as a list of tokens which all should be present in the bullet line.
    """
    recs: List[List[str]] = []
    for d in deviations:
        key = d.get("key")
        issue = d.get("issue")
        severity = d.get("severity")
        if issue == "invalid_value" and key == "sample_rate":
            recs.append(["Set", "sample_rate", "48000"])
        elif issue == "invalid_value" and key == "bit_depth":
            recs.append(["Set", "bit_depth", "24"])
        elif issue == "missing_required_key" and key == "sample_rate":
            recs.append(["Set", "sample_rate", "48000"])
        elif issue == "missing_required_key" and key == "bit_depth":
            recs.append(["Set", "bit_depth", "24"])
        elif (issue == "invalid_value" or issue == "missing_required_key") and key == "hrtf_profile":
            recs.append(["Set", "hrtf_profile", "gen2_"])
        elif issue == "version_below_min":
            recs.append(["Bump", "AuralX", "2.3.0"])
        elif issue == "unknown_feature" and key == "enabled_features":
            recs.append(["Remove", "legacy_"])
        else:
            recs.append(["Fix", str(key)])
    return recs


def section_for_file(text: str, file_marker: str) -> str:
    """
    Extract a subsection of text associated with a file. We search for the first occurrence of file_marker
    and return the following lines up to the next occurrence of another file path under input/configs or end.
    """
    idx = text.find(file_marker)
    if idx == -1:
        return ""
    tail = text[idx:]
    # Stop at next occurrence of 'input/configs/' for another file path, excluding the first char
    m = re.search(r"\n.*input/configs/.*", tail[1:], re.IGNORECASE)
    if m:
        end_idx = m.start() + 1  # since we started at offset 1
        return tail[:end_idx]
    return tail


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "audit_csv_exists_and_header": 0.0,
        "audit_csv_deviation_rows_correct_count": 0.0,
        "audit_csv_contains_expected_rows": 0.0,
        "audit_csv_file_paths_relative": 0.0,
        "compliance_summary_baseline_section_covers_requirements": 0.0,
        "compliance_summary_per_file_sections_present": 0.0,
        "compliance_summary_counts_and_flags_correct": 0.0,
        "compliance_summary_recommendations_present": 0.0,
        "changelog_has_configuration_updates_section": 0.0,
        "changelog_groups_by_file_and_references_changes": 0.0,
    }

    # Load schema
    schema_path = workspace / "input" / "spec" / "audio_config_schema.json"
    schema = load_json_safe(schema_path)

    # Load release notes
    rn_path = workspace / "input" / "docs" / "release_notes.md"
    rn_text = read_text_safe(rn_path)
    baseline = extract_baseline_from_release_notes(rn_text or "")

    # Discover config files
    configs_root = workspace / "input" / "configs"
    config_files = walk_config_files(configs_root)

    # Compute expected deviations per file
    expected_deviations: Dict[str, List[Dict[str, Any]]] = {}
    if schema and config_files:
        for cf in config_files:
            cfg = load_config_file(cf)
            if isinstance(cfg, dict):
                devs = compute_deviations_for_config(cfg, schema)
                rel = get_relative_under_configs(cf, configs_root)
                expected_deviations[rel] = devs

    # Expected total deviation count
    expected_total = sum(len(v) for v in expected_deviations.values())

    # Paths to deliverables
    audit_csv_path = workspace / "output" / "audit" / "config_audit.csv"
    compliance_md_path = workspace / "output" / "reports" / "compliance_summary.md"
    changelog_md_path = workspace / "output" / "reports" / "CHANGELOG_draft.md"

    # Check audit CSV
    csv_rows = load_csv_rows(audit_csv_path)
    if csv_rows is not None:
        # Check headers
        fieldnames = None
        try:
            with audit_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                fieldnames = next(reader)
        except Exception:
            fieldnames = None
        required_cols = ["file_path", "issue", "key", "current_value", "expected", "severity"]
        if fieldnames and all(col in fieldnames for col in required_cols):
            scores["audit_csv_exists_and_header"] = 1.0

        # Check row count equals expected deviations (only if we could compute expectations)
        if expected_total > 0:
            if isinstance(csv_rows, list) and len(csv_rows) == expected_total:
                scores["audit_csv_deviation_rows_correct_count"] = 1.0
        else:
            scores["audit_csv_deviation_rows_correct_count"] = 0.0

        # Check file paths relative and presence of expected rows
        if expected_deviations and isinstance(csv_rows, list):
            # Normalize CSV rows
            by_file: Dict[str, List[Dict[str, str]]] = {}
            for r in csv_rows:
                fp = (r.get("file_path") or "").replace("\\", "/")
                for rel in expected_deviations.keys():
                    if fp.endswith(rel) or fp.endswith("input/configs/" + rel) or fp == rel or fp == ("input/configs/" + rel):
                        by_file.setdefault(rel, []).append(r)
                        break
            # Check path relativity
            all_paths_relative = True
            for r in csv_rows:
                fp = (r.get("file_path") or "").replace("\\", "/")
                if "/input/configs/" in fp:
                    tail_match = any(fp.endswith(rel) for rel in expected_deviations.keys()) or any(
                        fp.endswith("input/configs/" + rel) for rel in expected_deviations.keys()
                    )
                    if not tail_match:
                        all_paths_relative = False
                        break
                else:
                    if not any(fp.endswith(rel) for rel in expected_deviations.keys()):
                        all_paths_relative = False
                        break
            if all_paths_relative:
                scores["audit_csv_file_paths_relative"] = 1.0

            # Check presence of expected deviations rows semantically
            def row_matches_deviation(row: Dict[str, str], dev: Dict[str, Any]) -> bool:
                if (row.get("key") or "").strip() != str(dev.get("key")):
                    return False
                if (row.get("severity") or "").strip().lower() != str(dev.get("severity")):
                    return False
                if dev.get("issue") == "unknown_feature":
                    if (row.get("current_value") or "").strip() != str(dev.get("current_value")):
                        return False
                if dev.get("issue") == "invalid_value":
                    cv = (row.get("current_value") or "").strip()
                    if dev.get("key") == "sample_rate":
                        if cv and cv not in ("44100", "48000"):
                            return False
                    if dev.get("key") == "bit_depth":
                        if cv and cv not in ("16", "24"):
                            return False
                if dev.get("issue") == "version_below_min":
                    cv = (row.get("current_value") or "").strip()
                    if cv and cv not in ("2.2.1", "2.1.9", "2.3.0"):
                        return False
                return True

            all_expected_found = True
            for rel, devs in expected_deviations.items():
                rows_for_file = by_file.get(rel, [])
                for d in devs:
                    matched = False
                    for r in rows_for_file:
                        fp = (r.get("file_path") or "").replace("\\", "/")
                        if not (fp.endswith(rel) or fp.endswith("input/configs/" + rel) or fp == rel or fp == ("input/configs/" + rel)):
                            continue
                        if row_matches_deviation(r, d):
                            matched = True
                            break
                    if not matched:
                        all_expected_found = False
                        break
                if not all_expected_found:
                    break
            if all_expected_found:
                scores["audit_csv_contains_expected_rows"] = 1.0

    # Check compliance summary
    comp_text = read_text_safe(compliance_md_path) or ""
    baseline_tokens_ok = True
    if comp_text:
        sr_ok = (re.search(r"48\s*kHz", comp_text, re.IGNORECASE) is not None) or ("48000" in comp_text)
        bd_ok = (re.search(r"24\s*[- ]?bit", comp_text, re.IGNORECASE) is not None)
        hrtf_ok = ("gen2_standard" in comp_text and "gen2_wide" in comp_text and re.search(r"default", comp_text, re.IGNORECASE) is not None)
        plugin_ok = ("AuralX" in comp_text and "2.3.0" in comp_text)
        def_feats_ok = ("dynamic_occlusion" in comp_text and "head_tracking" in comp_text)
        opt_feats_ok = ("room_sim" in comp_text and re.search(r"optional", comp_text, re.IGNORECASE) is not None)
        latency_ok = (re.search(r"latency", comp_text, re.IGNORECASE) is not None and re.search(r"\blow\b", comp_text, re.IGNORECASE) is not None and re.search(r"\bstandard\b", comp_text, re.IGNORECASE) is not None)
        deprec_ok = ("legacy_" in comp_text and re.search(r"deprecation|deprecated", comp_text, re.IGNORECASE) is not None)
        baseline_tokens_ok = all([sr_ok, bd_ok, hrtf_ok, plugin_ok, def_feats_ok, opt_feats_ok, latency_ok, deprec_ok])
    else:
        baseline_tokens_ok = False
    scores["compliance_summary_baseline_section_covers_requirements"] = 1.0 if baseline_tokens_ok else 0.0

    # Per-file sections present
    per_file_present = True
    if expected_deviations:
        for rel in expected_deviations.keys():
            if rel not in comp_text and ("input/configs/" + rel) not in comp_text:
                per_file_present = False
                break
    else:
        per_file_present = False
    scores["compliance_summary_per_file_sections_present"] = 1.0 if per_file_present else 0.0

    # Counts and compliant flag correctness
    counts_ok = True
    recs_ok = True
    if expected_deviations and comp_text:
        for rel, devs in expected_deviations.items():
            file_marker = rel
            if file_marker not in comp_text and ("input/configs/" + file_marker) in comp_text:
                file_marker = "input/configs/" + file_marker
            section = section_for_file(comp_text, file_marker)
            if not section:
                counts_ok = False
                recs_ok = False
                break
            error_count = sum(1 for d in devs if d.get("severity") == "error")
            m_comp = re.search(r"compliant\s*:\s*(true|false)", section, re.IGNORECASE)
            if not m_comp:
                counts_ok = False
            else:
                is_true = m_comp.group(1).lower() == "true"
                if is_true != (error_count == 0):
                    counts_ok = False
            m_err = re.search(r"errors?\s*:\s*(\d+)", section, re.IGNORECASE)
            m_warn = re.search(r"warnings?\s*:\s*(\d+)", section, re.IGNORECASE)
            if not m_err or not m_warn:
                counts_ok = False
            else:
                try:
                    ce = int(m_err.group(1))
                    cw = int(m_warn.group(1))
                except Exception:
                    ce = -1
                    cw = -1
                expected_warnings = sum(1 for d in devs if d.get("severity") == "warning")
                if ce != error_count or cw != expected_warnings:
                    counts_ok = False

            expected_rec_tokens = expected_recommendation_tokens_for_deviations(devs)
            bullets = []
            for line in section.splitlines():
                if re.match(r"\s*[-*]\s+", line):
                    bullets.append(line.strip())
            for tokens in expected_rec_tokens:
                found_line = False
                for b in bullets:
                    all_present = True
                    for t in tokens:
                        if t == "gen2_":
                            if ("gen2_standard" not in b) and ("gen2_wide" not in b):
                                all_present = False
                                break
                        else:
                            if re.search(re.escape(t), b, re.IGNORECASE) is None:
                                all_present = False
                                break
                    if all_present:
                        found_line = True
                        break
                if not found_line:
                    recs_ok = False
                    break
    else:
        counts_ok = False
        recs_ok = False
    scores["compliance_summary_counts_and_flags_correct"] = 1.0 if counts_ok else 0.0
    scores["compliance_summary_recommendations_present"] = 1.0 if recs_ok else 0.0

    # Changelog checks
    chg_text = read_text_safe(changelog_md_path) or ""
    if chg_text and re.search(r"Configuration Updates", chg_text, re.IGNORECASE):
        scores["changelog_has_configuration_updates_section"] = 1.0

    chg_group_ok = True
    if expected_deviations and chg_text:
        for rel, devs in expected_deviations.items():
            if rel not in chg_text and ("input/configs/" + rel) not in chg_text:
                chg_group_ok = False
                break
            expected_rec_tokens = expected_recommendation_tokens_for_deviations(devs)
            for tokens in expected_rec_tokens:
                pattern_parts = []
                for t in tokens:
                    if t == "gen2_":
                        pattern_parts.append(r"(gen2_standard|gen2_wide)")
                    else:
                        pattern_parts.append(re.escape(t))
                pattern = r".*".join(pattern_parts)
                if re.search(pattern, chg_text, re.IGNORECASE | re.DOTALL) is None:
                    chg_group_ok = False
                    break
            if not chg_group_ok:
                break
    else:
        chg_group_ok = False
    scores["changelog_groups_by_file_and_references_changes"] = 1.0 if chg_group_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()