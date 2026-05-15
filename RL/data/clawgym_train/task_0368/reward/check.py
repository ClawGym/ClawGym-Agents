import json
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from typing import Any, Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
        return data, None
    except Exception as e:
        return None, f"read_error:{e}"


def _read_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, f"json_error:{e}"


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    try:
        # try fromisoformat; support trailing Z
        try_str = s
        if try_str.endswith("Z"):
            try_str = try_str[:-1]
        datetime.fromisoformat(try_str)
        return True
    except Exception:
        return False


def _parse_bracket_list(val: str) -> List[str]:
    inner = val.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    if not inner.strip():
        return []
    parts = [p.strip() for p in inner.split(",")]
    out = []
    for p in parts:
        if p.startswith('"') and p.endswith('"'):
            out.append(p[1:-1])
        elif p.startswith("'") and p.endswith("'"):
            out.append(p[1:-1])
        else:
            out.append(p)
    return out


def _parse_int_list(val: str) -> List[int]:
    items = []
    for tok in _parse_bracket_list(val):
        tok = tok.strip()
        try:
            items.append(int(tok))
        except Exception:
            # try remove trailing commas/spaces
            tok2 = tok.strip(", ")
            try:
                items.append(int(tok2))
            except Exception:
                pass
    return items


def _parse_config_minimal(text: str) -> Dict[str, Any]:
    # Very minimal parser tailored to the provided config.yaml structure
    cfg: Dict[str, Any] = {"plan": {}, "paths": {}, "constraints": []}
    section = None
    lines = text.splitlines()
    i = 0
    in_constraints = False
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if stripped.startswith("project_name:"):
            val = stripped.split(":", 1)[1].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            cfg["project_name"] = val
        elif stripped.startswith("plan:"):
            section = "plan"
            in_constraints = False
        elif stripped.startswith("paths:"):
            section = "paths"
            in_constraints = False
        elif stripped.startswith("internet_sources:"):
            section = "internet_sources"
            cfg["internet_sources"] = {}
            in_constraints = False
        elif stripped.startswith("constraints:"):
            section = "constraints"
            in_constraints = True
            cfg["constraints"] = []
        else:
            if section == "plan":
                # Keys under plan
                if "days:" in stripped and stripped.startswith("days:") or stripped.startswith("days:"):
                    m = re.search(r"days:\s*(\d+)", stripped)
                    if m:
                        cfg["plan"]["days"] = int(m.group(1))
                elif stripped.startswith("active_days:"):
                    m = re.search(r"active_days:\s*(\d+)", stripped)
                    if m:
                        cfg["plan"]["active_days"] = int(m.group(1))
                elif stripped.startswith("session_length_minutes:"):
                    m = re.search(r"session_length_minutes:\s*(\d+)", stripped)
                    if m:
                        cfg["plan"]["session_length_minutes"] = int(m.group(1))
                elif stripped.startswith("yoga_to_strength_ratio:"):
                    m = re.search(r"yoga_to_strength_ratio:\s*(\[.*\])", stripped)
                    if m:
                        cfg["plan"]["yoga_to_strength_ratio"] = _parse_int_list(m.group(1))
                elif stripped.startswith("yoga_style_preferences:"):
                    m = re.search(r"yoga_style_preferences:\s*(\[.*\])", stripped)
                    if m:
                        cfg["plan"]["yoga_style_preferences"] = _parse_bracket_list(m.group(1))
                elif stripped.startswith("ability_level:"):
                    val = stripped.split(":", 1)[1].strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    cfg["plan"]["ability_level"] = val
            elif section == "paths":
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    cfg["paths"][k] = v
            elif section == "internet_sources":
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    cfg["internet_sources"][k] = v
            elif section == "constraints" or in_constraints:
                if stripped.startswith("-"):
                    # bullet line
                    item = stripped[1:].strip()
                    if item.startswith('"') and item.endswith('"'):
                        item = item[1:-1]
                    cfg["constraints"].append(item)
                else:
                    in_constraints = False
        i += 1
    return cfg


