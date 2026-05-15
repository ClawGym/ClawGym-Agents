import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        # Basic header sanity: ensure all keys are present per row
        headers = reader.fieldnames or []
        for r in rows:
            if any(k not in r for k in headers):
                return None
        return rows
    except Exception:
        return None


def _parse_iso_z(ts: str) -> Optional[datetime]:
    try:
        # Expect YYYY-MM-DDTHH:MM:SSZ
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _format_float_2(x: float) -> str:
    return f"{x:.2f}"


def _load_all_emotion_logs(workspace: Path) -> Optional[List[Dict[str, str]]]:
    input_dir = workspace / "input"
    if not input_dir.exists():
        return None
    rows_all: List[Dict[str, str]] = []
    for p in sorted(input_dir.glob("emotion_logs_*.csv")):
        rows = _read_csv_rows(p)
        if rows is None:
            return None
        rows_all.extend(rows)
    return rows_all if rows_all else None


def _compute_processed_date_and_rows(rows: List[Dict[str, str]]) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    # Determine the maximum date among all timestamps, then select only those rows matching that date.
    max_dt: Optional[datetime] = None
    for r in rows:
        ts = r.get("timestamp", "")
        dt = _parse_iso_z(ts)
        if dt is None:
            return None
        if max_dt is None or dt > max_dt:
            max_dt = dt
    if max_dt is None:
        return None
    processed_date = max_dt.strftime("%Y-%m-%d")
    # Filter rows by processed_date
    processed_rows: List[Dict[str, str]] = []
    for r in rows:
        dt = _parse_iso_z(r.get("timestamp", ""))
        if dt is None:
            return None
        if dt.strftime("%Y-%m-%d") == processed_date:
            processed_rows.append(r)
    return processed_date, processed_rows


def _load_ads_metadata(workspace: Path) -> Optional[Dict[str, Dict[str, str]]]:
    meta_path = workspace / "input" / "ads_metadata.csv"
    rows = _read_csv_rows(meta_path)
    if rows is None:
        return None
    meta: Dict[str, Dict[str, str]] = {}
    for r in rows:
        ad_id = r.get("ad_id")
        brand = r.get("brand")
        ad_title = r.get("ad_title")
        if ad_id is None or brand is None or ad_title is None:
            return None
        meta[ad_id] = {"brand": brand, "ad_title": ad_title}
    return meta


def _aggregate_by_ad(processed_rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, float]]]:
    agg: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    for r in processed_rows:
        ad_id = r.get("ad_id")
        try:
            val = float(r.get("valence", ""))
            aro = float(r.get("arousal", ""))
        except Exception:
            return None
        if ad_id is None:
            return None
        if ad_id not in agg:
            agg[ad_id] = {"sum_valence": 0.0, "sum_arousal": 0.0}
            counts[ad_id] = 0
        agg[ad_id]["sum_valence"] += val
        agg[ad_id]["sum_arousal"] += aro
        counts[ad_id] += 1
    # finalize means
    for ad_id in agg.keys():
        n = counts[ad_id]
        if n == 0:
            return None
        agg[ad_id]["n_responses"] = float(n)
        agg[ad_id]["mean_valence"] = agg[ad_id]["sum_valence"] / n
        agg[ad_id]["mean_arousal"] = agg[ad_id]["sum_arousal"] / n
    # convert counts to int stored separately
    results: Dict[str, Dict[str, float]] = {}
    for ad_id, stats in agg.items():
        results[ad_id] = {
            "n_responses": int(stats["n_responses"]),
            "mean_valence": stats["mean_valence"],
            "mean_arousal": stats["mean_arousal"],
        }
    return results


def _rank_ads(aggregates: Dict[str, Dict[str, float]]) -> List[str]:
    # Rank by mean_valence desc; tie-breaker: n_responses desc
    items = []
    for ad_id, stats in aggregates.items():
        items.append((ad_id, stats["mean_valence"], int(stats["n_responses"])))
    items.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return [ad_id for ad_id, _, _ in items]


def _safe_split_lines(text: str) -> List[str]:
    return text.splitlines()


