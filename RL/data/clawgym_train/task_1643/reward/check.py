import json
import sys
import csv
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_number(s: str) -> Optional[float]:
    try:
        if s.strip().lower() in ("true", "false", "null", "~", "nan", "inf", "+inf", "-inf"):
            return None
        return float(s)
    except Exception:
        return None


def _parse_simple_yaml_mapping(text: str) -> Optional[Dict[str, Any]]:
    # Minimal indentation-based YAML parser for simple mappings with numeric scalars.
    # Supports only nested mappings with keys and numeric values. No lists.
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    # stack of tuples: (indent_level, current_container)
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]

    def leading_spaces_count(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    for raw in lines:
        # Remove comments
        line = raw.split("#", 1)[0]
        if not line.strip():
            continue
        indent = leading_spaces_count(line)
        stripped = line.strip()
        if ":" not in stripped:
            # Not supported; malformed for our purposes
            return None
        key, after = stripped.split(":", 1)
        key = key.strip()
        val = after.strip()

        # Adjust stack based on indent
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]

        if val == "":
            # Mapping node
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            # Expect children at greater indent
            stack.append((indent + 2, new_map))
        else:
            # Scalar value
            num = _parse_number(val)
            current[key] = num if num is not None else val
    return root


def _median(values: List[float]) -> float:
    if not values:
        return float("nan")
    arr = sorted(values)
    n = len(arr)
    mid = n // 2
    if n % 2 == 1:
        return float(arr[mid])
    else:
        return float((arr[mid - 1] + arr[mid]) / 2.0)


def _close(a: float, b: float, tol: float = 1e-6) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol


def _load_balance_ranges(workspace: Path) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    path = workspace / "input" / "docs" / "balance.yaml"
    text = _safe_read_text(path)
    if text is None:
        return None
    parsed = _parse_simple_yaml_mapping(text)
    if not isinstance(parsed, dict):
        return None
    # Expect structure: { archetypes: { <arch>: { health: {min, max}, speed: {min, max}} } }
    archetypes = parsed.get("archetypes")
    if not isinstance(archetypes, dict):
        return None
    # Validate numeric ranges present
    for arch, cfg in archetypes.items():
        if not isinstance(cfg, dict):
            return None
        for stat in ("health", "speed"):
            stat_cfg = cfg.get(stat)
            if not isinstance(stat_cfg, dict):
                return None
            if not isinstance(stat_cfg.get("min"), (int, float)) or not isinstance(stat_cfg.get("max"), (int, float)):
                return None
    return archetypes  # type: ignore


