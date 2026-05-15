import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional


REFERENCE_DATE_STR = "2026-04-16"
REFERENCE_DATE = date(2026, 4, 16)


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists():
            return None, None
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        if not path.exists():
            return None
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                items.append(json.loads(s))
        return items
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 0.01) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def _round2(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        return round(float(x), 2)
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        return lines
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    s = s.lower()
    s = s.replace("\u2019", "'").replace("\u2014", "-").replace("\u2013", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_paragraphs(text: str) -> List[str]:
    paras = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paras.append("\n".join(current).strip())
                current = []
        else:
            current.append(line.rstrip("\n"))
    if current:
        paras.append("\n".join(current).strip())
    return paras


def _compute_expected(workspace: Path) -> Optional[Dict]:
    roster_path = workspace / "input" / "pilot_roster.csv"
    tests_path = workspace / "input" / "test_results.jsonl"
    header, roster_rows = _safe_read_csv(roster_path)
    test_items = _safe_read_jsonl(tests_path)
    if header is None or roster_rows is None or test_items is None:
        return None

    roster_by_id: Dict[str, Dict] = {}
    for r in roster_rows:
        pid = r.get("project_id", "").strip()
        if not pid:
            continue
        roster_by_id[pid] = {
            "project_id": pid,
            "project_name": r.get("project_name", "").strip(),
            "lead_name": r.get("lead_name", "").strip(),
            "lead_email": r.get("lead_email", "").strip(),
            "next_milestone_date": r.get("next_milestone_date", "").strip(),
            "last_checkin_date": r.get("last_checkin_date", "").strip(),
        }

    agg: Dict[str, Dict[str, float]] = {}
    latencies: Dict[str, List[float]] = {}
    for item in test_items:
        try:
            pid = str(item["project_id"])
            tp = int(item["true_positives"])
            fp = int(item["false_positives"])
            fn = int(item["false_negatives"])
            lat = float(item["avg_latency_ms"])
        except Exception:
            return None
        a = agg.setdefault(pid, {"tp": 0, "fp": 0, "fn": 0})
        a["tp"] += tp
        a["fp"] += fp
        a["fn"] += fn
        latencies.setdefault(pid, []).append(lat)

    per_project: Dict[str, Dict] = {}
    for pid, info in roster_by_id.items():
        sums = agg.get(pid, {"tp": 0, "fp": 0, "fn": 0})
        total_tp = int(sums.get("tp", 0))
        total_fp = int(sums.get("fp", 0))
        total_fn = int(sums.get("fn", 0))
        denom_p = total_tp + total_fp
        denom_r = total_tp + total_fn
        precision = float(total_tp) / denom_p if denom_p > 0 else 0.0
        recall = float(total_tp) / denom_r if denom_r > 0 else 0.0
        if (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0
        lats = latencies.get(pid, [])
        avg_latency = sum(lats) / len(lats) if len(lats) > 0 else 0.0
        precision_r = _round2(precision)
        recall_r = _round2(recall)
        f1_r = _round2(f1)
        avg_latency_r = _round2(avg_latency)

        nms_str = info["next_milestone_date"]
        lci_str = info["last_checkin_date"]
        nms = _parse_date(nms_str)
        lci = _parse_date(lci_str)
        if nms is None or lci is None:
            return None
        days_until_milestone = (nms - REFERENCE_DATE).days
        days_since_checkin = (REFERENCE_DATE - lci).days
        follow_up_needed = "yes" if (days_until_milestone <= 10 or days_since_checkin > 14) else "no"

        per_project[pid] = {
            "project_id": pid,
            "project_name": info["project_name"],
            "lead_name": info["lead_name"],
            "lead_email": info["lead_email"],
            "next_milestone_date": nms_str,
            "days_until_milestone": days_until_milestone,
            "last_checkin_date": lci_str,
            "days_since_checkin": days_since_checkin,
            "total_tp": total_tp,
            "total_fp": total_fp,
            "total_fn": total_fn,
            "precision": precision_r,
            "recall": recall_r,
            "f1": f1_r,
            "avg_latency_ms": avg_latency_r,
            "follow_up_needed": follow_up_needed,
        }

    projects_list = list(per_project.values())
    if not projects_list:
        return None
    avg_precision = _round2(sum(p["precision"] for p in projects_list) / len(projects_list))
    avg_recall = _round2(sum(p["recall"] for p in projects_list) / len(projects_list))
    avg_f1 = _round2(sum(p["f1"] for p in projects_list) / len(projects_list))
    avg_latency_ms = _round2(sum(p["avg_latency_ms"] for p in projects_list) / len(projects_list))
    total_projects = len(projects_list)
    follow_ids = sorted([p["project_id"] for p in projects_list if p["follow_up_needed"] == "yes"])
    projects_needing_follow_up = len(follow_ids)

    expected = {
        "per_project": per_project,
        "rollup": {
            "average_precision": avg_precision,
            "average_recall": avg_recall,
            "average_f1": avg_f1,
            "average_latency_ms": avg_latency_ms,
            "total_projects": total_projects,
            "projects_needing_follow_up": projects_needing_follow_up,
            "follow_up_project_ids": follow_ids,
        },
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "followups_body_quality": 0.0,
        "followups_header_lines": 0.0,
        "followups_presence": 0.0,
        "rollup_correctness": 0.0,
        "rollup_structure": 0.0,
        "summary_dates_and_followup_accuracy": 0.0,
        "summary_header": 0.0,
        "summary_metrics_accuracy": 0.0,
        "summary_row_coverage": 0.0,
    }

    expected = _compute_expected(workspace)
    if expected is None:
        return scores

    expected_columns = [
        "project_id",
        "project_name",
        "lead_name",
        "lead_email",
        "next_milestone_date",
        "days_until_milestone",
        "last_checkin_date",
        "days_since_checkin",
        "total_tp",
        "total_fp",
        "total_fn",
        "precision",
        "recall",
        "f1",
        "avg_latency_ms",
        "follow_up_needed",
    ]

    summary_path = workspace / "output" / "pilot_status_summary.csv"
    header, rows = _safe_read_csv(summary_path)
    summary_by_id: Dict[str, Dict[str, str]] = {}
    if header is not None and rows is not None:
        if header == expected_columns:
            scores["summary_header"] = 1.0
        else:
            scores["summary_header"] = 0.0

        project_ids_expected = set(expected["per_project"].keys())
        seen_ids = []
        for r in rows:
            pid = (r.get("project_id") or "").strip()
            if pid:
                seen_ids.append(pid)
                summary_by_id[pid] = r
        unique_seen = set(seen_ids)
        if len(rows) == len(project_ids_expected) and unique_seen == project_ids_expected:
            scores["summary_row_coverage"] = 1.0
        else:
            scores["summary_row_coverage"] = 0.0

        if project_ids_expected:
            metrics_correct = 0
            dates_correct = 0
            for pid in project_ids_expected:
                exp = expected["per_project"][pid]
                row = summary_by_id.get(pid)
                if row is None:
                    continue

                try:
                    r_tp = _to_int(row.get("total_tp", ""))
                    r_fp = _to_int(row.get("total_fp", ""))
                    r_fn = _to_int(row.get("total_fn", ""))
                    r_prec = _to_float(row.get("precision", ""))
                    r_rec = _to_float(row.get("recall", ""))
                    r_f1 = _to_float(row.get("f1", ""))
                    r_lat = _to_float(row.get("avg_latency_ms", ""))
                except Exception:
                    r_tp = r_fp = r_fn = None
                    r_prec = r_rec = r_f1 = r_lat = None

                totals_ok = (
                    r_tp == exp["total_tp"] and
                    r_fp == exp["total_fp"] and
                    r_fn == exp["total_fn"]
                )

                precision_ok = r_prec is not None and _round2(r_prec) == exp["precision"]
                recall_ok = r_rec is not None and _round2(r_rec) == exp["recall"]
                f1_ok = r_f1 is not None and _round2(r_f1) == exp["f1"]
                lat_ok = r_lat is not None and _round2(r_lat) == exp["avg_latency_ms"]

                if totals_ok and precision_ok and recall_ok and f1_ok and lat_ok:
                    metrics_correct += 1

                nms_ok = (row.get("next_milestone_date", "").strip() == exp["next_milestone_date"])
                lci_ok = (row.get("last_checkin_date", "").strip() == exp["last_checkin_date"])
                dim = _to_int(row.get("days_until_milestone", ""))
                dsc = _to_int(row.get("days_since_checkin", ""))
                dim_ok = dim == exp["days_until_milestone"]
                dsc_ok = dsc == exp["days_since_checkin"]
                fun_ok = (row.get("follow_up_needed", "").strip().lower() == exp["follow_up_needed"])
                if nms_ok and lci_ok and dim_ok and dsc_ok and fun_ok:
                    dates_correct += 1

            scores["summary_metrics_accuracy"] = metrics_correct / max(1, len(project_ids_expected))
            scores["summary_dates_and_followup_accuracy"] = dates_correct / max(1, len(project_ids_expected))

    rollup_path = workspace / "output" / "rollup.json"
    rollup_data = None
    if rollup_path.exists():
        try:
            with rollup_path.open("r", encoding="utf-8") as f:
                rollup_data = json.load(f)
        except Exception:
            rollup_data = None

    if rollup_data is not None:
        keys_needed = {
            "average_precision",
            "average_recall",
            "average_f1",
            "average_latency_ms",
            "total_projects",
            "projects_needing_follow_up",
            "follow_up_project_ids",
        }
        if keys_needed.issubset(set(rollup_data.keys())):
            scores["rollup_structure"] = 1.0
        else:
            scores["rollup_structure"] = 0.0

        exp_roll = expected["rollup"]
        try:
            ap = float(rollup_data.get("average_precision"))
            ar = float(rollup_data.get("average_recall"))
            af = float(rollup_data.get("average_f1"))
            al = float(rollup_data.get("average_latency_ms"))
            tp = int(rollup_data.get("total_projects"))
            pf = int(rollup_data.get("projects_needing_follow_up"))
            fids = rollup_data.get("follow_up_project_ids")
            if isinstance(fids, list):
                fids_set = set(str(x) for x in fids)
            else:
                fids_set = set()
            ok = (
                _float_equal(_round2(ap), exp_roll["average_precision"]) and
                _float_equal(_round2(ar), exp_roll["average_recall"]) and
                _float_equal(_round2(af), exp_roll["average_f1"]) and
                _float_equal(_round2(al), exp_roll["average_latency_ms"]) and
                tp == exp_roll["total_projects"] and
                pf == exp_roll["projects_needing_follow_up"] and
                fids_set == set(exp_roll["follow_up_project_ids"])
            )
            scores["rollup_correctness"] = 1.0 if ok else 0.0
        except Exception:
            scores["rollup_correctness"] = 0.0

    follow_ids = [pid for pid, p in expected["per_project"].items() if p["follow_up_needed"] == "yes"]
    follow_dir = workspace / "output" / "followups"

    if follow_ids:
        present_count = 0
        header_ok_count = 0
        body_ok_count = 0

        for pid in follow_ids:
            proj = expected["per_project"][pid]
            fpath = follow_dir / f"{pid}_followup.txt"
            lines = _read_text_lines(fpath)
            if lines is None:
                continue
            present_count += 1

            expected_to = f"To: {proj['lead_email']}"
            expected_subject = f"Subject: Follow-up: {proj['project_name']} — milestone {proj['next_milestone_date']}"
            first_line_ok = len(lines) >= 1 and lines[0].strip() == expected_to
            second_line_ok = len(lines) >= 2 and lines[1].strip() == expected_subject
            if first_line_ok and second_line_ok:
                header_ok_count += 1

            body_text = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
            paras = _split_paragraphs(body_text)
            paras_count_ok = 2 <= len(paras) <= 3

            norm_body = _normalize_text(body_text)
            a_ok = ("checking in" in norm_body) and ("officer" in norm_body) and ("mathematician" in norm_body)

            p_str = f"{proj['precision']:.2f}"
            r_str = f"{proj['recall']:.2f}"
            f1_str = f"{proj['f1']:.2f}"
            lat_str = f"{proj['avg_latency_ms']:.2f}"
            b_ok = (p_str in body_text) and (r_str in body_text) and (f1_str in body_text) and (lat_str in body_text)

            c_date_ok = proj["next_milestone_date"] in body_text
            dim_str = str(proj["days_until_milestone"])
            dsc_str = str(proj["days_since_checkin"])
            dim_found = re.search(rf"\b{re.escape(dim_str)}\b", body_text) is not None
            dsc_found = re.search(rf"\b{re.escape(dsc_str)}\b", body_text) is not None
            c_days_ok = (dim_found or dsc_found)

            status_ok = ("status" in norm_body)
            resource_ok = ("resource" in norm_body)

            if paras_count_ok and a_ok and b_ok and c_date_ok and c_days_ok and status_ok and resource_ok:
                body_ok_count += 1

        scores["followups_presence"] = present_count / max(1, len(follow_ids))
        scores["followups_header_lines"] = header_ok_count / max(1, len(follow_ids))
        scores["followups_body_quality"] = body_ok_count / max(1, len(follow_ids))
    else:
        scores["followups_presence"] = 1.0
        scores["followups_header_lines"] = 1.0
        scores["followups_body_quality"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()