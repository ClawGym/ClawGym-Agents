import sys
import json
import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or len(reader.fieldnames) == 0:
                return None
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_csv_file(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        body = rows[1:]
        return header, body
    except Exception:
        return None, None


def _parse_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, data)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        while stack and indent < stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if ":" in line.strip():
            if line.strip().endswith(":"):
                key = line.strip()[:-1].strip()
                current[key] = {}
                stack.append((indent + 2, current[key]))
            else:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val_clean: Any = val[1:-1]
                else:
                    try:
                        if "." in val:
                            val_clean = float(val)
                        else:
                            val_clean = int(val)
                    except Exception:
                        val_clean = val
                current[key] = val_clean
    return data


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    s = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _pearson_corr(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n != len(y) or n < 2:
        return float("nan")
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    sxy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    sx2 = sum((xi - mean_x) ** 2 for xi in x)
    sy2 = sum((yi - mean_y) ** 2 for yi in y)
    denom = math.sqrt(sx2) * math.sqrt(sy2)
    if denom == 0:
        return float("nan")
    return sxy / denom


def _format4(x: float) -> str:
    return f"{x:.4f}"


def _compute_expected_metrics(ml_rows: List[Dict[str, str]], fc_rows: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    try:
        spreads: List[float] = []
        depths: List[float] = []
        for r in ml_rows:
            spreads.append(float(r["bid_ask_spread"]))
            depths.append(float(r["depth"]))
        total_rows = len(ml_rows)
        if total_rows == 0:
            return None
        mean_spread = sum(spreads) / total_rows
        median_spread = _median(spreads)
        mean_depth = sum(depths) / total_rows

        coverage_by_date: Dict[str, float] = {}
        for r in fc_rows:
            coverage_by_date[r["date"]] = float(r["coverage_ratio"])
        jx: List[float] = []
        jy: List[float] = []
        for r in ml_rows:
            d = r["date"]
            if d in coverage_by_date:
                jx.append(float(r["bid_ask_spread"]))
                jy.append(coverage_by_date[d])
        corr = _pearson_corr(jx, jy)

        per_market: Dict[str, Dict[str, List[float]]] = {}
        for r in ml_rows:
            m = r["market"]
            per_market.setdefault(m, {"s": [], "d": []})
            per_market[m]["s"].append(float(r["bid_ask_spread"]))
            per_market[m]["d"].append(float(r["depth"]))
        aggs: List[Tuple[str, float, float, int]] = []
        for m, vals in per_market.items():
            n = len(vals["s"])
            avg_s = sum(vals["s"]) / n if n else float("nan")
            avg_d = sum(vals["d"]) / n if n else float("nan")
            aggs.append((m, avg_s, avg_d, n))
        aggs.sort(key=lambda t: (-t[1], t[0]))
        return {
            "total_rows": total_rows,
            "mean_spread": mean_spread,
            "median_spread": median_spread,
            "mean_depth": mean_depth,
            "spread_coverage_corr": corr,
            "market_aggs": aggs,
        }
    except Exception:
        return None


def _find_section(text: str, heading: str, all_headings: List[str]) -> Optional[str]:
    lines = text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading:
            idx = i
            break
    if idx is None:
        return None
    next_idx = None
    for j in range(idx + 1, len(lines)):
        if lines[j].strip() in all_headings:
            next_idx = j
            break
    if next_idx is None:
        section_lines = lines[idx + 1 :]
    else:
        section_lines = lines[idx + 1 : next_idx]
    return "\n".join(section_lines).strip("\n")


def _bullet_lines(section_text: str) -> List[str]:
    return [ln.strip() for ln in section_text.splitlines() if ln.strip().startswith("- ")]


def _path_mentions(line: str, workspace: Path, target: Path) -> bool:
    try_opts = [
        str(target),  # absolute or given
        str(target.resolve()) if target.exists() else str(target),
        str(target.as_posix()),
        str(target.relative_to(workspace)) if str(target).startswith(str(workspace)) else str(target.name),
        str(target.name),
    ]
    return any(opt in line for opt in try_opts if opt)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "manifest_exists_and_structure": 0.0,
        "manifest_row_counts_and_sizes": 0.0,
        "summary_stats_exists_and_header": 0.0,
        "summary_stats_values_correct": 0.0,
        "market_aggregates_exists_and_header": 0.0,
        "market_aggregates_values_and_sorting": 0.0,
        "meeting_notes_headings_present": 0.0,
        "meeting_notes_environment_section_content": 0.0,
        "meeting_notes_key_metrics_section_content": 0.0,
        "meeting_notes_action_items_correct": 0.0,
    }

    # Parse config to locate output directories
    config_path = workspace / "input" / "config.yaml"
    config = _parse_yaml_config(config_path) if config_path.exists() else None
    metrics_dir = workspace / "output" / "metrics"
    logs_dir = workspace / "output" / "logs"
    reports_dir = workspace / "output" / "reports"
    if isinstance(config, dict) and isinstance(config.get("outputs"), dict):
        try:
            metrics_dir = workspace / str(config["outputs"].get("metrics_dir", "output/metrics"))
            logs_dir = workspace / str(config["outputs"].get("logs_dir", "output/logs"))
            reports_dir = workspace / str(config["outputs"].get("reports_dir", "output/reports"))
        except Exception:
            pass

    # Load inputs for expected computations
    ml_path = workspace / "input" / "market_liquidity.csv"
    fc_path = workspace / "input" / "fiscal_coverage.csv"
    ml_rows = _load_csv_rows(ml_path) if ml_path.exists() else None
    fc_rows = _load_csv_rows(fc_path) if fc_path.exists() else None
    expected = _compute_expected_metrics(ml_rows, fc_rows) if (ml_rows is not None and fc_rows is not None) else None

    # 1) Manifest checks
    manifest_path = logs_dir / "input_manifest.json"
    manifest = _load_json_safe(manifest_path) if manifest_path.exists() else None
    if isinstance(manifest, list):
        required_files = {"market_liquidity.csv", "fiscal_coverage.csv"}
        structure_ok = True
        if len(manifest) != 2:
            structure_ok = False
        present = set()
        for entry in manifest:
            if not isinstance(entry, dict):
                structure_ok = False
                break
            if not all(k in entry for k in ("file_path", "size_bytes", "row_count")):
                structure_ok = False
                break
            fp_str = str(entry.get("file_path"))
            name = Path(fp_str).name
            if name in required_files:
                present.add(name)
        if structure_ok and present == required_files:
            scores["manifest_exists_and_structure"] = 1.0

        if scores["manifest_exists_and_structure"] == 1.0:
            by_name: Dict[str, Dict[str, Any]] = {}
            for entry in manifest:
                name = Path(str(entry.get("file_path"))).name
                by_name[name] = entry
            ok = True
            # market_liquidity.csv
            if ml_path.exists():
                exp_rows = len(ml_rows) if ml_rows is not None else None
                exp_size = ml_path.stat().st_size
                e = by_name.get("market_liquidity.csv")
                if not isinstance(e, dict):
                    ok = False
                else:
                    if not isinstance(e.get("row_count"), int) or (exp_rows is not None and e.get("row_count") != exp_rows):
                        ok = False
                    if not isinstance(e.get("size_bytes"), int) or e.get("size_bytes") != exp_size:
                        ok = False
                    # file_path should reference input path
                    fp = str(e.get("file_path"))
                    if not (fp.endswith("input/market_liquidity.csv") or Path(fp).name == "market_liquidity.csv"):
                        ok = False
            else:
                ok = False
            # fiscal_coverage.csv
            if fc_path.exists():
                exp_rows = len(fc_rows) if fc_rows is not None else None
                exp_size = fc_path.stat().st_size
                e = by_name.get("fiscal_coverage.csv")
                if not isinstance(e, dict):
                    ok = False
                else:
                    if not isinstance(e.get("row_count"), int) or (exp_rows is not None and e.get("row_count") != exp_rows):
                        ok = False
                    if not isinstance(e.get("size_bytes"), int) or e.get("size_bytes") != exp_size:
                        ok = False
                    fp = str(e.get("file_path"))
                    if not (fp.endswith("input/fiscal_coverage.csv") or Path(fp).name == "fiscal_coverage.csv"):
                        ok = False
            else:
                ok = False

            if ok:
                scores["manifest_row_counts_and_sizes"] = 1.0

    # 2) Summary stats checks
    summary_path = metrics_dir / "summary_stats.csv"
    s_header, s_body = _parse_csv_file(summary_path) if summary_path.exists() else (None, None)
    if s_header is not None and s_body is not None:
        expected_header = ["total_rows", "mean_spread", "median_spread", "mean_depth", "spread_coverage_corr"]
        if s_header == expected_header and len(s_body) == 1:
            scores["summary_stats_exists_and_header"] = 1.0
        if scores["summary_stats_exists_and_header"] == 1.0 and expected is not None:
            row = s_body[0]
            try:
                total_rows_ok = row[0] == str(int(expected["total_rows"]))
                mean_spread_ok = row[1] == _format4(expected["mean_spread"])
                median_spread_ok = row[2] == _format4(expected["median_spread"])
                mean_depth_ok = row[3] == _format4(expected["mean_depth"])
                corr_ok = row[4] == _format4(expected["spread_coverage_corr"])
                if total_rows_ok and mean_spread_ok and median_spread_ok and mean_depth_ok and corr_ok:
                    scores["summary_stats_values_correct"] = 1.0
            except Exception:
                pass

    # 3) Market aggregates checks
    aggs_path = metrics_dir / "market_aggregates.csv"
    a_header, a_body = _parse_csv_file(aggs_path) if aggs_path.exists() else (None, None)
    if a_header is not None and a_body is not None:
        expected_a_header = ["market", "avg_spread", "avg_depth", "n_days"]
        if a_header == expected_a_header and len(a_body) > 0:
            scores["market_aggregates_exists_and_header"] = 1.0
        if scores["market_aggregates_exists_and_header"] == 1.0 and expected is not None:
            exp_aggs = expected["market_aggs"]
            exp_rows = [[m, _format4(avg_s), _format4(avg_d), str(n)] for (m, avg_s, avg_d, n) in exp_aggs]
            ok = True
            if len(a_body) != len(exp_rows):
                ok = False
            else:
                for got, exp in zip(a_body, exp_rows):
                    if got != exp:
                        ok = False
                        break
            if ok:
                scores["market_aggregates_values_and_sorting"] = 1.0

    # 4) Meeting notes checks
    notes_path = reports_dir / "meeting_notes.md"
    notes_text = _read_text_safe(notes_path) if notes_path.exists() else None
    headings = ["Environment:", "Key Metrics:", "Action Items:"]
    if notes_text is not None:
        if all(h in notes_text for h in headings):
            scores["meeting_notes_headings_present"] = 1.0

        # Environment section: Python version mention and bullet list of created output directories
        env_sec = _find_section(notes_text, "Environment:", headings)
        if env_sec is not None:
            env_ok = False
            # Python version mention heuristic
            if "Python" in env_sec and any(ch.isdigit() for ch in env_sec):
                env_ok = True
            # Bullet list includes created output directories
            blines = _bullet_lines(env_sec)
            dirs_ok = True
            for tdir in [metrics_dir, logs_dir, reports_dir]:
                found = False
                for ln in blines:
                    if _path_mentions(ln, workspace, tdir):
                        found = True
                        break
                if not found:
                    dirs_ok = False
                    break
            if env_ok and dirs_ok:
                scores["meeting_notes_environment_section_content"] = 1.0

        # Key Metrics section: include numeric values and list top 3 markets by avg_spread with values, in order
        km_sec = _find_section(notes_text, "Key Metrics:", headings)
        if km_sec is not None and expected is not None and scores["summary_stats_values_correct"] == 1.0:
            km_ok = True
            required_vals = [
                str(int(expected["total_rows"])),
                _format4(expected["mean_spread"]),
                _format4(expected["median_spread"]),
                _format4(expected["mean_depth"]),
                _format4(expected["spread_coverage_corr"]),
            ]
            for v in required_vals:
                if v not in km_sec:
                    km_ok = False
                    break
            if km_ok:
                top3 = [(m, _format4(avg_s)) for (m, avg_s, avg_d, n) in expected["market_aggs"][:3]]
                indices: List[int] = []
                for m, val in top3:
                    pos_m = km_sec.find(m)
                    pos_v = km_sec.find(val)
                    if pos_m == -1 or pos_v == -1:
                        km_ok = False
                        break
                    indices.append(min(pos_m, pos_v))
                if km_ok and not (len(indices) == 3 and indices[0] < indices[1] < indices[2]):
                    km_ok = False
            if km_ok:
                scores["meeting_notes_key_metrics_section_content"] = 1.0

        # Action Items section
        ai_sec = _find_section(notes_text, "Action Items:", headings)
        if ai_sec is not None and expected is not None:
            avg_spreads = [avg_s for (_, avg_s, _, _) in expected["market_aggs"]]
            med = _median(avg_spreads)
            targets = [(m, avg_s) for (m, avg_s, _, _) in expected["market_aggs"] if avg_s > med]
            blines = _bullet_lines(ai_sec)
            final_expected = "- Confirm date alignment in fiscal coverage vs. liquidity data."
            ai_ok = True
            # Ensure "Investigate" bullets for each target
            inv_lines = [ln for ln in blines if ln.startswith("- Investigate")]
            if len(inv_lines) != len(targets):
                ai_ok = False
            else:
                for m, avg_s in targets:
                    val = _format4(avg_s)
                    found = False
                    for ln in inv_lines:
                        if ln.startswith("- Investigate") and (m in ln) and (val in ln):
                            found = True
                            break
                    if not found:
                        ai_ok = False
                        break
            # Final bullet exact and last
            if not blines or blines[-1] != final_expected:
                ai_ok = False
            if ai_ok:
                scores["meeting_notes_action_items_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()