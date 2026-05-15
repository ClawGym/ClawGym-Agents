import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def load_csv_records(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None or any(row is None for row in rows):
                return None
            return rows
    except Exception:
        try:
            with path.open("r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if reader.fieldnames is None or any(row is None for row in rows):
                    return None
                return rows
        except Exception:
            return None


def list_csv_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists():
        return []
    return sorted([p for p in input_dir.rglob("*.csv") if p.is_file()])


def approx_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def compute_expected_from_inputs(input_dir: Path) -> Optional[Dict]:
    csv_files = list_csv_files(input_dir)
    if not csv_files:
        return None

    inventory: Dict[str, Dict[str, object]] = {}
    first_header = None
    schemas_consistent = True
    schema_mismatches: List[Tuple[str, List[str]]] = []

    all_rows = []
    for file in csv_files:
        records = load_csv_records(file)
        if records is None:
            return None
        try:
            with file.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
        except Exception:
            try:
                with file.open("r") as f:
                    header_line = f.readline().strip()
            except Exception:
                return None
        header_cols = header_line.split(",")
        if first_header is None:
            first_header = header_cols
        else:
            if header_cols != first_header:
                schemas_consistent = False
                schema_mismatches.append((str(file), header_cols))
        total_rows = len(records)
        tz_rows = [r for r in records if r.get("player") == "Tamara Zidanšek"]
        inventory[str(file)] = {
            "total_rows": total_rows,
            "tz_rows": len(tz_rows),
            "header": header_cols,
        }
        all_rows.extend(tz_rows)

    if not all_rows:
        total_matches = 0
        wins = 0
        losses = 0
        win_rate = 0.0
        avg_aces = 0.0
        avg_double_faults = 0.0
        avg_first_serve_pct = 0.0
        bpc_rate = 0.0
        top_opponents = []
        per_opp: Dict[str, Dict[str, int]] = {}
    else:
        total_matches = len(all_rows)
        wins = sum(1 for r in all_rows if (r.get("result") or "").strip() == "W")
        losses = sum(1 for r in all_rows if (r.get("result") or "").strip() == "L")
        win_rate = wins / total_matches if total_matches > 0 else 0.0

        def to_int(v: str) -> int:
            try:
                return int(str(v).strip())
            except Exception:
                return 0

        aces_sum = sum(to_int(r.get("aces", "0")) for r in all_rows)
        df_sum = sum(to_int(r.get("double_faults", "0")) for r in all_rows)
        fs_sum = sum(to_int(r.get("first_serve_pct", "0")) for r in all_rows)
        avg_aces = aces_sum / total_matches
        avg_double_faults = df_sum / total_matches
        avg_first_serve_pct = fs_sum / total_matches
        break_points_won_sum = sum(to_int(r.get("break_points_won", "0")) for r in all_rows)
        break_points_total_sum = sum(to_int(r.get("break_points_total", "0")) for r in all_rows)
        bpc_rate = (break_points_won_sum / break_points_total_sum) if break_points_total_sum > 0 else 0.0

        per_opp: Dict[str, Dict[str, int]] = {}
        for r in all_rows:
            opp = r.get("opponent", "").strip()
            res = (r.get("result") or "").strip()
            if opp not in per_opp:
                per_opp[opp] = {"matches": 0, "wins": 0, "losses": 0}
            per_opp[opp]["matches"] += 1
            if res == "W":
                per_opp[opp]["wins"] += 1
            elif res == "L":
                per_opp[opp]["losses"] += 1

        sorted_opps = sorted(
            per_opp.items(),
            key=lambda kv: (-kv[1]["matches"], kv[0])
        )
        top_opponents = []
        for opp, stats in sorted_opps[:3]:
            top_opponents.append({
                "opponent": opp,
                "matches": stats["matches"],
                "wins": stats["wins"],
                "losses": stats["losses"],
            })

    return {
        "csv_files": csv_files,
        "inventory": inventory,
        "schemas_consistent": schemas_consistent,
        "schema_mismatches": schema_mismatches,
        "summary": {
            "player": "Tamara Zidanšek",
            "total_matches": total_matches,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_aces": avg_aces,
            "avg_double_faults": avg_double_faults,
            "avg_first_serve_pct": avg_first_serve_pct,
            "break_point_conversion_rate": bpc_rate,
            "top_opponents_by_count": top_opponents,
        },
        "per_opponent": per_opp,
    }


def extract_section(lines: List[str], title: str) -> List[str]:
    section_lines: List[str] = []
    in_section = False
    title_lower = title.lower()
    for line in lines:
        if not in_section:
            if title_lower in line.strip().lower():
                in_section = True
                continue
        else:
            if re.match(r'^\s*#+\s+\S', line) and title_lower not in line.strip().lower():
                break
            section_lines.append(line)
    return section_lines


def parse_markdown_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for line in lines:
        if re.match(r'^\s*[-*]\s+', line):
            bullets.append(line.strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "requirements_txt_exists": 0.0,
        "analyze_script_exists": 0.0,
        "analyze_script_has_cli_args": 0.0,
        "data_inventory_lists_all_csvs": 0.0,
        "data_inventory_row_counts_correct": 0.0,
        "data_inventory_schema_note_present": 0.0,
        "zidansek_summary_json_exists_and_schema": 0.0,
        "zidansek_summary_values_correct": 0.0,
        "opponents_breakdown_csv_exists_and_header": 0.0,
        "opponents_breakdown_values_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_environment_setup_commands": 0.0,
        "meeting_notes_key_findings_quality": 0.0,
        "meeting_notes_action_items_count": 0.0,
    }

    input_dir = workspace / "input"
    expected = compute_expected_from_inputs(input_dir)

    req = workspace / "requirements.txt"
    if req.exists() and req.is_file():
        scores["requirements_txt_exists"] = 1.0

    script = workspace / "scripts" / "analyze_matches.py"
    if script.exists() and script.is_file():
        scores["analyze_script_exists"] = 1.0
        txt = read_text(script) or ""
        if ("--input-dir" in txt) and ("--out-dir" in txt):
            scores["analyze_script_has_cli_args"] = 1.0

    data_inventory = workspace / "output" / "data_inventory.md"
    if expected is not None and data_inventory.exists() and data_inventory.is_file():
        md_text = read_text(data_inventory) or ""
        md_lines = md_text.splitlines()

        all_listed = True
        for csv_path in expected["csv_files"]:
            basename = csv_path.name
            relpath = str(csv_path)
            try:
                rel_from_ws = str(csv_path.relative_to(workspace))
            except Exception:
                rel_from_ws = relpath
            found = False
            for line in md_lines:
                if basename in line or rel_from_ws in line or relpath in line:
                    found = True
                    break
            if not found:
                all_listed = False
                break
        if all_listed:
            scores["data_inventory_lists_all_csvs"] = 1.0

        counts_ok = True
        for csv_path in expected["csv_files"]:
            inv = expected["inventory"].get(str(csv_path))
            if inv is None:
                counts_ok = False
                break
            total_rows = inv["total_rows"]
            tz_rows = inv["tz_rows"]
            basename = csv_path.name
            try:
                rel_from_ws = str(csv_path.relative_to(workspace))
            except Exception:
                rel_from_ws = str(csv_path)
            idxs = [i for i, line in enumerate(md_lines) if (basename in line or rel_from_ws in line or str(csv_path) in line)]
            if not idxs:
                counts_ok = False
                break
            i0 = idxs[0]
            window = "\n".join(md_lines[i0:i0+5])
            if not re.search(rf'\b{total_rows}\b', window):
                counts_ok = False
                break
            if not re.search(rf'\b{tz_rows}\b', window):
                counts_ok = False
                break
        if counts_ok:
            scores["data_inventory_row_counts_correct"] = 1.0

        schema_note_ok = False
        for line in md_lines:
            if ("schema" in line.lower()) and ("consistent" in line.lower()):
                schema_note_ok = True
                break
        if schema_note_ok:
            scores["data_inventory_schema_note_present"] = 1.0

    summary_path = workspace / "output" / "zidansek_summary.json"
    if summary_path.exists() and summary_path.is_file():
        try:
            with summary_path.open("r", encoding="utf-8") as f:
                summary_data = json.load(f)
        except Exception:
            summary_data = None
        if isinstance(summary_data, dict):
            required_fields = [
                "player",
                "total_matches",
                "wins",
                "losses",
                "win_rate",
                "avg_aces",
                "avg_double_faults",
                "avg_first_serve_pct",
                "break_point_conversion_rate",
                "top_opponents_by_count",
            ]
            has_all = all(k in summary_data for k in required_fields)
            correct_types = isinstance(summary_data.get("top_opponents_by_count"), list)
            if has_all and correct_types:
                scores["zidansek_summary_json_exists_and_schema"] = 1.0

            if expected is not None:
                exp = expected["summary"]
                try:
                    vals_ok = True
                    vals_ok &= (summary_data.get("player") == exp["player"])
                    vals_ok &= (int(summary_data.get("total_matches")) == exp["total_matches"])
                    vals_ok &= (int(summary_data.get("wins")) == exp["wins"])
                    vals_ok &= (int(summary_data.get("losses")) == exp["losses"])
                    vals_ok &= approx_equal(float(summary_data.get("win_rate")), exp["win_rate"], tol=1e-3)
                    vals_ok &= approx_equal(float(summary_data.get("avg_aces")), exp["avg_aces"], tol=1e-3)
                    vals_ok &= approx_equal(float(summary_data.get("avg_double_faults")), exp["avg_double_faults"], tol=1e-3)
                    vals_ok &= approx_equal(float(summary_data.get("avg_first_serve_pct")), exp["avg_first_serve_pct"], tol=1e-3)
                    vals_ok &= approx_equal(float(summary_data.get("break_point_conversion_rate")), exp["break_point_conversion_rate"], tol=1e-3)
                    top_list = summary_data.get("top_opponents_by_count")
                    if not isinstance(top_list, list):
                        vals_ok = False
                    else:
                        expected_top = exp["top_opponents_by_count"]
                        if len(top_list) != len(expected_top):
                            vals_ok = False
                        else:
                            for i, item in enumerate(top_list):
                                exp_item = expected_top[i]
                                if not isinstance(item, dict):
                                    vals_ok = False
                                    break
                                if not (
                                    item.get("opponent") == exp_item["opponent"]
                                    and int(item.get("matches", -1)) == exp_item["matches"]
                                    and int(item.get("wins", -1)) == exp_item["wins"]
                                    and int(item.get("losses", -1)) == exp_item["losses"]
                                ):
                                    vals_ok = False
                                    break
                    if vals_ok:
                        scores["zidansek_summary_values_correct"] = 1.0
                except Exception:
                    pass

    opponents_csv = workspace / "output" / "opponents_breakdown.csv"
    if opponents_csv.exists() and opponents_csv.is_file():
        rows = load_csv_records(opponents_csv)
        if rows is not None:
            try:
                with opponents_csv.open("r", encoding="utf-8") as f:
                    header_line = f.readline().strip()
            except Exception:
                try:
                    with opponents_csv.open("r") as f:
                        header_line = f.readline().strip()
                except Exception:
                    header_line = ""
            if header_line == "opponent,matches,wins,losses,win_rate":
                scores["opponents_breakdown_csv_exists_and_header"] = 1.0

            if expected is not None:
                exp_per = expected["per_opponent"]
                try:
                    csv_map: Dict[str, Dict[str, float]] = {}
                    for r in rows:
                        opp = (r.get("opponent") or "").strip()
                        if not opp:
                            continue
                        try:
                            matches = int(str(r.get("matches", "0")).strip())
                            wins = int(str(r.get("wins", "0")).strip())
                            losses = int(str(r.get("losses", "0")).strip())
                            win_rate = float(str(r.get("win_rate", "0")).strip())
                        except Exception:
                            csv_map = {}
                            break
                        csv_map[opp] = {
                            "matches": matches,
                            "wins": wins,
                            "losses": losses,
                            "win_rate": win_rate,
                        }
                    if csv_map:
                        exp_opps = set(exp_per.keys())
                        csv_opps = set(csv_map.keys())
                        if exp_opps == csv_opps:
                            all_ok = True
                            for opp, stats in exp_per.items():
                                m = stats["matches"]
                                w = stats["wins"]
                                l = stats["losses"]
                                wr = (w / m) if m > 0 else 0.0
                                got = csv_map.get(opp, {})
                                all_ok &= (got.get("matches") == m)
                                all_ok &= (got.get("wins") == w)
                                all_ok &= (got.get("losses") == l)
                                all_ok &= approx_equal(got.get("win_rate", -1.0), wr, tol=1e-3)
                            if all_ok:
                                scores["opponents_breakdown_values_correct"] = 1.0
                except Exception:
                    pass

    meeting_notes = workspace / "output" / "MEETING_NOTES.md"
    if meeting_notes.exists() and meeting_notes.is_file():
        scores["meeting_notes_exists"] = 1.0
        text = read_text(meeting_notes) or ""
        lines = text.splitlines()

        env_sec = extract_section(lines, "Environment Setup")
        env_ok = False
        if env_sec:
            has_venv = any("python -m venv" in ln and ".venv" in ln for ln in env_sec)
            has_activate = any("activate" in ln for ln in env_sec)
            has_default_run = any(
                ("python" in ln and "scripts/analyze_matches.py" in ln and "--input-dir" not in ln and "--out-dir" not in ln)
                for ln in env_sec
            )
            has_explicit_run = any(
                ("python" in ln and "scripts/analyze_matches.py" in ln and "--input-dir" in ln and "--out-dir" in ln)
                for ln in env_sec
            )
            env_ok = has_venv and has_activate and has_default_run and has_explicit_run
        if env_ok:
            scores["meeting_notes_environment_setup_commands"] = 1.0

        kf_sec = extract_section(lines, "Key Findings")
        kf_bullets = parse_markdown_bullets(kf_sec)
        kf_ok = False
        if len(kf_bullets) >= 3:
            has_total_matches = any(re.search(r'\b10\b', ln) for ln in kf_bullets)
            has_winrate_pct = any(re.search(r'50(\.0+)?\s*%', ln) for ln in kf_bullets)
            has_opponent = any("Paula Badosa" in ln for ln in kf_bullets)
            has_head_to_head = any(re.search(r'\b1\s*-\s*1\b', ln) or re.search(r'\b1\s*–\s*1\b', ln) for ln in kf_bullets)
            kf_ok = has_total_matches and has_winrate_pct and has_opponent and has_head_to_head
        if kf_ok:
            scores["meeting_notes_key_findings_quality"] = 1.0

        ai_sec = extract_section(lines, "Action Items")
        ai_bullets = parse_markdown_bullets(ai_sec)
        if len(ai_bullets) >= 4:
            scores["meeting_notes_action_items_count"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()