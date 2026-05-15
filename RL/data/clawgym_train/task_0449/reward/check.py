import json
import sys
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional


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


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _compute_input_bullet_structure(text: str) -> Dict[str, Any]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    bullet_runs = []
    current_run = 0
    bullet_total = 0
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("- "):
            current_run += 1
            bullet_total += 1
        else:
            if current_run > 0:
                bullet_runs.append(current_run)
                current_run = 0
    if current_run > 0:
        bullet_runs.append(current_run)
    colon_only_count = sum(1 for ln in lines if ln.strip().endswith(":") and ln.strip().startswith(tuple([ln.strip()])))

    # colon_only_count logic is naive above; better: endswith ":" and has no other non-space after colon
    colon_only_count = 0
    for ln in lines:
        stripped = ln.strip()
        if stripped.endswith(":"):
            # Ensure it's just a header line, not "Hallazgos: something"
            before, _, after = stripped.partition(":")
            if after == "":
                colon_only_count += 1

    return {
        "bullet_total": bullet_total,
        "bullet_runs": bullet_runs,
        "colon_only_headers": colon_only_count,
    }


def _compute_output_bullet_structure(text: str) -> Dict[str, Any]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    bullet_runs = []
    current_run = 0
    bullet_total = 0
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("- "):
            current_run += 1
            bullet_total += 1
        else:
            if current_run > 0:
                bullet_runs.append(current_run)
                current_run = 0
    if current_run > 0:
        bullet_runs.append(current_run)
    colon_only_count = 0
    for ln in lines:
        stripped = ln.strip()
        if stripped.endswith(":"):
            before, _, after = stripped.partition(":")
            if after == "":
                colon_only_count += 1
    return {
        "bullet_total": bullet_total,
        "bullet_runs": bullet_runs,
        "colon_only_headers": colon_only_count,
    }