def _load_config(workspace: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cfg_path = workspace / "input" / "config.yaml"
    if not cfg_path.exists():
        return None, "missing_config"
    text, err = _read_text_safe(cfg_path)
    if err or text is None:
        return None, err or "read_error"
    try:
        cfg = _parse_config_minimal(text)
        return cfg, None
    except Exception as e:
        return None, f"parse_error:{e}"


def _validate_sources_manifest(workspace: Path, cfg: Dict[str, Any]) -> Tuple[float, float, float]:
    """
    Returns tuple of three scores:
    - sources_manifest_exists_and_structure
    - downloads_saved_and_hashes_match_manifest
    - sources_url_tld_requirements
    """
    manifest_path = workspace / cfg["paths"].get("outputs_dir", "outputs") / "sources.json"
    downloads_dir = workspace / cfg["paths"].get("downloads_dir", "downloads")
    s_struct = 0.0
    s_hash = 0.0
    s_tld = 0.0
    if not manifest_path.exists():
        return s_struct, s_hash, s_tld
    manifest, err = _read_json_safe(manifest_path)
    if err or not isinstance(manifest, dict):
        return s_struct, s_hash, s_tld

    # Basic structure
    ok_struct = True
    if "search_queries" not in manifest or not isinstance(manifest["search_queries"], dict):
        ok_struct = False
    if "sources" not in manifest or not isinstance(manifest["sources"], list):
        ok_struct = False
    else:
        if len(manifest["sources"]) != 2:
            ok_struct = False
        else:
            for src in manifest["sources"]:
                if not isinstance(src, dict):
                    ok_struct = False
                    break
                for req in ("type", "url", "saved_path", "sha256", "retrieved_at"):
                    if req not in src:
                        ok_struct = False
                        break
                if not ok_struct:
                    break
    if ok_struct:
        s_struct = 1.0

    # Hashes and paths validity
    ok_hash = True
    ok_tld = True
    type_seen = set()
    expected_paths = {
        "strength": str(Path(cfg["paths"].get("downloads_dir", "downloads")) / "strength_source_1.html"),
        "yoga": str(Path(cfg["paths"].get("downloads_dir", "downloads")) / "yoga_source_1.html"),
    }
    if isinstance(manifest.get("sources"), list):
        for src in manifest["sources"]:
            if not isinstance(src, dict):
                ok_hash = False
                ok_tld = False
                break
            typ = src.get("type")
            type_seen.add(typ)
            saved_path = src.get("saved_path")
            sha = src.get("sha256")
            retrieved_at = src.get("retrieved_at")
            url = src.get("url", "")

            # Check saved_path matches expected
            exp = expected_paths.get(typ)
            if exp is None or saved_path != exp:
                ok_hash = False

            # Check file exists and hash matches
            file_path = workspace / saved_path if isinstance(saved_path, str) else None
            if not file_path or not file_path.exists():
                ok_hash = False
            else:
                file_sha = _sha256_file(file_path)
                if not file_sha or file_sha != sha:
                    ok_hash = False

            # Check retrieved_at iso
            if not isinstance(retrieved_at, str) or not _is_iso8601(retrieved_at):
                ok_hash = False

            # TLD checks
            try:
                parsed = urlparse(url)
                host = parsed.netloc.lower()
            except Exception:
                host = ""
            if typ == "strength":
                if not (host.endswith(".gov") or host.endswith(".edu")):
                    ok_tld = False
            elif typ == "yoga":
                if not host.endswith(".org"):
                    ok_tld = False
            else:
                ok_tld = False

    # Ensure both types present
    if type_seen != {"strength", "yoga"}:
        ok_tld = False

    s_hash = 1.0 if ok_hash else 0.0
    s_tld = 1.0 if ok_tld else 0.0
    return s_struct, s_hash, s_tld


def _load_dataset(path: Path, expected_fields: List[str]) -> Tuple[Optional[List[Dict[str, Any]]], float]:
    data, err = _read_json_safe(path)
    if err or not isinstance(data, list):
        return None, 0.0
    for item in data:
        if not isinstance(item, dict):
            return None, 0.0
        for f in expected_fields:
            if f not in item:
                return None, 0.0
    return data, 1.0


def _validate_strength_data(workspace: Path, cfg: Dict[str, Any]) -> float:
    path = workspace / cfg["paths"].get("data_dir", "data") / "strength_movements.json"
    data, s = _load_dataset(path, ["source_url", "movement_category", "exercise_name"])
    if s == 0.0 or data is None:
        return 0.0
    # Ensure >= 8 entries and >= 3 distinct movement_category values
    if len(data) < 8:
        return 0.0
    cats = set([str(d.get("movement_category")) for d in data])
    if len(cats) < 3:
        return 0.0
    # Basic type integrity
    for d in data:
        if not isinstance(d.get("exercise_name"), str) or not isinstance(d.get("movement_category"), (str,)):
            return 0.0
        if not isinstance(d.get("source_url"), str):
            return 0.0
    return 1.0


def _validate_yoga_data(workspace: Path, cfg: Dict[str, Any]) -> float:
    path = workspace / cfg["paths"].get("data_dir", "data") / "yoga_poses.json"
    data, s = _load_dataset(path, ["source_url", "name", "category", "difficulty"])
    if s == 0.0 or data is None:
        return 0.0
    if len(data) < 12:
        return 0.0
    cats = set([str(d.get("category")) for d in data])
    diffs = set([str(d.get("difficulty")) for d in data])
    if len(cats) < 3 or len(diffs) < 2:
        return 0.0
    # Field types
    for d in data:
        if not isinstance(d.get("name"), str):
            return 0.0
        if not isinstance(d.get("category"), str) or not isinstance(d.get("difficulty"), str):
            return 0.0
        if not isinstance(d.get("source_url"), str):
            return 0.0
    return 1.0


def _validate_plan_structure_and_days(workspace: Path, cfg: Dict[str, Any]) -> Tuple[float, Optional[Dict[str, Any]]]:
    plan_path = workspace / cfg["paths"].get("outputs_dir", "outputs") / "weekly_plan.json"
    plan, err = _read_json_safe(plan_path)
    if err or not isinstance(plan, dict):
        return 0.0, None
    # Keys "1".."7"
    expected_days = [str(i) for i in range(1, 1 + int(cfg["plan"].get("days", 7)))]
    if set(plan.keys()) != set(expected_days):
        return 0.0, None
    # Each day must be list
    for k in expected_days:
        if not isinstance(plan.get(k), list):
            return 0.0, None
        # each segment basic structure
        for seg in plan[k]:
            if not isinstance(seg, dict):
                return 0.0, None
            if "type" not in seg or "duration_minutes" not in seg or "details" not in seg:
                return 0.0, None
            if seg["type"] not in ("yoga", "strength", "rest"):
                return 0.0, None
            if not isinstance(seg["duration_minutes"], int) or seg["duration_minutes"] < 0:
                return 0.0, None
            if not isinstance(seg["details"], dict):
                return 0.0, None
    # Rest days must have a single rest segment duration 0; Active days at least one yoga and one strength
    active_days = 0
    for k in expected_days:
        segs = plan[k]
        if len(segs) == 1 and segs[0].get("type") == "rest":
            if segs[0].get("duration_minutes") != 0:
                return 0.0, None
        else:
            types = {s.get("type") for s in segs}
            if not ("yoga" in types and "strength" in types):
                return 0.0, None
            active_days += 1
    if active_days != int(cfg["plan"].get("active_days", 4)):
        return 0.0, None
    return 1.0, plan


def _validate_segments_reference_names(workspace: Path, cfg: Dict[str, Any], plan: Dict[str, Any]) -> float:
    data_dir = workspace / cfg["paths"].get("data_dir", "data")
    yoga_path = data_dir / "yoga_poses.json"
    strength_path = data_dir / "strength_movements.json"
    yoga_data, e1 = _read_json_safe(yoga_path)
    strength_data, e2 = _read_json_safe(strength_path)
    if e1 or e2 or not isinstance(yoga_data, list) or not isinstance(strength_data, list):
        return 0.0
    yoga_names_to_cat = {}
    for y in yoga_data:
        if isinstance(y, dict) and isinstance(y.get("name"), str) and isinstance(y.get("category"), str):
            yoga_names_to_cat[y["name"]] = y["category"]
    strength_names_to_cat = {}
    for s in strength_data:
        if isinstance(s, dict) and isinstance(s.get("exercise_name"), str) and isinstance(s.get("movement_category"), str):
            strength_names_to_cat[s["exercise_name"]] = s["movement_category"]

    for day, segs in plan.items():
        # segs is list
        for seg in segs:
            if seg["type"] == "yoga":
                details = seg.get("details", {})
                pose_names = details.get("pose_names")
                styles = details.get("styles")
                if not isinstance(pose_names, list) or len(pose_names) < 2:
                    return 0.0
                for p in pose_names:
                    if p not in yoga_names_to_cat:
                        return 0.0
                if not isinstance(styles, list):
                    return 0.0
                # styles subset of preferences
                prefs = cfg["plan"].get("yoga_style_preferences", [])
                for st in styles:
                    if st not in prefs:
                        return 0.0
            elif seg["type"] == "strength":
                details = seg.get("details", {})
                movement_category = details.get("movement_category")
                exercise_names = details.get("exercise_names")
                if not isinstance(movement_category, str):
                    return 0.0
                if not isinstance(exercise_names, list) or len(exercise_names) < 2:
                    return 0.0
                for ex in exercise_names:
                    if ex not in strength_names_to_cat:
                        return 0.0
                    # ensure category matches
                    if strength_names_to_cat[ex] != movement_category:
                        return 0.0
            elif seg["type"] == "rest":
                # already checked in structure
                pass
    return 1.0


def _validate_durations_and_ratio(workspace: Path, cfg: Dict[str, Any], plan: Dict[str, Any]) -> float:
    session_len = int(cfg["plan"].get("session_length_minutes", 45))
    ratio = cfg["plan"].get("yoga_to_strength_ratio", [60, 40])
    if not isinstance(ratio, list) or len(ratio) != 2 or sum(ratio) == 0:
        return 0.0
    yoga_pct, strength_pct = ratio[0], ratio[1]
    # Expected durations per day
    exp_yoga = round(session_len * yoga_pct / (yoga_pct + strength_pct))
    exp_strength = session_len - exp_yoga
    tol = 2
    ok = True
    active_days = 0
    for k in sorted(plan.keys(), key=lambda x: int(x)):
        segs = plan[k]
        if len(segs) == 1 and segs[0]["type"] == "rest":
            continue
        active_days += 1
        total = sum([s["duration_minutes"] for s in segs if isinstance(s.get("duration_minutes"), int)])
        if total != session_len:
            ok = False
            break
        yoga_minutes = sum([s["duration_minutes"] for s in segs if s["type"] == "yoga"])
        strength_minutes = sum([s["duration_minutes"] for s in segs if s["type"] == "strength"])
        if abs(yoga_minutes - exp_yoga) > tol or abs(strength_minutes - exp_strength) > tol:
            ok = False
            break
    return 1.0 if ok and active_days == int(cfg["plan"].get("active_days", 4)) else 0.0


def _validate_no_consecutive_yoga_category(workspace: Path, cfg: Dict[str, Any], plan: Dict[str, Any]) -> float:
    # Build mapping pose_name -> category
    data_dir = workspace / cfg["paths"].get("data_dir", "data")
    yoga_path = data_dir / "yoga_poses.json"
    yoga_data, e1 = _read_json_safe(yoga_path)
    if e1 or not isinstance(yoga_data, list):
        return 0.0
    name_to_cat = {}
    for y in yoga_data:
        if isinstance(y, dict):
            name = y.get("name")
            cat = y.get("category")
            if isinstance(name, str) and isinstance(cat, str):
                name_to_cat[name] = cat
    # For each active day, determine dominant yoga category
    prev_mode: Optional[str] = None
    for day in sorted(plan.keys(), key=lambda x: int(x)):
        segs = plan[day]
        if len(segs) == 1 and segs[0]["type"] == "rest":
            continue
        # gather yoga categories
        counts: Dict[str, int] = {}
        for s in segs:
            if s["type"] == "yoga":
                for p in s.get("details", {}).get("pose_names", []):
                    cat = name_to_cat.get(p)
                    if cat is not None:
                        counts[cat] = counts.get(cat, 0) + 1
        if not counts:
            # no yoga poses or not mappable; fail
            return 0.0
        # mode
        mode_cat = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if prev_mode is not None and mode_cat == prev_mode:
            return 0.0
        prev_mode = mode_cat
    return 1.0


def _validate_yoga_styles_variety(workspace: Path, cfg: Dict[str, Any], plan: Dict[str, Any]) -> float:
    styles_set = set()
    prefs = set(cfg["plan"].get("yoga_style_preferences", []))
    for day, segs in plan.items():
        for s in segs:
            if s["type"] == "yoga":
                styles = s.get("details", {}).get("styles", [])
                if isinstance(styles, list):
                    for st in styles:
                        if st in prefs:
                            styles_set.add(st)
                        else:
                            # styles must be subset of prefs; fail if any outside
                            return 0.0
    return 1.0 if len(styles_set) >= 2 else 0.0


def _validate_strength_patterns_coverage(workspace: Path, cfg: Dict[str, Any], plan: Dict[str, Any]) -> float:
    # Collect movement categories used across active days for strength segments
    patterns = set()
    for day, segs in plan.items():
        for s in segs:
            if s["type"] == "strength":
                mc = s.get("details", {}).get("movement_category")
                if isinstance(mc, str):
                    patterns.add(mc.lower())
    # Compare against canonical set
    canonical = {"push", "pull", "squat", "hinge", "core"}
    covered = patterns & canonical
    return 1.0 if len(covered) >= 4 else 0.0


def _validate_compliance_report(workspace: Path, cfg: Dict[str, Any], plan: Dict[str, Any]) -> float:
    report_path = workspace / cfg["paths"].get("outputs_dir", "outputs") / "compliance_report.json"
    report, err = _read_json_safe(report_path)
    if err or not isinstance(report, dict):
        return 0.0

    # Compute expected totals from plan
    total_minutes = 0
    yoga_minutes = 0
    strength_minutes = 0
    yoga_styles_used = set()
    strength_patterns = set()
    prefs = set(cfg["plan"].get("yoga_style_preferences", []))
    active_days = 0
    non_rest_segments = 0
    for day in plan:
        segs = plan[day]
        day_has_activity = False
        for s in segs:
            typ = s.get("type")
            dur = s.get("duration_minutes", 0)
            if not isinstance(dur, int):
                return 0.0
            if typ != "rest":
                day_has_activity = True
                non_rest_segments += 1
            total_minutes += dur
            if typ == "yoga":
                yoga_minutes += dur
                styles = s.get("details", {}).get("styles", [])
                if isinstance(styles, list):
                    for st in styles:
                        if st in prefs:
                            yoga_styles_used.add(st)
                        else:
                            # using styles outside prefs
                            return 0.0
            elif typ == "strength":
                strength_minutes += dur
                mc = s.get("details", {}).get("movement_category")
                if isinstance(mc, str):
                    strength_patterns.add(mc.lower())
        if day_has_activity:
            active_days += 1

    # Constraints
    ratio = cfg["plan"].get("yoga_to_strength_ratio", [60, 40])
    session_len = int(cfg["plan"].get("session_length_minutes", 45))
    exp_yoga = round(session_len * ratio[0] / (ratio[0] + ratio[1])) if isinstance(ratio, list) and len(ratio) == 2 else None
    exp_strength = session_len - exp_yoga if exp_yoga is not None else None
    tol = 2
    violations = []
    # Check 7 days and active days
    if len(plan.keys()) != int(cfg["plan"].get("days", 7)) or active_days != int(cfg["plan"].get("active_days", 4)):
        violations.append("Invalid days/active_days count")
    # Check per-day durations and ratio as separate util
    dur_ratio_ok = _validate_durations_and_ratio(workspace, cfg, plan) == 1.0
    if not dur_ratio_ok:
        violations.append("Per-day durations or ratio not within tolerance")
    # Yoga styles distinct
    if len(yoga_styles_used) < 2:
        violations.append("Insufficient yoga styles")
    # Strength patterns coverage
    canonical = {"push", "pull", "squat", "hinge", "core"}
    if len(strength_patterns & canonical) < 4:
        violations.append("Insufficient strength patterns coverage")
    constraints_met_expected = len(violations) == 0

    # Validate report fields
    if not isinstance(report.get("total_sessions"), int):
        return 0.0
    if not isinstance(report.get("total_minutes"), int):
        return 0.0
    if not isinstance(report.get("yoga_minutes"), int):
        return 0.0
    if not isinstance(report.get("strength_minutes"), int):
        return 0.0
    if not isinstance(report.get("yoga_styles_used"), list):
        return 0.0
    if not isinstance(report.get("strength_patterns_covered"), list):
        return 0.0
    if not isinstance(report.get("constraints_met"), bool):
        return 0.0
    if not isinstance(report.get("violations"), list):
        return 0.0

    # Check minutes match
    if report["total_minutes"] != total_minutes:
        return 0.0
    if report["yoga_minutes"] != yoga_minutes:
        return 0.0
    if report["strength_minutes"] != strength_minutes:
        return 0.0

    # Check styles used equals computed set (order-insensitive)
    if set(report["yoga_styles_used"]) != set(yoga_styles_used):
        return 0.0

    # Check strength patterns covered equals at least canonical intersection; allow extra but ensure includes our computed intersection
    rep_patterns = set([p.lower() for p in report["strength_patterns_covered"] if isinstance(p, str)])
    if (strength_patterns & canonical) - rep_patterns:
        return 0.0

    # Check constraints_met and violations consistency
    # Accept total_sessions either equals number of active days or count of non-rest segments
    total_sessions_ok = report["total_sessions"] in (active_days, non_rest_segments)
    if not total_sessions_ok:
        return 0.0
    if report["constraints_met"] != constraints_met_expected:
        return 0.0
    # If constraints_met is True, violations should be empty; if False, non-empty
    if report["constraints_met"] and len(report["violations"]) != 0:
        return 0.0
    if (not report["constraints_met"]) and len(report["violations"]) == 0:
        return 0.0

    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "sources_manifest_exists_and_structure": 0.0,
        "downloads_saved_and_hashes_match_manifest": 0.0,
        "sources_url_tld_requirements": 0.0,
        "strength_data_structure_and_counts": 0.0,
        "yoga_data_structure_and_counts": 0.0,
        "plan_days_and_segments_structure": 0.0,
        "segments_reference_names_valid": 0.0,
        "per_day_duration_and_ratio": 0.0,
        "no_consecutive_yoga_category": 0.0,
        "styles_subset_and_variety": 0.0,
        "strength_patterns_coverage": 0.0,
        "report_structure_and_consistency": 0.0,
    }

    # Load config
    cfg, cfg_err = _load_config(workspace)
    if cfg is None:
        # Without config, we cannot meaningfully validate; return zeros
        return scores

    # Sources manifest and downloads validation
    s_struct, s_hash, s_tld = _validate_sources_manifest(workspace, cfg)
    scores["sources_manifest_exists_and_structure"] = s_struct
    scores["downloads_saved_and_hashes_match_manifest"] = s_hash
    scores["sources_url_tld_requirements"] = s_tld

    # Datasets validation
    scores["strength_data_structure_and_counts"] = _validate_strength_data(workspace, cfg)
    scores["yoga_data_structure_and_counts"] = _validate_yoga_data(workspace, cfg)

    # Plan structure
    s_plan, plan = _validate_plan_structure_and_days(workspace, cfg)
    scores["plan_days_and_segments_structure"] = s_plan

    # Only proceed with deeper checks if basic plan structure present
    if s_plan == 1.0 and isinstance(plan, dict):
        scores["segments_reference_names_valid"] = _validate_segments_reference_names(workspace, cfg, plan)
        scores["per_day_duration_and_ratio"] = _validate_durations_and_ratio(workspace, cfg, plan)
        scores["no_consecutive_yoga_category"] = _validate_no_consecutive_yoga_category(workspace, cfg, plan)
        scores["styles_subset_and_variety"] = _validate_yoga_styles_variety(workspace, cfg, plan)
        scores["strength_patterns_coverage"] = _validate_strength_patterns_coverage(workspace, cfg, plan)
        scores["report_structure_and_consistency"] = _validate_compliance_report(workspace, cfg, plan)

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()