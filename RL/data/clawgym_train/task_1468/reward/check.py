import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                norm_row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(norm_row)
            return rows
    except Exception:
        return None


def _to_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, int):
            return val
        s = str(val).strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r'[-+]?\d+(?:\.\d+)?', text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _compat_lookup(comp_map: Dict[Tuple[str, str], float], theme_a: str, theme_b: str) -> float:
    if (theme_a, theme_b) in comp_map:
        return comp_map[(theme_a, theme_b)]
    if (theme_b, theme_a) in comp_map:
        return comp_map[(theme_b, theme_a)]
    return 0.0


def _parse_meeting_notes_sections(text: str) -> Dict[str, Tuple[int, int]]:
    lines = text.splitlines()
    sections = ["Context", "Approach", "Key constraints checked", "Action items for studio review", "Open questions"]
    indices: Dict[str, Tuple[int, int]] = {}
    header_positions: List[Tuple[str, int]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for sec in sections:
            pattern = re.compile(r'^\s{0,3}#{0,6}\s*' + re.escape(sec) + r'\b', re.IGNORECASE)
            if pattern.match(stripped):
                header_positions.append((sec.lower(), idx))
                break
    header_positions.sort(key=lambda x: x[1])
    for i, (sec_low, start) in enumerate(header_positions):
        end = len(lines)
        if i + 1 < len(header_positions):
            end = header_positions[i + 1][1]
        indices[sec_low] = (start, end)
    return indices


def _count_bullets_in_section(text: str, start: int, end: int) -> int:
    lines = text.splitlines()[start:end]
    count = 0
    for ln in lines:
        s = ln.strip()
        if re.match(r'^[-*•]\s+', s):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "room_assignments_file_valid": 0.0,
        "all_exhibits_mapped_once": 0.0,
        "room_ids_valid_and_unassigned_present": 0.0,
        "capacity_constraints_satisfied": 0.0,
        "adjacency_scores_coverage": 0.0,
        "adjacency_scores_values_correct": 0.0,
        "summary_totals_correct": 0.0,
        "summary_rooms_section_correct": 0.0,
        "summary_unassigned_correct": 0.0,
        "cross_output_totals_consistent": 0.0,
        "meeting_notes_structure_and_totals_reference": 0.0,
        "email_structure_content_and_attachments": 0.0,
    }

    exhibits_path = workspace / "input" / "exhibits.csv"
    rooms_path = workspace / "input" / "rooms.csv"
    graph_path = workspace / "input" / "floorplan_graph.csv"
    comp_path = workspace / "input" / "compatibility.csv"

    exhibits_rows = _load_csv_dicts(exhibits_path)
    rooms_rows = _load_csv_dicts(rooms_path)
    graph_rows = _load_csv_dicts(graph_path)
    comp_rows = _load_csv_dicts(comp_path)

    valid_inputs = True
    if exhibits_rows is None or rooms_rows is None or graph_rows is None or comp_rows is None:
        valid_inputs = False

    exhibits: Dict[int, Dict[str, Any]] = {}
    rooms_area: Dict[str, float] = {}
    graph_edges: Dict[frozenset, float] = {}
    comp_map: Dict[Tuple[str, str], float] = {}

    if valid_inputs:
        try:
            for r in exhibits_rows:
                eid = _to_int(r.get("id"))
                name = r.get("name", "")
                theme = r.get("theme", "")
                area = _to_float(r.get("area_sqm"))
                imp = _to_int(r.get("importance"))
                if eid is None or theme == "" or area is None or imp is None:
                    valid_inputs = False
                    break
                exhibits[eid] = {
                    "name": name,
                    "theme": theme,
                    "area": float(area),
                    "importance": int(imp),
                }
        except Exception:
            valid_inputs = False

        if valid_inputs:
            try:
                for r in rooms_rows:
                    rid = r.get("room_id", "")
                    area = _to_float(r.get("area_sqm"))
                    if not rid or area is None:
                        valid_inputs = False
                        break
                    rooms_area[rid] = float(area)
            except Exception:
                valid_inputs = False

        if valid_inputs:
            try:
                for r in graph_rows:
                    u = r.get("room_u", "")
                    v = r.get("room_v", "")
                    w = _to_float(r.get("door_width_m"))
                    if not u or not v or w is None:
                        valid_inputs = False
                        break
                    if u not in rooms_area or v not in rooms_area:
                        valid_inputs = False
                        break
                    key = frozenset({u, v})
                    if key in graph_edges:
                        valid_inputs = False
                        break
                    graph_edges[key] = float(w)
            except Exception:
                valid_inputs = False

        if valid_inputs:
            try:
                for r in comp_rows:
                    a = r.get("theme_a", "")
                    b = r.get("theme_b", "")
                    c = _to_float(r.get("compatibility"))
                    if not a or not b or c is None:
                        valid_inputs = False
                        break
                    comp_map[(a, b)] = float(c)
            except Exception:
                valid_inputs = False

    out_assign_path = workspace / "output" / "room_assignments.csv"
    out_adj_path = workspace / "output" / "adjacency_scores.csv"
    out_summary_path = workspace / "output" / "summary.json"
    out_notes_path = workspace / "output" / "meeting_notes.md"
    out_email_path = workspace / "output" / "email_to_curator.txt"

    assignments_rows = _load_csv_dicts(out_assign_path)
    adj_rows = _load_csv_dicts(out_adj_path)
    summary_obj = _load_json(out_summary_path)
    notes_text = _read_text(out_notes_path)
    email_text = _read_text(out_email_path)

    assignment_valid = False
    assignment_map: Dict[int, str] = {}
    if assignments_rows is not None:
        try:
            with out_assign_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        if header is not None and [h.strip() for h in header] == ["exhibit_id", "room_id"]:
            seen_ids: set = set()
            try:
                for r in assignments_rows:
                    eid = _to_int(r.get("exhibit_id"))
                    rid = r.get("room_id", "")
                    if eid is None or rid == "":
                        assignment_valid = False
                        break
                    if eid in seen_ids:
                        assignment_valid = False
                        break
                    seen_ids.add(eid)
                    assignment_map[eid] = rid
                else:
                    assignment_valid = True
            except Exception:
                assignment_valid = False

    if assignment_valid and valid_inputs:
        exhibit_ids_set = set(exhibits.keys())
        assigned_ids_set = set(assignment_map.keys())
        if assigned_ids_set == exhibit_ids_set:
            scores["all_exhibits_mapped_once"] = 1.0
        else:
            scores["all_exhibits_mapped_once"] = 0.0

        valid_room_ids = set(rooms_area.keys())
        room_ids_ok = True
        for eid, rid in assignment_map.items():
            if rid != "UNASSIGNED" and rid not in valid_room_ids:
                room_ids_ok = False
                break
        scores["room_ids_valid_and_unassigned_present"] = 1.0 if room_ids_ok else 0.0
        scores["room_assignments_file_valid"] = 1.0
    else:
        scores["room_assignments_file_valid"] = 0.0
        scores["all_exhibits_mapped_once"] = 0.0
        scores["room_ids_valid_and_unassigned_present"] = 0.0

    per_room_exhibits: Dict[str, List[int]] = {}
    sum_importance: Dict[str, float] = {}
    sum_area: Dict[str, float] = {}
    if assignment_valid and valid_inputs:
        for rid in rooms_area.keys():
            per_room_exhibits[rid] = []
            sum_importance[rid] = 0.0
            sum_area[rid] = 0.0
        for eid, rid in assignment_map.items():
            if rid in rooms_area:
                per_room_exhibits[rid].append(eid)
                sum_importance[rid] += exhibits[eid]["importance"]
                sum_area[rid] += exhibits[eid]["area"]

        capacity_ok = True
        for rid, cap in rooms_area.items():
            assigned_area = sum_area.get(rid, 0.0)
            if assigned_area - cap > 1e-6:
                capacity_ok = False
                break
        scores["capacity_constraints_satisfied"] = 1.0 if capacity_ok else 0.0

    expected_edge_scores: Dict[frozenset, Dict[str, float]] = {}
    if assignment_valid and valid_inputs:
        for key, door_w in graph_edges.items():
            rooms = list(key)
            if len(rooms) != 2:
                continue
            ru, rv = rooms[0], rooms[1]
            exhibits_u = per_room_exhibits.get(ru, [])
            exhibits_v = per_room_exhibits.get(rv, [])
            synergy = 0.0
            for i in exhibits_u:
                for j in exhibits_v:
                    imp_i = exhibits[i]["importance"]
                    imp_j = exhibits[j]["importance"]
                    theme_i = exhibits[i]["theme"]
                    theme_j = exhibits[j]["theme"]
                    c = _compat_lookup(comp_map, theme_i, theme_j)
                    synergy += imp_i * imp_j * c
            penalty_factor = max(0.0, 1.2 - float(door_w))
            s_imp_u = sum_importance.get(ru, 0.0)
            s_imp_v = sum_importance.get(rv, 0.0)
            penalty = penalty_factor * (s_imp_u + s_imp_v)
            net = synergy - penalty
            expected_edge_scores[key] = {
                "door_width_m": float(door_w),
                "sum_importance_u": s_imp_u,
                "sum_importance_v": s_imp_v,
                "synergy_score": synergy,
                "penalty": penalty,
                "net_score": net,
            }

    adj_valid_coverage = False
    adj_valid_values = False
    adj_edge_map: Dict[frozenset, Dict[str, Any]] = {}
    if adj_rows is not None:
        try:
            with out_adj_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        expected_header = [
            "room_u",
            "room_v",
            "door_width_m",
            "sum_importance_u",
            "sum_importance_v",
            "synergy_score",
            "penalty",
            "net_score",
        ]
        if header is not None and [h.strip() for h in header] == expected_header and valid_inputs and assignment_valid:
            coverage_ok = True
            seen_pairs: set = set()
            for r in adj_rows:
                ru = r.get("room_u", "")
                rv = r.get("room_v", "")
                key = frozenset({ru, rv})
                if not ru or not rv:
                    coverage_ok = False
                    break
                if key in seen_pairs:
                    coverage_ok = False
                    break
                seen_pairs.add(key)
                adj_edge_map[key] = r
            if set(adj_edge_map.keys()) == set(graph_edges.keys()):
                adj_valid_coverage = True
            else:
                adj_valid_coverage = False

            if adj_valid_coverage and expected_edge_scores:
                values_ok = True
                for key, expected in expected_edge_scores.items():
                    r = adj_edge_map.get(key)
                    if r is None:
                        values_ok = False
                        break
                    dw = _to_float(r.get("door_width_m"))
                    if dw is None or not _almost_equal(dw, expected["door_width_m"]):
                        values_ok = False
                        break
                    ru, rv = list(key)
                    ru_row = r.get("room_u", "")
                    rv_row = r.get("room_v", "")
                    if {ru_row, rv_row} != {ru, rv}:
                        values_ok = False
                        break
                    exp_su = expected["sum_importance_u"] if ru_row == ru else expected["sum_importance_v"]
                    exp_sv = expected["sum_importance_v"] if rv_row == rv else expected["sum_importance_u"]
                    su = _to_float(r.get("sum_importance_u"))
                    sv = _to_float(r.get("sum_importance_v"))
                    syn = _to_float(r.get("synergy_score"))
                    pen = _to_float(r.get("penalty"))
                    net = _to_float(r.get("net_score"))
                    if su is None or sv is None or syn is None or pen is None or net is None:
                        values_ok = False
                        break
                    if not (_almost_equal(su, exp_su) and _almost_equal(sv, exp_sv)):
                        values_ok = False
                        break
                    if not _almost_equal(syn, expected["synergy_score"]):
                        values_ok = False
                        break
                    if not _almost_equal(pen, expected["penalty"]):
                        values_ok = False
                        break
                    if not _almost_equal(net, expected["net_score"]):
                        values_ok = False
                        break
                adj_valid_values = 1.0 if values_ok else 0.0
        else:
            adj_valid_coverage = False
            adj_valid_values = False

    scores["adjacency_scores_coverage"] = 1.0 if adj_valid_coverage else 0.0
    scores["adjacency_scores_values_correct"] = adj_valid_values if isinstance(adj_valid_values, float) else 0.0

    expected_total_synergy = None
    expected_total_penalty = None
    expected_total_net = None
    if expected_edge_scores:
        expected_total_synergy = sum(v["synergy_score"] for v in expected_edge_scores.values())
        expected_total_penalty = sum(v["penalty"] for v in expected_edge_scores.values())
        expected_total_net = sum(v["net_score"] for v in expected_edge_scores.values())

    summary_totals_ok = False
    summary_rooms_ok = False
    summary_unassigned_ok = False
    if isinstance(summary_obj, dict) and valid_inputs and assignment_valid and expected_total_synergy is not None:
        t_syn = summary_obj.get("total_synergy_score")
        t_pen = summary_obj.get("total_penalty")
        t_net = summary_obj.get("total_net_score")
        if (
            isinstance(t_syn, (int, float))
            and isinstance(t_pen, (int, float))
            and isinstance(t_net, (int, float))
            and _almost_equal(float(t_syn), expected_total_synergy)
            and _almost_equal(float(t_pen), expected_total_penalty)
            and _almost_equal(float(t_net), expected_total_net)
        ):
            summary_totals_ok = True

        rooms_list = summary_obj.get("rooms")
        if isinstance(rooms_list, list):
            room_ids_in_summary = set()
            rooms_ok = True
            for item in rooms_list:
                if not isinstance(item, dict):
                    rooms_ok = False
                    break
                rid = item.get("room_id")
                area = item.get("area_sqm")
                assigned_area = item.get("assigned_area_sqm")
                util = item.get("utilization_ratio")
                ex_count = item.get("exhibit_count")
                if not isinstance(rid, str) or rid not in rooms_area:
                    rooms_ok = False
                    break
                room_ids_in_summary.add(rid)
                if not isinstance(area, (int, float)) or not _almost_equal(float(area), rooms_area[rid]):
                    rooms_ok = False
                    break
                exp_assigned_area = sum(exhibits[eid]["area"] for eid in per_room_exhibits.get(rid, []))
                if not isinstance(assigned_area, (int, float)) or not _almost_equal(float(assigned_area), exp_assigned_area):
                    rooms_ok = False
                    break
                exp_util = 0.0 if rooms_area[rid] == 0 else exp_assigned_area / rooms_area[rid]
                if not isinstance(util, (int, float)) or not _almost_equal(float(util), exp_util):
                    rooms_ok = False
                    break
                if not isinstance(ex_count, int) and not (isinstance(ex_count, float) and ex_count.is_integer()):
                    rooms_ok = False
                    break
                if int(ex_count) != len(per_room_exhibits.get(rid, [])):
                    rooms_ok = False
                    break
            if rooms_ok and room_ids_in_summary == set(rooms_area.keys()):
                summary_rooms_ok = True

        unassigned_list = summary_obj.get("unassigned_exhibits")
        if isinstance(unassigned_list, list):
            try:
                unassigned_from_summary = set(int(x) for x in unassigned_list)
                unassigned_from_assign = set(eid for eid, rid in assignment_map.items() if rid == "UNASSIGNED")
                if unassigned_from_summary == unassigned_from_assign:
                    summary_unassigned_ok = True
            except Exception:
                summary_unassigned_ok = False

    scores["summary_totals_correct"] = 1.0 if summary_totals_ok else 0.0
    scores["summary_rooms_section_correct"] = 1.0 if summary_rooms_ok else 0.0
    scores["summary_unassigned_correct"] = 1.0 if summary_unassigned_ok else 0.0

    cross_ok = False
    if adj_rows is not None and adj_valid_coverage and isinstance(summary_obj, dict):
        try:
            sum_syn_from_adj = 0.0
            sum_pen_from_adj = 0.0
            sum_net_from_adj = 0.0
            for r in adj_rows or []:
                syn = _to_float(r.get("synergy_score"))
                pen = _to_float(r.get("penalty"))
                net = _to_float(r.get("net_score"))
                if syn is None or pen is None or net is None:
                    raise ValueError("bad floats")
                sum_syn_from_adj += syn
                sum_pen_from_adj += pen
                sum_net_from_adj += net
            t_syn = summary_obj.get("total_synergy_score")
            t_pen = summary_obj.get("total_penalty")
            t_net = summary_obj.get("total_net_score")
            if (
                isinstance(t_syn, (int, float))
                and isinstance(t_pen, (int, float))
                and isinstance(t_net, (int, float))
                and _almost_equal(sum_syn_from_adj, float(t_syn))
                and _almost_equal(sum_pen_from_adj, float(t_pen))
                and _almost_equal(sum_net_from_adj, float(t_net))
            ):
                cross_ok = True
        except Exception:
            cross_ok = False
    scores["cross_output_totals_consistent"] = 1.0 if cross_ok else 0.0

    notes_ok = False
    if isinstance(notes_text, str) and isinstance(summary_obj, dict):
        sections = _parse_meeting_notes_sections(notes_text)
        have_sections = all(sec in sections for sec in ["context", "approach", "key constraints checked", "action items for studio review", "open questions"])
        constraints_ok = False
        if "key constraints checked" in sections:
            start, end = sections["key constraints checked"]
            sect_text = "\n".join(notes_text.splitlines()[start:end])
            constraints_ok = ("capacity" in sect_text.lower()) and ("scoring" in sect_text.lower())
        bullets_ok = False
        if "action items for studio review" in sections:
            start, end = sections["action items for studio review"]
            bullet_count = _count_bullets_in_section(notes_text, start, end)
            bullets_ok = bullet_count >= 3
        totals_ref_ok = False
        if isinstance(summary_obj.get("total_synergy_score"), (int, float)) and isinstance(summary_obj.get("total_penalty"), (int, float)) and isinstance(summary_obj.get("total_net_score"), (int, float)):
            nums = _extract_numbers(notes_text)
            def _has_close(val: float) -> bool:
                for n in nums:
                    if abs(n - val) <= 0.01:
                        return True
                if f"{val:.2f}" in notes_text:
                    return True
                return False
            t_syn = float(summary_obj.get("total_synergy_score"))
            t_pen = float(summary_obj.get("total_penalty"))
            t_net = float(summary_obj.get("total_net_score"))
            if _has_close(t_syn) and _has_close(t_pen) and _has_close(t_net):
                totals_ref_ok = True
        notes_ok = have_sections and constraints_ok and bullets_ok and totals_ref_ok
    scores["meeting_notes_structure_and_totals_reference"] = 1.0 if notes_ok else 0.0

    email_ok = False
    if isinstance(email_text, str) and isinstance(summary_obj, dict):
        lines = email_text.splitlines()
        first_nonempty_idx = None
        for i, ln in enumerate(lines):
            if ln.strip():
                first_nonempty_idx = i
                break
        subject_ok = False
        if first_nonempty_idx is not None and lines[first_nonempty_idx].startswith("Subject: "):
            subject_ok = True
        greeting_ok = any(re.match(r'^\s*(Dear|Hello|Hi)\b', ln) for ln in lines)
        paragraphs: List[str] = []
        curr: List[str] = []
        for ln in lines:
            if not ln.strip():
                if curr:
                    paragraphs.append("\n".join(curr).strip())
                    curr = []
                continue
            curr.append(ln)
        if curr:
            paragraphs.append("\n".join(curr).strip())
        bullet_para_pattern = re.compile(r'^\s*[-*]\s+')
        non_bullet_paras = [p for p in paragraphs if not all(bullet_para_pattern.match(l) for l in p.splitlines())]
        two_paras_ok = len(non_bullet_paras) >= 2
        metrics_ok = False
        util_ok = False
        if two_paras_ok:
            second_para = non_bullet_paras[1]
            nums = _extract_numbers(second_para)
            t_syn = summary_obj.get("total_synergy_score")
            t_pen = summary_obj.get("total_penalty")
            t_net = summary_obj.get("total_net_score")
            if isinstance(t_syn, (int, float)) and isinstance(t_pen, (int, float)) and isinstance(t_net, (int, float)):
                targets = [float(t_syn), float(t_pen), float(t_net)]
                matches = 0
                for target in targets:
                    for n in nums:
                        if abs(n - target) <= 0.01:
                            matches += 1
                            break
                metrics_ok = matches >= 2
            util_ok = ("utilization" in second_para.lower())
        attachments = {
            "output/room_assignments.csv",
            "output/adjacency_scores.csv",
            "output/summary.json",
            "output/meeting_notes.md",
            "output/email_to_curator.txt",
        }
        bullets_present: set = set()
        for ln in lines:
            if re.match(r'^\s*[-*]\s+', ln):
                for p in attachments:
                    if p in ln:
                        bullets_present.add(p)
        attachments_ok = bullets_present == attachments
        closing_idx = None
        for i, ln in enumerate(lines):
            if re.match(r'^\s*(Best|Regards|Sincerely|Thank you|Many thanks)\s*,\s*$', ln):
                closing_idx = i
                break
        closing_ok = False
        signature_ok = False
        if closing_idx is not None:
            closing_ok = True
            if closing_idx + 1 < len(lines) and lines[closing_idx + 1].strip():
                signature_ok = True
        email_ok = all([subject_ok, greeting_ok, two_paras_ok, metrics_ok, util_ok, attachments_ok, closing_ok, signature_ok])
    scores["email_structure_content_and_attachments"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()