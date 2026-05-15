import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import subprocess


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text, err = _safe_read_text(path)
        if err is not None or text is None:
            return None, err or "empty"
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None, "Missing header"
            rows = list(reader)
            return rows, header, None
    except Exception as e:
        return None, None, str(e)


def _run_cmd(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 127, "", str(e)


def _compute_aggregates(tips: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    country_counts: Dict[str, int] = {}
    country_sum: Dict[str, float] = {}
    city_counts: Dict[Tuple[str, str], int] = {}
    city_sum: Dict[Tuple[str, str], float] = {}

    for t in tips:
        if not isinstance(t, dict):
            continue
        country = t.get("country")
        city = t.get("city")
        score = t.get("score")
        if country is None or city is None:
            continue
        try:
            score_f = float(score)
        except Exception:
            continue
        country_counts[country] = country_counts.get(country, 0) + 1
        country_sum[country] = country_sum.get(country, 0.0) + score_f

        key = (country, city)
        city_counts[key] = city_counts.get(key, 0) + 1
        city_sum[key] = city_sum.get(key, 0.0) + score_f

    country_stats: Dict[str, Dict[str, Any]] = {}
    for c in country_counts:
        cnt = country_counts[c]
        avg = round(country_sum[c] / cnt, 2) if cnt > 0 else 0.0
        country_stats[c] = {"tips_count": cnt, "avg_score": avg}

    city_stats: List[Dict[str, Any]] = []
    for (c, city), cnt in city_counts.items():
        avg = round(city_sum[(c, city)] / cnt, 2) if cnt > 0 else 0.0
        city_stats.append({"country": c, "city": city, "tips_count": cnt, "avg_score": avg})

    return country_stats, city_stats


def _top_cities(city_stats: List[Dict[str, Any]]) -> List[str]:
    filtered = [r for r in city_stats if int(r.get("tips_count", 0)) >= 2]
    def sort_key(r: Dict[str, Any]) -> Tuple[float, int, str]:
        return (-float(r["avg_score"]), -int(r["tips_count"]), str(r["city"]))
    filtered.sort(key=sort_key)
    top3 = filtered[:3]
    return [r["city"] for r in top3]


def _extract_summary_json_from_html(html: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        pattern = re.compile(r'<script\s+id="summary-data"\s+type="application/json">\s*(.*?)\s*</script>', re.DOTALL)
        m = pattern.search(html)
        if not m:
            return None, "summary-data script tag not found"
        blob = m.group(1).strip()
        data = json.loads(blob)
        if not isinstance(data, dict):
            return None, "summary-data JSON is not an object"
        return data, None
    except Exception as e:
        return None, str(e)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_site_title_updated": 0.0,
        "config_output_dir_updated": 0.0,
        "config_data_path_kept_correct": 0.0,
        "build_script_uses_correct_config": 0.0,
        "run_build_sh_works": 0.0,
        "country_aggregates_correct": 0.0,
        "city_aggregates_correct": 0.0,
        "homepage_exists": 0.0,
        "homepage_contains_required_comment": 0.0,
        "homepage_summary_json_correct": 0.0,
        "homepage_top_cities_correct_order": 0.0,
        "readme_rewritten_description": 0.0,
        "readme_instructions_include_venv_and_build_command": 0.0,
        "readme_includes_counts_and_outputs": 0.0,
    }

    # Load config and input to compute expectations
    cfg_path = workspace / "config" / "config.json"
    cfg, cfg_err = _safe_load_json(cfg_path)
    if cfg_err is None and isinstance(cfg, dict):
        if cfg.get("site_title") == "Multicultural Insider Travel Guide":
            scores["config_site_title_updated"] = 1.0
        if cfg.get("output_dir") == "dist":
            scores["config_output_dir_updated"] = 1.0
        # Only award data_path check if the updated fields are also correct, to ensure it's part of the intended change
        if (
            cfg.get("site_title") == "Multicultural Insider Travel Guide"
            and cfg.get("output_dir") == "dist"
            and cfg.get("data_path") == "input/data/tips.json"
        ):
            scores["config_data_path_kept_correct"] = 1.0

    tips_path = workspace / "input" / "data" / "tips.json"
    tips, tips_err = _safe_load_json(tips_path)
    expected_country_stats: Optional[Dict[str, Dict[str, Any]]] = None
    expected_city_stats: Optional[List[Dict[str, Any]]] = None
    expected_total_tips: Optional[int] = None
    expected_countries_sorted: Optional[List[str]] = None
    expected_top_cities: Optional[List[str]] = None
    if tips_err is None and isinstance(tips, list):
        expected_total_tips = len(tips)
        expected_countries_sorted = sorted({t.get("country") for t in tips if isinstance(t, dict) and "country" in t})
        expected_country_stats, expected_city_stats = _compute_aggregates(tips)
        if expected_city_stats is not None:
            expected_top_cities = _top_cities(expected_city_stats)

    # Check build script uses correct config key and has been updated in place
    build_script = workspace / "scripts" / "build_site.py"
    build_text, b_err = _safe_read_text(build_script)
    if b_err is None and build_text is not None:
        # Should reference data_path and not the outdated data_file key at runtime
        uses_data_path = ("data_path" in build_text)
        mentions_outdated = ("data_file" in build_text)
        # If script still contains 'data_file' string, consider it outdated (strict)
        if uses_data_path and not mentions_outdated:
            scores["build_script_uses_correct_config"] = 1.0

    # Helper script run_build.sh should run build and print absolute path to dist/index.html
    run_build_sh = workspace / "scripts" / "run_build.sh"
    if run_build_sh.exists():
        for shell in [["bash", str(run_build_sh)], ["sh", str(run_build_sh)]]:
            rc, out, err = _run_cmd(shell, workspace)
            out_stripped = out.strip()
            if rc == 0 and out_stripped:
                lines = [ln for ln in out_stripped.splitlines() if ln.strip()]
                last_line = lines[-1] if lines else out_stripped
                path_out = Path(last_line.strip())
                if path_out.is_absolute() and path_out.name == "index.html" and path_out.parent.name == "dist" and path_out.exists():
                    scores["run_build_sh_works"] = 1.0
                    break

    # Aggregates: country-level JSON
    country_stats_path = workspace / "output" / "aggregates" / "country_stats.json"
    country_stats, c_err = _safe_load_json(country_stats_path)
    if c_err is None and isinstance(country_stats, dict) and expected_country_stats is not None:
        keys_match = set(country_stats.keys()) == set(expected_country_stats.keys())
        values_match = True
        if keys_match:
            for k, v in expected_country_stats.items():
                got = country_stats.get(k)
                if not isinstance(got, dict):
                    values_match = False
                    break
                if got.get("tips_count") != v.get("tips_count"):
                    values_match = False
                    break
                try:
                    got_avg = float(got.get("avg_score"))
                except Exception:
                    values_match = False
                    break
                if round(got_avg, 2) != round(float(v.get("avg_score")), 2):
                    values_match = False
                    break
        else:
            values_match = False
        if keys_match and values_match:
            scores["country_aggregates_correct"] = 1.0

    # Aggregates: city-level CSV
    city_stats_path = workspace / "output" / "aggregates" / "city_stats.csv"
    rows, header, r_err = _safe_read_csv_dicts(city_stats_path)
    if r_err is None and header is not None and rows is not None and expected_city_stats is not None:
        header_ok = header == ["country", "city", "tips_count", "avg_score"]
        values_ok = True
        expected_set = set()
        for r in expected_city_stats:
            expected_set.add((r["country"], r["city"], int(r["tips_count"]), float(r["avg_score"])))
        got_set = set()
        for row in rows:
            try:
                c = row.get("country")
                ci = row.get("city")
                tc = int(row.get("tips_count"))
                av = round(float(row.get("avg_score")), 2)
                got_set.add((c, ci, tc, av))
            except Exception:
                values_ok = False
                break
        if values_ok and header_ok and got_set == expected_set:
            scores["city_aggregates_correct"] = 1.0

    # Homepage checks
    index_html_path = workspace / "dist" / "index.html"
    html_text, html_err = _safe_read_text(index_html_path)
    if html_err is None and html_text is not None:
        scores["homepage_exists"] = 1.0
        if "<!-- multicultural-insider-build -->" in html_text:
            scores["homepage_contains_required_comment"] = 1.0
        summary, sum_err = _extract_summary_json_from_html(html_text)
        if sum_err is None and summary is not None and expected_total_tips is not None and expected_countries_sorted is not None:
            total_ok = summary.get("total_tips") == expected_total_tips
            countries = summary.get("countries")
            countries_ok = isinstance(countries, list) and countries == expected_countries_sorted
            if total_ok and countries_ok:
                scores["homepage_summary_json_correct"] = 1.0
        # Top cities order (ensure presence and order)
        if expected_top_cities is not None and len(expected_top_cities) >= 3 and "Top Cities by Insider Score" in html_text:
            try:
                pos1 = html_text.index(expected_top_cities[0])
                pos2 = html_text.index(expected_top_cities[1], pos1 + 1)
                pos3 = html_text.index(expected_top_cities[2], pos2 + 1)
                scores["homepage_top_cities_correct_order"] = 1.0
            except ValueError:
                pass

    # README checks
    readme_path = workspace / "docs" / "README.md"
    readme_text, readme_err = _safe_read_text(readme_path)
    if readme_err is None and readme_text is not None:
        text_lower = readme_text.lower()
        if ("local build" in text_lower) and ("multicultural" in text_lower) and ("insider travel guide" in text_lower):
            scores["readme_rewritten_description"] = 1.0
        # Basic venv creation/activation mention and build command
        venv_ok = (".venv" in readme_text) and (
            "python -m venv .venv" in readme_text or "python3 -m venv .venv" in readme_text
        ) and (
            "activate" in text_lower  # covers both source and Windows activate mention
        )
        build_cmd_ok = ("python scripts/build_site.py" in readme_text)
        if venv_ok and build_cmd_ok:
            scores["readme_instructions_include_venv_and_build_command"] = 1.0
        counts_ok = False
        outputs_ok = False
        if expected_total_tips is not None and expected_countries_sorted is not None:
            if str(expected_total_tips) in readme_text and str(len(expected_countries_sorted)) in readme_text:
                counts_ok = True
        required_outputs = [
            "dist/index.html",
            "output/aggregates/country_stats.json",
            "output/aggregates/city_stats.csv",
        ]
        if all(p in readme_text for p in required_outputs):
            outputs_ok = True
        if counts_ok and outputs_ok:
            scores["readme_includes_counts_and_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()