def _recompute_shortlist(providers_csv: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _load_csv_rows(providers_csv)
    if rows is None:
        return None
    # Filter
    filtered = []
    for r in rows:
        accepts = (r.get("accepts_insurance", "").strip().upper() == "Y")
        new_patients = (r.get("new_patients", "").strip().upper() == "Y")
        lang_services = r.get("language_services", "")
        lang_lower = lang_services.lower()
        has_interpreter = "spanish interpreter" in lang_lower
        # Determine native Spanish: exact token "spanish" when splitting on ';'
        tokens = [t.strip().lower() for t in lang_services.split(";")]
        has_native = any(t == "spanish" for t in tokens)
        has_spanish_any = has_interpreter or has_native
        if accepts and new_patients and has_spanish_any:
            # Derive language_support_type
            if has_native and has_interpreter:
                lstype = "Both"
            elif has_native:
                lstype = "Native Spanish"
            else:
                lstype = "Interpreter"
            # Collect necessary fields
            try:
                wait_days = int(str(r.get("wait_days", "")).strip())
            except Exception:
                try:
                    wait_days = int(float(str(r.get("wait_days", "")).strip()))
                except Exception:
                    wait_days = None
            try:
                distance_km = float(str(r.get("distance_km", "")).strip())
            except Exception:
                distance_km = None
            filtered.append({
                "provider_id": r.get("provider_id", "").strip(),
                "name": r.get("name", "").strip(),
                "wait_days": wait_days,
                "distance_km": distance_km,
                "language_support_type": lstype,
                "has_patient_advocate": r.get("has_patient_advocate", "").strip(),
            })
    # Sort with tie-breakers:
    # 1) Smaller wait_days first
    # 2) Shorter distance_km next
    # 3) has_patient_advocate = Y before N
    # 4) language_support_type order: Native Spanish, Both, Interpreter
    order_map = {"Native Spanish": 0, "Both": 1, "Interpreter": 2}
    def sort_key(item: Dict[str, Any]):
        wait = item["wait_days"]
        dist = item["distance_km"]
        advocate = 0 if item["has_patient_advocate"].upper() == "Y" else 1
        lang_priority = order_map.get(item["language_support_type"], 99)
        return (wait if wait is not None else 10**9,
                dist if dist is not None else 10**9,
                advocate,
                lang_priority)
    filtered.sort(key=sort_key)
    # Add composite_rank
    for i, item in enumerate(filtered, start=1):
        item["composite_rank"] = i
    return filtered


def _parse_log_patterns(log_text: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns expected patterns with counts and earliest step:
    keys: pattern_id with 'needle' for matching substrings (lowercase), 'occurrences' count in the input log, 'first_step'
    """
    patterns = {
        "token_expired": {"needle": "unauthorized: token expired", "occurrences": 0, "first_step": None},
        "isa_mismatch": {"needle": "isa control number mismatch", "occurrences": 0, "first_step": None},
        "member_not_found": {"needle": "member not found", "occurrences": 0, "first_step": None},
        "network_timeout": {"needle": "network timeout", "occurrences": 0, "first_step": None},
        "plan_year_mismatch": {"needle": "plan year mismatch", "occurrences": 0, "first_step": None},
    }
    lines = [ln.rstrip("\n") for ln in log_text.splitlines()]
    for idx, ln in enumerate(lines):
        low = ln.lower()
        if "[error]" not in low:
            continue
        # try to extract step=
        step = None
        if "step=" in ln:
            # basic parse step= until space
            try:
                after = ln.split("step=", 1)[1]
                step_val = after.split()[0]
                # strip trailing punctuation
                step = step_val.strip().strip(',')
            except Exception:
                step = None
        for key, info in patterns.items():
            if info["needle"] in low:
                info["occurrences"] += 1
                if info["first_step"] is None:
                    info["first_step"] = step
    return patterns


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        # Part 1: Translation
        "translation_file_exists": 0.0,
        "translation_no_spanish_headings": 0.0,
        "translation_bullet_count_preserved": 0.0,
        "translation_header_count_preserved": 0.0,
        "translation_bullet_run_structure": 0.0,
        # Part 2: Providers shortlist
        "providers_shortlist_csv_structure": 0.0,
        "providers_shortlist_rows_order_and_values": 0.0,
        "providers_language_support_type_correct": 0.0,
        "providers_ranking_json_correct": 0.0,
        # Part 3: Error analysis
        "error_summary_json_structure": 0.0,
        "error_patterns_covered": 0.0,
        "error_counts_and_steps_correct": 0.0,
        "error_suggested_actions_present": 0.0,
        "eligibility_summary_md_exists": 0.0,
    }

    # Paths
    input_notes = workspace / "input" / "notes_es.txt"
    out_translation = workspace / "outputs" / "translation" / "notes_en.txt"
    providers_csv = workspace / "input" / "providers.csv"
    shortlist_csv = workspace / "outputs" / "providers" / "shortlist.csv"
    ranking_json_path = workspace / "outputs" / "providers" / "ranking.json"
    eligibility_log = workspace / "input" / "eligibility_cli.log"
    error_summary_json = workspace / "outputs" / "analysis" / "error_summary.json"
    eligibility_summary_md = workspace / "outputs" / "analysis" / "eligibility_summary.md"

    # Part 1: Translation checks
    input_text = _read_text(input_notes) or ""
    output_text = _read_text(out_translation)
    if output_text is not None and len(output_text.strip()) > 0:
        scores["translation_file_exists"] = 1.0
        # Check that Spanish section keywords are not present in translation
        lowered = output_text.lower()
        spanish_keywords = [
            "resumen de alta", "diagnóstico principal", "hallazgos",
            "indicaciones", "signos de alarma", "citas y seguimiento",
            "contacto", "paciente", "llame", "electrolitos", "radiografía"
        ]
        if not any(k in lowered for k in spanish_keywords):
            scores["translation_no_spanish_headings"] = 1.0

        # Compare bullet counts and header counts
        in_struct = _compute_input_bullet_structure(input_text) if input_text else {"bullet_total": 0, "bullet_runs": [], "colon_only_headers": 0}
        out_struct = _compute_output_bullet_structure(output_text)
        # Exact bullet count
        if out_struct.get("bullet_total") == in_struct.get("bullet_total"):
            scores["translation_bullet_count_preserved"] = 1.0
        # Exact count of colon-only headers
        if out_struct.get("colon_only_headers") == in_struct.get("colon_only_headers"):
            scores["translation_header_count_preserved"] = 1.0
        # Bullet run structure equals [4,3,2,1]
        expected_runs = in_struct.get("bullet_runs", [])
        if out_struct.get("bullet_runs") == expected_runs and expected_runs != []:
            scores["translation_bullet_run_structure"] = 1.0
    else:
        # Missing or empty translation file; leave zeros
        pass

    # Part 2: Providers shortlist checks
    expected_shortlist = _recompute_shortlist(providers_csv)
    # Structure of shortlist.csv
    rows_out = None
    if shortlist_csv.exists():
        rows_out = _load_csv_rows(shortlist_csv)
    # Check CSV columns and structure
    expected_columns = ["provider_id", "name", "wait_days", "distance_km", "language_support_type", "has_patient_advocate", "composite_rank"]
    if rows_out is not None and isinstance(rows_out, list):
        # Validate header columns
        try:
            with shortlist_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        if header == expected_columns:
            scores["providers_shortlist_csv_structure"] = 1.0

        # Validate rows and order
        if expected_shortlist is not None:
            # Compare number of rows
            correct = True
            if len(rows_out) != len(expected_shortlist):
                correct = False
            else:
                # Verify each row fields match expected and order
                for idx, expected in enumerate(expected_shortlist):
                    ro = rows_out[idx]
                    # provider_id and name
                    if ro.get("provider_id", "").strip() != expected["provider_id"]:
                        correct = False
                        break
                    if ro.get("name", "").strip() != expected["name"]:
                        correct = False
                        break
                    # wait_days int
                    try:
                        wd = int(float(ro.get("wait_days", "").strip()))
                    except Exception:
                        correct = False
                        break
                    if wd != int(expected["wait_days"]):
                        correct = False
                        break
                    # distance_km float approx equality
                    try:
                        dk = float(ro.get("distance_km", "").strip())
                    except Exception:
                        correct = False
                        break
                    if abs(dk - float(expected["distance_km"])) > 1e-6:
                        correct = False
                        break
                    # has_patient_advocate
                    if ro.get("has_patient_advocate", "").strip().upper() != expected["has_patient_advocate"].upper():
                        correct = False
                        break
                    # composite_rank
                    try:
                        cr = int(float(ro.get("composite_rank", "").strip()))
                    except Exception:
                        correct = False
                        break
                    if cr != int(expected["composite_rank"]):
                        correct = False
                        break
                # If all matched, pass this check
            if correct:
                scores["providers_shortlist_rows_order_and_values"] = 1.0

            # Validate language_support_type correctness
            lstypes_ok = True
            if len(rows_out) == len(expected_shortlist):
                for idx, expected in enumerate(expected_shortlist):
                    ro = rows_out[idx]
                    if ro.get("language_support_type", "").strip() != expected["language_support_type"]:
                        lstypes_ok = False
                        break
            else:
                lstypes_ok = False
            if lstypes_ok:
                scores["providers_language_support_type_correct"] = 1.0
    # ranking.json checks
    ranking_json_ok = False
    rj = _load_json(ranking_json_path) if ranking_json_path.exists() else None
    if isinstance(rj, dict) and "criteria" in rj and "top_3_provider_ids" in rj:
        criteria_ok = isinstance(rj.get("criteria"), str) and len(rj.get("criteria", "").strip()) > 0
        top3 = rj.get("top_3_provider_ids")
        top3_ok = False
        if isinstance(top3, list):
            expected_ids = []
            if expected_shortlist is not None:
                expected_ids = [row["provider_id"] for row in expected_shortlist[:3]]
            # Only check equality if we have expected shortlist
            if expected_ids:
                top3_ok = top3 == expected_ids
            else:
                # If we cannot compute expected, at least ensure list of strings length <=3
                top3_ok = all(isinstance(x, str) for x in top3)
        ranking_json_ok = criteria_ok and top3_ok
    if ranking_json_ok:
        scores["providers_ranking_json_correct"] = 1.0

    # Part 3: Error analysis
    # Load log and expected patterns
    log_text = _read_text(eligibility_log) or ""
    patterns = _parse_log_patterns(log_text) if log_text else {}
    # Check error_summary.json structure
    esj = _load_json(error_summary_json) if error_summary_json.exists() else None
    structure_ok = False
    if isinstance(esj, list):
        # Each item must have fields
        required_fields = {"error_type", "occurrences", "first_seen_step", "examples", "suggested_action"}
        structure_ok = True
        for item in esj:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if not required_fields.issubset(set(item.keys())):
                structure_ok = False
                break
            # types
            if not isinstance(item.get("error_type"), str):
                structure_ok = False
                break
            if not isinstance(item.get("occurrences"), (int, float)):
                structure_ok = False
                break
            if item.get("first_seen_step") is not None and not isinstance(item.get("first_seen_step"), str):
                structure_ok = False
                break
            if not isinstance(item.get("examples"), list):
                structure_ok = False
                break
            if not isinstance(item.get("suggested_action"), str):
                structure_ok = False
                break
        if structure_ok:
            scores["error_summary_json_structure"] = 1.0

    # Coverage of patterns, counts, steps, and suggested_action presence
    covered = 0
    counts_correct = 0
    suggestions_ok = 0
    total_patterns = len(patterns) if patterns else 0
    if structure_ok and patterns:
        # Helper to find matching item for a pattern
        def find_item_for_pattern(needle: str) -> Optional[Dict[str, Any]]:
            needle_l = needle.lower()
            for item in esj:
                # check in examples, or in error_type
                examples = item.get("examples", [])
                found = False
                for ex in examples:
                    if isinstance(ex, str) and needle_l in ex.lower():
                        found = True
                        break
                if not found:
                    et = item.get("error_type", "")
                    if isinstance(et, str) and needle_l in et.lower():
                        found = True
                if found:
                    return item
            return None

        for key, info in patterns.items():
            item = find_item_for_pattern(info["needle"])
            if item is not None:
                covered += 1
                # Check occurrences
                occ = item.get("occurrences")
                occ_int = int(occ) if isinstance(occ, (int, float)) else None
                if occ_int == info["occurrences"]:
                    # Check first_seen_step
                    first_step = item.get("first_seen_step")
                    if (first_step == info["first_step"]) or (info["first_step"] is None and (first_step in [None, ""])):
                        counts_correct += 1
                # Check suggested_action non-empty
                sa = item.get("suggested_action", "")
                if isinstance(sa, str) and len(sa.strip()) > 0:
                    suggestions_ok += 1

        if total_patterns > 0:
            scores["error_patterns_covered"] = covered / total_patterns
            scores["error_counts_and_steps_correct"] = counts_correct / total_patterns
            scores["error_suggested_actions_present"] = suggestions_ok / total_patterns

    # Non-technical explanation file existence
    md_text = _read_text(eligibility_summary_md)
    if md_text is not None and len(md_text.strip()) > 0:
        scores["eligibility_summary_md_exists"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()