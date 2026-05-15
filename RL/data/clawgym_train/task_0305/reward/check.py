import json
import sys
import re
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import csv


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dict(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _compute_expected_stats(roster_path: Path, ballots_path: Path):
    roster_rows = _read_csv_dict(roster_path)
    ballots_rows = _read_csv_dict(ballots_path)
    if roster_rows is None or ballots_rows is None:
        return None

    # Build roster map
    roster_map = {}
    for row in roster_rows:
        cid = row.get("competitor_id")
        name = row.get("competitor_name")
        school = row.get("school")
        if cid is None or name is None or school is None:
            return None
        roster_map[cid] = {"competitor_name": name, "school": school}

    # Aggregate ballots
    stats = {}
    for row in ballots_rows:
        cid = row.get("competitor_id")
        result = row.get("result")
        sp_str = row.get("speaker_points")
        if cid is None or result is None or sp_str is None:
            return None
        try:
            sp = Decimal(str(sp_str))
        except Exception:
            return None
        s = stats.setdefault(cid, {"wins": 0, "losses": 0, "points": []})
        if result == "W":
            s["wins"] += 1
        elif result == "L":
            s["losses"] += 1
        else:
            return None
        s["points"].append(sp)

    # Build expected summary for all competitors in roster (one object per competitor)
    expected = []
    for cid, info in roster_map.items():
        s = stats.get(cid, {"wins": 0, "losses": 0, "points": []})
        pts = s["points"]
        if len(pts) == 0:
            avg = Decimal("0.00")
        else:
            avg_raw = sum(pts) / Decimal(len(pts))
            avg = avg_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected.append({
            "competitor_id": cid,
            "competitor_name": info["competitor_name"],
            "school": info["school"],
            "total_rounds": s["wins"] + s["losses"],
            "wins": s["wins"],
            "losses": s["losses"],
            "avg_speaker_points": float(avg),
        })

    # Sort by wins desc, then avg_speaker_points desc
    expected.sort(key=lambda x: (x["wins"], x["avg_speaker_points"]), reverse=True)
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    out_dir = workspace / "out"

    scores = {
        "before_log_captured_error": 0.0,
        "after_log_clean_run": 0.0,
        "after_log_reports_competitor_count": 0.0,
        "summary_json_exists_and_schema": 0.0,
        "summary_json_values_correct": 0.0,
        "summary_sorted_order_correct": 0.0,
        "summary_totals_consistent": 0.0,
        "html_references_local_chart_asset": 0.0,
        "html_offline_and_chart_code_present": 0.0,
        "chart_asset_present": 0.0,
    }

    # Paths
    before_log = out_dir / "before.log"
    after_log = out_dir / "after.log"
    summary_path = out_dir / "summary.json"
    index_html = out_dir / "index.html"
    chart_js = out_dir / "assets" / "chart.umd.min.js"

    # Check before.log contains an error/traceback
    before_text = _read_text(before_log)
    if before_text is not None and len(before_text.strip()) > 0:
        error_indicators = ["Traceback", "CalledProcessError", "ValueError", "Exception"]
        if any(ind in before_text for ind in error_indicators):
            scores["before_log_captured_error"] = 1.0

    # Check after.log clean run and competitor count line
    after_text = _read_text(after_log)
    if after_text is not None and len(after_text.strip()) > 0:
        # Clean run: no Traceback in after log
        if "Traceback" not in after_text:
            scores["after_log_clean_run"] = 1.0
        # Look for count line like "Generated N competitors" or "Processed N competitors"
        m = re.search(r'\b(Generated|Processed)\s+(\d+)\s+competitors\b', after_text, flags=re.IGNORECASE)
        if m:
            # If summary exists, verify the number matches
            js = _load_json(summary_path)
            if isinstance(js, list):
                try:
                    n = int(m.group(2))
                    if n == len(js):
                        scores["after_log_reports_competitor_count"] = 1.0
                except Exception:
                    pass

    # Validate summary.json schema and totals consistency
    summary = _load_json(summary_path)
    if isinstance(summary, list) and len(summary) > 0:
        required_keys = {
            "competitor_id": str,
            "competitor_name": str,
            "school": str,
            "total_rounds": int,
            "wins": int,
            "losses": int,
            "avg_speaker_points": (int, float),
        }
        schema_ok = True
        totals_ok = True
        for obj in summary:
            if not isinstance(obj, dict):
                schema_ok = False
                break
            # Check required fields presence and type
            for k, tp in required_keys.items():
                if k not in obj:
                    schema_ok = False
                    break
                # Type check: for numbers, ensure they are not strings
                if k in ("total_rounds", "wins", "losses"):
                    if not isinstance(obj[k], int):
                        schema_ok = False
                        break
                elif k == "avg_speaker_points":
                    if not isinstance(obj[k], (int, float)):
                        schema_ok = False
                        break
                else:
                    if not isinstance(obj[k], str):
                        schema_ok = False
                        break
            if not schema_ok:
                break
            # Totals consistency
            if obj.get("wins", 0) + obj.get("losses", 0) != obj.get("total_rounds", -1):
                totals_ok = False
        if schema_ok:
            scores["summary_json_exists_and_schema"] = 1.0
        if totals_ok:
            scores["summary_totals_consistent"] = 1.0

    # Compare values to recomputed expected and check sorting order
    roster_path = workspace / "input" / "roster.csv"
    ballots_path = workspace / "input" / "ballots.csv"
    expected = _compute_expected_stats(roster_path, ballots_path)
    if expected is not None and isinstance(summary, list):
        # Build maps for comparison
        expected_map = {e["competitor_id"]: e for e in expected}
        summary_map = {s.get("competitor_id"): s for s in summary if isinstance(s, dict) and "competitor_id" in s}
        # Check set equality of competitor_ids
        if set(expected_map.keys()) == set(summary_map.keys()):
            all_ok = True
            for cid, exp in expected_map.items():
                got = summary_map[cid]
                # Compare main fields
                if got.get("competitor_name") != exp["competitor_name"]:
                    all_ok = False
                    break
                if got.get("school") != exp["school"]:
                    all_ok = False
                    break
                if got.get("wins") != exp["wins"]:
                    all_ok = False
                    break
                if got.get("losses") != exp["losses"]:
                    all_ok = False
                    break
                if got.get("total_rounds") != exp["total_rounds"]:
                    all_ok = False
                    break
                # Compare avg within 0.005 tolerance
                gav = got.get("avg_speaker_points")
                try:
                    gavf = float(gav)
                except Exception:
                    all_ok = False
                    break
                if abs(gavf - float(exp["avg_speaker_points"])) > 0.005:
                    all_ok = False
                    break
            if all_ok:
                scores["summary_json_values_correct"] = 1.0

        # Check sorted by wins desc then avg desc according to the file's own values
        try:
            sorted_ok = True
            for i in range(1, len(summary)):
                prev = summary[i - 1]
                curr = summary[i]
                w_prev = prev.get("wins")
                w_curr = curr.get("wins")
                a_prev = prev.get("avg_speaker_points")
                a_curr = curr.get("avg_speaker_points")
                # Must be non-increasing on wins
                if w_prev < w_curr:
                    sorted_ok = False
                    break
                # If wins equal, avg must be non-increasing
                if w_prev == w_curr and a_prev < a_curr:
                    sorted_ok = False
                    break
            if sorted_ok and len(summary) > 0:
                scores["summary_sorted_order_correct"] = 1.0
        except Exception:
            pass

    # Validate index.html references local asset and contains chart code
    html_text = _read_text(index_html)
    if html_text is not None and len(html_text.strip()) > 0:
        # Reference to local Chart.js asset must be exactly ./assets/chart.umd.min.js
        if re.search(r'<script[^>]+src=["\']\./assets/chart\.umd\.min\.js["\']', html_text, flags=re.IGNORECASE):
            scores["html_references_local_chart_asset"] = 1.0
        # Must not include external CDN/http links, and contains canvas/chart code
        offline_ok = True
        if re.search(r'https?://', html_text, flags=re.IGNORECASE):
            offline_ok = False
        if "cdn.jsdelivr" in html_text or "unpkg.com" in html_text or "cdnjs.cloudflare" in html_text:
            offline_ok = False
        canvas_ok = bool(re.search(r'<canvas[^>]*id=["\']chart["\']', html_text, flags=re.IGNORECASE))
        chart_code_ok = ("new Chart" in html_text) and (re.search(r"type\s*:\s*['\"]bar['\"]", html_text) is not None)
        if offline_ok and canvas_ok and chart_code_ok:
            scores["html_offline_and_chart_code_present"] = 1.0

    # Validate Chart.js asset presence and basic plausibility
    try:
        if chart_js.exists() and chart_js.is_file():
            size = chart_js.stat().st_size
            # Size threshold to avoid empty or trivial file
            if size >= 10000:
                # Weak content check
                with chart_js.open("r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(2000)
                if "Chart" in content or "chart" in content:
                    scores["chart_asset_present"] = 1.0
    except Exception:
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()