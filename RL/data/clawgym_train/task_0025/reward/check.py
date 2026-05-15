import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NUMERIC_FIELDS = ["planet_x", "planet_y", "comet_x", "comet_y", "brightness"]


def _safe_load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            for r in reader:
                row = {
                    "frame": int(r["frame"]),
                    "planet_x": float(r["planet_x"]),
                    "planet_y": float(r["planet_y"]),
                    "comet_x": float(r["comet_x"]),
                    "comet_y": float(r["comet_y"]),
                    "brightness": float(r["brightness"]),
                }
                rows.append(row)
            return rows, None
    except Exception as e:
        return None, str(e)


def _compute_stats_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = {}
    for field in NUMERIC_FIELDS:
        vals = [float(r[field]) for r in rows]
        stats[field] = {"min": min(vals), "max": max(vals)}
    return stats


def _approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _run_script(workspace: Path) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    script_path = workspace / "src" / "render.py"
    config_path = workspace / "config" / "scene.json"
    csv_path = workspace / "data" / "orbits.csv"
    if not script_path.exists() or not config_path.exists() or not csv_path.exists():
        return False, None, None, "missing required inputs"
    cmd = [
        sys.executable,
        str(script_path),
        "--config",
        "config/scene.json",
        "--csv",
        "data/orbits.csv",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            text=True,
            check=False,
        )
        success = proc.returncode == 0
        return success, proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return False, None, None, str(e)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_art_direction_updated": 0.0,
        "config_output_paths_unchanged": 0.0,
        "script_todos_resolved": 0.0,
        "script_runs_successfully": 0.0,
        "frames_generated_exact_set": 0.0,
        "manifest_exists_and_valid_json": 0.0,
        "manifest_total_frames_correct": 0.0,
        "manifest_title_matches_config": 0.0,
        "manifest_canvas_size_matches_config": 0.0,
        "manifest_source_csv_path_correct": 0.0,
        "manifest_stats_correct": 0.0,
        "manifest_frames_entries_correct": 0.0,
        "svg_uses_art_direction_and_glow": 0.0,
    }

    # Load config for checks
    cfg_path = workspace / "config" / "scene.json"
    cfg, _ = _safe_load_json(cfg_path)

    # Check art direction updates (all-or-nothing to avoid baseline awarding)
    if cfg and isinstance(cfg, dict):
        title_ok = cfg.get("title") == "Auroras & Orbits"
        canvas_bg_ok = isinstance(cfg.get("canvas"), dict) and cfg["canvas"].get("background") == "#0b0b16"
        style = cfg.get("style") if isinstance(cfg.get("style"), dict) else {}
        planet_color_ok = style.get("planet_color") == "#7cc7ff"
        comet_color_ok = style.get("comet_color") == "#ffd166"
        if title_ok and canvas_bg_ok and planet_color_ok and comet_color_ok:
            scores["config_art_direction_updated"] = 1.0

        # Only award unchanged output path if art direction updates are present
        output_ok = (
            isinstance(cfg.get("output"), dict)
            and cfg["output"].get("frames_dir") == "outputs/frames"
            and cfg["output"].get("manifest_path") == "outputs/manifest.json"
        )
        if output_ok and scores["config_art_direction_updated"] == 1.0:
            scores["config_output_paths_unchanged"] = 1.0

    # Check TODOs resolved (no NotImplementedError remains)
    src_path = workspace / "src" / "render.py"
    src_text, _ = _safe_read_text(src_path)
    if src_text is not None and "NotImplementedError" not in src_text:
        scores["script_todos_resolved"] = 1.0

    # Attempt to run script
    ran_successfully, _, _, _ = _run_script(workspace)
    if ran_successfully:
        scores["script_runs_successfully"] = 1.0

    # Load CSV ground truth
    csv_path = workspace / "data" / "orbits.csv"
    rows, _ = _safe_read_csv_rows(csv_path)
    if rows is None:
        rows = []

    # Frames generation: exact set equals expected
    frames_dir = workspace / "outputs" / "frames"
    expected_names = [f"frame_{int(r['frame']):04d}.svg" for r in rows]
    if frames_dir.exists() and rows:
        actual_names = sorted([p.name for p in frames_dir.glob("*.svg")])
        if sorted(expected_names) == actual_names and len(actual_names) == len(expected_names):
            scores["frames_generated_exact_set"] = 1.0

    # Manifest checks
    manifest_path = workspace / "outputs" / "manifest.json"
    manifest, _ = _safe_load_json(manifest_path)
    if isinstance(manifest, dict):
        scores["manifest_exists_and_valid_json"] = 1.0

        # total_frames
        if isinstance(manifest.get("total_frames"), int) and rows:
            if manifest["total_frames"] == len(rows):
                scores["manifest_total_frames_correct"] = 1.0

        # title and canvas_size from config
        if cfg and isinstance(cfg.get("canvas"), dict):
            if manifest.get("title") == cfg.get("title"):
                scores["manifest_title_matches_config"] = 1.0
            canvas_size = manifest.get("canvas_size")
            if (
                isinstance(canvas_size, list)
                and len(canvas_size) == 2
                and canvas_size[0] == cfg["canvas"].get("width")
                and canvas_size[1] == cfg["canvas"].get("height")
            ):
                scores["manifest_canvas_size_matches_config"] = 1.0

        # source_csv path correctness: accept "data/orbits.csv" or absolute path
        src_csv_val = manifest.get("source_csv")
        src_ok = False
        if isinstance(src_csv_val, str):
            expected_abs = (workspace / "data" / "orbits.csv").resolve()
            try:
                src_resolved = Path(src_csv_val).resolve()
            except Exception:
                src_resolved = None
            if src_csv_val == "data/orbits.csv":
                src_ok = True
            elif src_resolved is not None and src_resolved == expected_abs:
                src_ok = True
        if src_ok:
            scores["manifest_source_csv_path_correct"] = 1.0

        # stats correctness
        if rows and isinstance(manifest.get("stats"), dict):
            expected_stats = _compute_stats_from_rows(rows)
            man_stats = manifest["stats"]
            stats_ok = True
            for field in NUMERIC_FIELDS:
                fstat = man_stats.get(field)
                if not isinstance(fstat, dict):
                    stats_ok = False
                    break
                mn = fstat.get("min")
                mx = fstat.get("max")
                if mn is None or mx is None:
                    stats_ok = False
                    break
                if not (_approx_equal(mn, expected_stats[field]["min"]) and _approx_equal(mx, expected_stats[field]["max"])):
                    stats_ok = False
                    break
            if stats_ok:
                scores["manifest_stats_correct"] = 1.0

        # frames entries content
        frames_ok = True
        frames_list = manifest.get("frames")
        if not isinstance(frames_list, list) or not rows:
            frames_ok = False
        else:
            if len(frames_list) != len(rows):
                frames_ok = False
            else:
                by_frame: Dict[int, Dict[str, Any]] = {}
                for item in frames_list:
                    if not isinstance(item, dict):
                        frames_ok = False
                        break
                    if not isinstance(item.get("frame"), int):
                        frames_ok = False
                        break
                    if item["frame"] in by_frame:
                        frames_ok = False
                        break
                    by_frame[item["frame"]] = item
                if frames_ok:
                    for r in rows:
                        fr = r["frame"]
                        if fr not in by_frame:
                            frames_ok = False
                            break
                        item = by_frame[fr]
                        expected_svg_path = f"outputs/frames/frame_{fr:04d}.svg"
                        if item.get("svg_path") != expected_svg_path:
                            frames_ok = False
                            break
                        planet = item.get("planet")
                        comet = item.get("comet")
                        brightness = item.get("brightness")
                        if not (isinstance(planet, dict) and isinstance(comet, dict) and isinstance(brightness, (int, float))):
                            frames_ok = False
                            break
                        for key in ("x", "y"):
                            if not isinstance(planet.get(key), (int, float)) or not isinstance(comet.get(key), (int, float)):
                                frames_ok = False
                                break
                        if not frames_ok:
                            break
                        if not (
                            _approx_equal(planet["x"], r["planet_x"])
                            and _approx_equal(planet["y"], r["planet_y"])
                            and _approx_equal(comet["x"], r["comet_x"])
                            and _approx_equal(comet["y"], r["comet_y"])
                            and _approx_equal(brightness, r["brightness"])
                        ):
                            frames_ok = False
                            break
        if frames_ok:
            scores["manifest_frames_entries_correct"] = 1.0

    # SVG content check for first frame: presence of svg, background, colors, and glow
    if rows:
        first_frame = rows[0]["frame"]
        svg_path = workspace / "outputs" / "frames" / f"frame_{first_frame:04d}.svg"
        svg_text, _ = _safe_read_text(svg_path)
        bg = cfg.get("canvas", {}).get("background") if isinstance(cfg, dict) else None
        planet_color = cfg.get("style", {}).get("planet_color") if isinstance(cfg, dict) else None
        comet_color = cfg.get("style", {}).get("comet_color") if isinstance(cfg, dict) else None
        if svg_text and isinstance(bg, str) and isinstance(planet_color, str) and isinstance(comet_color, str):
            text_lower = svg_text.lower()
            checks = [
                "<svg" in text_lower,
                bg in svg_text,
                planet_color in svg_text,
                comet_color in svg_text,
                "fill-opacity" in text_lower,  # indicates comet glow opacity present
            ]
            if all(checks):
                scores["svg_uses_art_direction_and_glow"] = 1.0

    return scores


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", nargs="?", default=".")
    args = ap.parse_args()
    result = grade([], args.workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()