def _load_characters(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    chars_dir = workspace / "input" / "characters"
    if not chars_dir.exists() or not chars_dir.is_dir():
        return None
    results: List[Dict[str, Any]] = []
    try:
        for p in sorted(chars_dir.glob("*.json")):
            data = _safe_load_json(p)
            if not isinstance(data, dict):
                return None
            # Require mandatory fields we use
            for field in ("name", "archetype", "health", "speed", "model_polycount", "animations"):
                if field not in data:
                    return None
            if not isinstance(data["name"], str):
                return None
            if not isinstance(data["archetype"], str):
                return None
            # Accept ints or floats for numbers
            for field in ("health", "speed", "model_polycount"):
                if not isinstance(data[field], (int, float)):
                    return None
            if not isinstance(data["animations"], list) or not all(isinstance(x, str) for x in data["animations"]):
                return None
            results.append(data)
    except Exception:
        return None
    return results


def _enumerate_existing_anims(workspace: Path) -> Optional[Set[str]]:
    base = workspace / "input" / "assets" / "anims"
    if not base.exists() or not base.is_dir():
        return None
    existing: Set[str] = set()
    try:
        for file in base.rglob("*.anim.json"):
            # Build relative path relative to input/assets/
            rel_to_assets = file.parent.relative_to(workspace / "input" / "assets").as_posix()
            rel_path = f"{rel_to_assets}/{file.name}" if rel_to_assets != "." else file.name
            # Ensure it starts with anims/
            if not rel_path.startswith("anims/"):
                rel_path = "anims/" + rel_path
            existing.add(rel_path)
    except Exception:
        return None
    return existing


def _resolve_anim_exists(workspace: Path, rel_anim: str) -> bool:
    # rel_anim like anims/...
    path = workspace / "input" / "assets" / rel_anim
    return path.exists() and path.is_file()


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    characters = _load_characters(workspace)
    balance = _load_balance_ranges(workspace)
    existing_anims = _enumerate_existing_anims(workspace)
    if characters is None or balance is None or existing_anims is None:
        return None

    # Compute per-character expected data
    per_char: Dict[str, Dict[str, Any]] = {}
    all_referenced_anims: Set[str] = set()
    missing_map: Dict[str, List[str]] = {}
    for ch in characters:
        name = ch["name"]
        arch = ch["archetype"]
        health = float(ch["health"])
        speed = float(ch["speed"])
        poly = float(ch["model_polycount"])
        anims: List[str] = list(ch["animations"])
        all_referenced_anims.update(anims)

        # Bounds inclusive
        if arch in balance:
            hmin = float(balance[arch]["health"]["min"])
            hmax = float(balance[arch]["health"]["max"])
            smin = float(balance[arch]["speed"]["min"])
            smax = float(balance[arch]["speed"]["max"])
        else:
            # If archetype not found, treat as out of range deterministically
            hmin = float("inf")
            hmax = float("-inf")
            smin = float("inf")
            smax = float("-inf")
        is_h_in = (health >= hmin) and (health <= hmax)
        is_s_in = (speed >= smin) and (speed <= smax)

        missing_list: List[str] = []
        for a in anims:
            # Must start with anims/
            # Existence check based on joining input/assets/ + rel path
            exists = _resolve_anim_exists(workspace, a)
            if not exists:
                missing_list.append(a)
                missing_map.setdefault(a, []).append(name)

        per_char[name] = {
            "name": name,
            "archetype": arch,
            "health": health,
            "speed": speed,
            "model_polycount": poly,
            "animation_refs_count": len(anims),
            "missing_animations": missing_list,
            "is_health_in_range": is_h_in,
            "is_speed_in_range": is_s_in,
            "referenced_anims": anims,
        }

    # Compute per-archetype aggregates
    per_arch_chars: Dict[str, List[Dict[str, Any]]] = {}
    for ch in per_char.values():
        per_arch_chars.setdefault(ch["archetype"], []).append(ch)

    per_arch_expected: Dict[str, Dict[str, Any]] = {}
    for arch, chs in per_arch_chars.items():
        num = len(chs)
        healths = [float(c["health"]) for c in chs]
        speeds = [float(c["speed"]) for c in chs]
        polys = [float(c["model_polycount"]) for c in chs]
        avg_health = sum(healths) / num if num > 0 else float("nan")
        median_speed = _median(speeds)
        avg_poly = sum(polys) / num if num > 0 else float("nan")
        # Unique anims referenced by characters in that archetype
        unique_anims: Set[str] = set()
        total_refs = 0
        missing_refs = 0
        for c in chs:
            unique_anims.update(c["referenced_anims"])
            total_refs += int(c["animation_refs_count"])
            missing_refs += len(c["missing_animations"])
        uniq_count = len(unique_anims)
        missing_pct = (missing_refs / total_refs) if total_refs > 0 else 0.0

        per_arch_expected[arch] = {
            "archetype": arch,
            "num_characters": num,
            "avg_health": avg_health,
            "median_speed": median_speed,
            "avg_model_polycount": avg_poly,
            "total_unique_anims_referenced": uniq_count,
            "missing_anim_refs": missing_refs,
            "missing_anim_ref_pct": missing_pct,
        }

    # Existing anim files under input/assets/anims
    existing_set = _enumerate_existing_anims(workspace)
    if existing_set is None:
        return None

    # Unused animations: present but not referenced by any character
    unreferenced = set(existing_set) - set(all_referenced_anims)

    return {
        "per_char": per_char,
        "per_arch": per_arch_expected,
        "missing_map": missing_map,
        "unreferenced_anims": unreferenced,
        "all_referenced_anims": set(all_referenced_anims),
        "balance": balance,
    }


def _parse_csv_to_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            header = reader.fieldnames
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _text_contains_token_with_nearby_names(text: str, token: str, names: List[str], window: int = 200) -> bool:
    # For each name, ensure token exists, and at least one occurrence has the name within a window around it.
    idxs: List[int] = []
    start = 0
    low_text = text
    low_token = token
    while True:
        i = low_text.find(low_token, start)
        if i == -1:
            break
        idxs.append(i)
        start = i + len(low_token)
    if not idxs:
        return False
    for name in names:
        name_found = False
        for i in idxs:
            # Consider nearby window
            left = max(0, i - window)
            right = min(len(text), i + len(token) + window)
            if name in text[left:right]:
                name_found = True
                break
        if not name_found:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "character_catalog_exists_and_parseable": 0.0,
        "character_catalog_fields_and_values": 0.0,
        "character_catalog_in_range_flags_correct": 0.0,
        "character_catalog_missing_animation_detection": 0.0,
        "character_catalog_warning_counts": 0.0,
        "archetype_aggregates_exists_and_parseable": 0.0,
        "archetype_aggregates_header_correct": 0.0,
        "archetype_aggregates_rows_complete": 0.0,
        "archetype_aggregates_values_correct": 0.0,
        "findings_missing_refs_listed_with_characters": 0.0,
        "findings_unreferenced_anims_listed": 0.0,
        "findings_archetype_compliance_summary_present": 0.0,
    }

    expected = _compute_expected(workspace)
    # Paths to deliverables
    cat_path = workspace / "output" / "character_catalog.json"
    csv_path = workspace / "output" / "stats" / "archetype_aggregates.csv"
    md_path = workspace / "output" / "findings.md"

    # Character catalog checks
    catalog = _safe_load_json(cat_path)
    if isinstance(catalog, list):
        scores["character_catalog_exists_and_parseable"] = 1.0
    # Only proceed with deeper checks if expected is available and file parsed
    if expected is not None and isinstance(catalog, list):
        per_char_exp: Dict[str, Dict[str, Any]] = expected["per_char"]
        # Build map by name
        by_name: Dict[str, Any] = {}
        fields_ok = True
        range_ok = True
        missing_ok = True
        warn_ok = True
        for item in catalog:
            if not isinstance(item, dict):
                fields_ok = False
                range_ok = False
                missing_ok = False
                warn_ok = False
                break
            name = item.get("name")
            if not isinstance(name, str):
                fields_ok = False
                range_ok = False
                missing_ok = False
                warn_ok = False
                break
            by_name[name] = item

        # Check every expected character exists with correct fields and values
        for cname, exp in per_char_exp.items():
            if cname not in by_name:
                fields_ok = False
                range_ok = False
                missing_ok = False
                warn_ok = False
                continue
            got = by_name[cname]
            # Fields and types + exact values where specified
            required_fields = [
                "name",
                "archetype",
                "health",
                "speed",
                "model_polycount",
                "animation_refs_count",
                "missing_animations",
                "is_health_in_range",
                "is_speed_in_range",
                "warnings",
            ]
            for f in required_fields:
                if f not in got:
                    fields_ok = False
            # Values
            if got.get("name") != exp["name"]:
                fields_ok = False
            if got.get("archetype") != exp["archetype"]:
                fields_ok = False
            # Numeric equalities (allow int or float)
            try:
                if float(got.get("health")) != float(exp["health"]):
                    fields_ok = False
                if float(got.get("speed")) != float(exp["speed"]):
                    fields_ok = False
                if float(got.get("model_polycount")) != float(exp["model_polycount"]):
                    fields_ok = False
            except Exception:
                fields_ok = False
            # animation_refs_count correctness
            try:
                if int(got.get("animation_refs_count")) != int(exp["animation_refs_count"]):
                    fields_ok = False
            except Exception:
                fields_ok = False
            # missing_animations exact list
            if not isinstance(got.get("missing_animations"), list):
                missing_ok = False
            else:
                exp_missing = list(exp["missing_animations"])
                got_missing = got["missing_animations"]
                # Strict equality including order
                if got_missing != exp_missing:
                    missing_ok = False
            # range flags exact boolean
            if bool(got.get("is_health_in_range")) != bool(exp["is_health_in_range"]):
                range_ok = False
            if bool(got.get("is_speed_in_range")) != bool(exp["is_speed_in_range"]):
                range_ok = False
            # warnings: count equals number of out-of-range stats + number of missing animations
            warnings = got.get("warnings")
            if not isinstance(warnings, list):
                warn_ok = False
            else:
                exp_warn_count = (0 if exp["is_health_in_range"] else 1) + (0 if exp["is_speed_in_range"] else 1) + len(exp["missing_animations"])
                if len(warnings) != exp_warn_count:
                    warn_ok = False

        scores["character_catalog_fields_and_values"] = 1.0 if fields_ok else 0.0
        scores["character_catalog_in_range_flags_correct"] = 1.0 if range_ok else 0.0
        scores["character_catalog_missing_animation_detection"] = 1.0 if missing_ok else 0.0
        scores["character_catalog_warning_counts"] = 1.0 if warn_ok else 0.0

    # Archetype aggregates CSV checks
    csv_parsed = _parse_csv_to_rows(csv_path)
    if csv_parsed is not None:
        scores["archetype_aggregates_exists_and_parseable"] = 1.0
        header, rows = csv_parsed
        expected_header = [
            "archetype",
            "num_characters",
            "avg_health",
            "median_speed",
            "avg_model_polycount",
            "total_unique_anims_referenced",
            "missing_anim_refs",
            "missing_anim_ref_pct",
        ]
        scores["archetype_aggregates_header_correct"] = 1.0 if header == expected_header else 0.0

        if expected is not None:
            per_arch_exp = expected["per_arch"]
            # Check row count and archetype set
            got_set = set()
            for r in rows:
                if "archetype" in r:
                    got_set.add(r["archetype"])
            rows_complete = got_set == set(per_arch_exp.keys()) and len(rows) == len(per_arch_exp)
            scores["archetype_aggregates_rows_complete"] = 1.0 if rows_complete else 0.0

            # Values correctness
            values_ok = True
            # Build map by archetype
            by_arch: Dict[str, Dict[str, str]] = {r["archetype"]: r for r in rows if "archetype" in r}
            for arch, exp in per_arch_exp.items():
                if arch not in by_arch:
                    values_ok = False
                    continue
                row = by_arch[arch]
                # Parse and compare
                try:
                    num_char = int(row["num_characters"])
                    uniq = int(row["total_unique_anims_referenced"])
                    miss_refs = int(row["missing_anim_refs"])
                    avg_h = float(row["avg_health"])
                    med_s = float(row["median_speed"])
                    avg_p = float(row["avg_model_polycount"])
                    miss_pct = float(row["missing_anim_ref_pct"])
                except Exception:
                    values_ok = False
                    continue
                if num_char != int(exp["num_characters"]):
                    values_ok = False
                if uniq != int(exp["total_unique_anims_referenced"]):
                    values_ok = False
                if miss_refs != int(exp["missing_anim_refs"]):
                    values_ok = False
                if not _close(avg_h, float(exp["avg_health"])):
                    values_ok = False
                if not _close(med_s, float(exp["median_speed"])):
                    values_ok = False
                if not _close(avg_p, float(exp["avg_model_polycount"])):
                    values_ok = False
                if not _close(miss_pct, float(exp["missing_anim_ref_pct"])):
                    values_ok = False
            scores["archetype_aggregates_values_correct"] = 1.0 if values_ok else 0.0

    # findings.md checks
    findings_text = _safe_read_text(md_path)
    if findings_text is not None:
        if expected is not None:
            # Missing refs listed with characters
            missing_map: Dict[str, List[str]] = expected["missing_map"]
            if missing_map:
                all_ok = True
                for rel_path, char_names in missing_map.items():
                    # The spec says: list missing animation references (relative to input/assets/) and which characters referenced them
                    # Check token and nearby names present
                    if not _text_contains_token_with_nearby_names(findings_text, rel_path, char_names, window=200):
                        all_ok = False
                        break
                scores["findings_missing_refs_listed_with_characters"] = 1.0 if all_ok else 0.0
            else:
                # If none missing, consider passing if text mentions none or has an explicit empty list; here we pass if there are no missing
                scores["findings_missing_refs_listed_with_characters"] = 1.0

            # Unreferenced anims listed
            unref: Set[str] = expected["unreferenced_anims"]
            if unref:
                all_ok = True
                for rel_path in unref:
                    if rel_path not in findings_text:
                        all_ok = False
                        break
                scores["findings_unreferenced_anims_listed"] = 1.0 if all_ok else 0.0
            else:
                scores["findings_unreferenced_anims_listed"] = 1.0

            # Archetype compliance summary
            per_char_exp: Dict[str, Dict[str, Any]] = expected["per_char"]
            per_arch_names: Set[str] = set(expected["per_arch"].keys())
            # Compute counts
            arch_counts: Dict[str, Tuple[int, int, int]] = {}  # arch -> (num, health_in, speed_in)
            for arch in per_arch_names:
                chars = [c for c in per_char_exp.values() if c["archetype"] == arch]
                num = len(chars)
                h_in = sum(1 for c in chars if bool(c["is_health_in_range"]))
                s_in = sum(1 for c in chars if bool(c["is_speed_in_range"]))
                arch_counts[arch] = (num, h_in, s_in)
            # Find lines containing summaries
            lines = findings_text.splitlines()
            all_arch_ok = True
            for arch, (num, h_in, s_in) in arch_counts.items():
                # Look for a line that contains the archetype name and conveys h_in/num for health and s_in/num for speed
                matched = False
                for ln in lines:
                    if arch not in ln:
                        continue
                    # Normalize spaces
                    l = ln.strip()
                    # Pattern 1: health then speed
                    pat1 = re.compile(rf"{re.escape(arch)}.*?(\d+)\s*/\s*({num})\s*.*?health.*?(\d+)\s*/\s*({num})\s*.*?speed", re.IGNORECASE)
                    m1 = pat1.search(l)
                    if m1:
                        try:
                            h_in_got = int(m1.group(1))
                            s_in_got = int(m1.group(3))
                            if h_in_got == h_in and s_in_got == s_in:
                                matched = True
                                break
                        except Exception:
                            pass
                    # Pattern 2: speed then health
                    pat2 = re.compile(rf"{re.escape(arch)}.*?(\d+)\s*/\s*({num})\s*.*?speed.*?(\d+)\s*/\s*({num})\s*.*?health", re.IGNORECASE)
                    m2 = pat2.search(l)
                    if m2:
                        try:
                            s_in_got = int(m2.group(1))
                            h_in_got = int(m2.group(3))
                            if h_in_got == h_in and s_in_got == s_in:
                                matched = True
                                break
                        except Exception:
                            pass
                if not matched:
                    all_arch_ok = False
                    break
            scores["findings_archetype_compliance_summary_present"] = 1.0 if all_arch_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()