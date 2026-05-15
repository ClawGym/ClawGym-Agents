import argparse
import csv
import json
from pathlib import Path

NUMERIC_FIELDS = ["planet_x", "planet_y", "comet_x", "comet_y", "brightness"]


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_rows(csv_path):
    """
    TODO: Implement: read CSV with header row. Convert frame to int and numeric fields in
    NUMERIC_FIELDS to float. Return list of dicts with keys: frame, planet_x, planet_y,
    comet_x, comet_y, brightness.
    """
    raise NotImplementedError("read_rows not implemented")


def compute_stats(rows):
    """
    TODO: Implement: compute min and max for each field in NUMERIC_FIELDS across rows.
    Return dict: {field: {"min": value, "max": value}}
    """
    raise NotImplementedError("compute_stats not implemented")


def to_px(val, size):
    return int(round(float(val) * int(size)))


def svg_frame_content(row, cfg):
    """
    TODO: Implement: produce an SVG string for one frame.
    Use cfg['canvas']['width'], cfg['canvas']['height'], cfg['canvas']['background'].
    Draw:
      - background rect covering the canvas
      - planet circle at (planet_x * width, planet_y * height) with radius cfg['style']['planet_radius'] and fill cfg['style']['planet_color']
      - comet circle at (comet_x * width, comet_y * height) with radius cfg['style']['comet_radius'] and fill cfg['style']['comet_color']
      - comet glow: another circle centered on the comet with radius (comet_radius + brightness * 20) and low fill-opacity (e.g., 0.25)
    Return the SVG XML as a string.
    """
    raise NotImplementedError("svg_frame_content not implemented")


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to config JSON")
    ap.add_argument("--csv", required=True, help="Path to orbit CSV")
    args = ap.parse_args()

    cfg = load_config(args.config)
    frames_dir = Path(cfg["output"]["frames_dir"])  # do not change path in code; configurable via JSON
    manifest_path = Path(cfg["output"]["manifest_path"])  # do not change path in code; configurable via JSON

    rows = read_rows(args.csv)
    stats = compute_stats(rows)

    frames_meta = []
    width = cfg["canvas"]["width"]
    height = cfg["canvas"]["height"]

    for row in rows:
        idx = int(row["frame"])  # must be int from CSV
        fname = f"frame_{idx:04d}.svg"
        out_path = frames_dir / fname
        svg = svg_frame_content(row, cfg)
        write_text(out_path, svg)
        frames_meta.append({
            "frame": idx,
            "svg_path": str(out_path.as_posix()),
            "planet": {"x": row["planet_x"], "y": row["planet_y"]},
            "comet": {"x": row["comet_x"], "y": row["comet_y"]},
            "brightness": row["brightness"],
        })

    manifest = {
        "source_csv": str(Path(args.csv).as_posix()),
        "total_frames": len(rows),
        "title": cfg.get("title"),
        "canvas_size": [width, height],
        "stats": stats,
        "frames": frames_meta,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