def _single_nonempty_line(lines: List[str]) -> Optional[str]:
    nonempty = [ln for ln in lines if ln.strip() != ""]
    if len(nonempty) != 1:
        return None
    return nonempty[0]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_file_present_correct_name": 0.0,
        "csv_header_correct": 0.0,
        "csv_rows_rank_order_correct": 0.0,
        "csv_values_correct_and_rounded": 0.0,
        "summary_title_line_correct": 0.0,
        "summary_top3_section_correct": 0.0,
        "summary_brevity_3_to_5_sentences": 0.0,
        "state_updated_max_timestamp_correct": 0.0,
        "run_daily_sh_exists": 0.0,
        "cron_snippet_line_valid": 0.0,
    }

    # Load inputs and compute expected processed date and aggregates
    rows_all = _load_all_emotion_logs(workspace)
    ads_meta = _load_ads_metadata(workspace)
    expected_date: Optional[str] = None
    expected_aggregates: Optional[Dict[str, Dict[str, float]]] = None
    ranked_ad_ids: List[str] = []
    max_ts_str: Optional[str] = None

    if rows_all is not None and ads_meta is not None:
        proc = _compute_processed_date_and_rows(rows_all)
        if proc is not None:
            expected_date, processed_rows = proc
            aggregates = _aggregate_by_ad(processed_rows)
            if aggregates is not None:
                expected_aggregates = aggregates
                ranked_ad_ids = _rank_ads(aggregates)
                # compute max timestamp among processed rows
                max_dt = None
                for r in processed_rows:
                    dt = _parse_iso_z(r.get("timestamp", ""))
                    if dt is None:
                        max_dt = None
                        break
                    if max_dt is None or dt > max_dt:
                        max_dt = dt
                if max_dt is not None:
                    max_ts_str = max_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # CSV checks
    if expected_date is not None:
        expected_csv_path = workspace / "output" / f"daily_top_ads_{expected_date}.csv"
        if expected_csv_path.exists() and expected_csv_path.is_file():
            scores["csv_file_present_correct_name"] = 1.0

            produced_rows = _read_csv_rows(expected_csv_path)
            if produced_rows is not None and len(produced_rows) > 0:
                # Check header
                try:
                    with expected_csv_path.open(encoding="utf-8") as f:
                        header_line = f.readline().strip("\n\r")
                    expected_header = "date,ad_id,brand,ad_title,n_responses,mean_valence,mean_arousal"
                    if header_line == expected_header:
                        scores["csv_header_correct"] = 1.0
                except Exception:
                    pass

                # Proceed with value checks if we have expected aggregates and metadata
                if expected_aggregates is not None and ads_meta is not None and ranked_ad_ids:
                    # Extract ad_ids from produced in order
                    produced_ad_ids = [r.get("ad_id", "") for r in produced_rows]
                    # Must include all processed ads in ranked order (top first)
                    # Expect exact match in length and order
                    if produced_ad_ids == ranked_ad_ids:
                        scores["csv_rows_rank_order_correct"] = 1.0

                    # Validate each row values
                    all_values_ok = True
                    for idx, r in enumerate(produced_rows):
                        ad_id = r.get("ad_id", "")
                        # date check
                        if r.get("date") != expected_date:
                            all_values_ok = False
                            break
                        # metadata join
                        meta = ads_meta.get(ad_id)
                        if not meta:
                            all_values_ok = False
                            break
                        if r.get("brand") != meta["brand"] or r.get("ad_title") != meta["ad_title"]:
                            all_values_ok = False
                            break
                        # n_responses
                        try:
                            n_expected = int(expected_aggregates[ad_id]["n_responses"])
                        except Exception:
                            all_values_ok = False
                            break
                        if r.get("n_responses") != str(n_expected):
                            all_values_ok = False
                            break
                        # means rounded to 2 decimals, verify exact textual formatting with two decimals
                        mv_expected = _format_float_2(expected_aggregates[ad_id]["mean_valence"])
                        ma_expected = _format_float_2(expected_aggregates[ad_id]["mean_arousal"])
                        mv_str = r.get("mean_valence", "")
                        ma_str = r.get("mean_arousal", "")
                        if mv_str != mv_expected or ma_str != ma_expected:
                            all_values_ok = False
                            break
                        # Also enforce two-decimal formatting
                        if not re.fullmatch(r"-?\d+\.\d{2}", mv_str or ""):
                            all_values_ok = False
                            break
                        if not re.fullmatch(r"-?\d+\.\d{2}", ma_str or ""):
                            all_values_ok = False
                            break
                    if all_values_ok:
                        scores["csv_values_correct_and_rounded"] = 1.0

    # Summary checks
    summary_path = workspace / "output" / "daily_summary_message.txt"
    summary_text = _read_text(summary_path)
    if summary_text is not None and expected_date is not None and expected_aggregates is not None and ads_meta is not None:
        lines = _safe_split_lines(summary_text)
        if len(lines) >= 1:
            expected_title = f"Daily Emotion Summary - {expected_date}"
            if lines[0].strip() == expected_title:
                scores["summary_title_line_correct"] = 1.0

        # Build expected top 3 lines
        ranked = _rank_ads(expected_aggregates)
        top3 = ranked[:3]
        expected_top3_lines = []
        for rank, ad_id in enumerate(top3, start=1):
            meta = ads_meta.get(ad_id, {})
            title = meta.get("ad_title", "")
            brand = meta.get("brand", "")
            mv = _format_float_2(expected_aggregates[ad_id]["mean_valence"])
            n = int(expected_aggregates[ad_id]["n_responses"])
            line = f"{rank}) {title} ({brand}) - mean_valence={mv}; n={n}"
            expected_top3_lines.append(line)

        # Find "Top 3 ads by mean valence:" section
        section_idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == "Top 3 ads by mean valence:":
                section_idx = i
                break
        if section_idx is not None:
            # Extract next three non-empty lines after the header
            following = []
            j = section_idx + 1
            while j < len(lines) and len(following) < 3:
                if lines[j].strip() != "":
                    following.append(lines[j].strip())
                j += 1
            if following == expected_top3_lines:
                # Also ensure there isn't a 4) line immediately following (ignoring blank lines)
                k = j
                extra_numbered = False
                while k < len(lines):
                    candidate = lines[k].strip()
                    if candidate == "":
                        k += 1
                        continue
                    if re.match(r"^\d+\)\s", candidate):
                        extra_numbered = True
                    break
                if not extra_numbered:
                    scores["summary_top3_section_correct"] = 1.0

        # Check brevity: 3–5 sentences in body before the top-3 section
        if len(lines) > 0:
            body_lines = []
            # lines after title up to (but not including) top-3 header
            start_idx = 1
            end_idx = section_idx if section_idx is not None else len(lines)
            for i in range(start_idx, end_idx):
                ln = lines[i].strip()
                if ln != "":
                    body_lines.append(ln)
            body_text = " ".join(body_lines)
            # Count sentences by '.', '!' or '?' terminators
            # We will count occurrences of sentence endings.
            sentence_endings = re.findall(r"[\.!?](?:\s|$)", body_text)
            count = len(sentence_endings)
            if 3 <= count <= 5:
                scores["summary_brevity_3_to_5_sentences"] = 1.0

    # State update check
    state_path = workspace / "state" / "last_run_state.json"
    state_json = _read_json(state_path)
    if state_json is not None and max_ts_str is not None:
        if isinstance(state_json, dict):
            lpt = state_json.get("last_processed_timestamp")
            if isinstance(lpt, str) and lpt == max_ts_str:
                scores["state_updated_max_timestamp_correct"] = 1.0

    # run_daily.sh existence
    run_sh = workspace / "run_daily.sh"
    if run_sh.exists() and run_sh.is_file():
        content = _read_text(run_sh) or ""
        if content.strip() != "":
            scores["run_daily_sh_exists"] = 1.0

    # cron_snippet.txt validation
    cron_path = workspace / "output" / "cron_snippet.txt"
    cron_text = _read_text(cron_path)
    if cron_text is not None:
        lines = _safe_split_lines(cron_text)
        line = _single_nonempty_line(lines)
        if line is not None:
            # Expected pattern: 0 19 * * * cd <abs-path> && bash run_daily.sh >> output/cron.log 2>&1
            ws_abs = str(workspace.resolve())
            pattern = rf"^0 19 \* \* \* cd {re.escape(ws_abs)} && bash run_daily\.sh >> output/cron\.log 2>&1$"
            if re.match(pattern, line.strip()):
                scores["cron_snippet_line_valid"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()