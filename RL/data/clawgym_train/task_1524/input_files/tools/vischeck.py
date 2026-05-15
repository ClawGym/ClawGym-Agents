#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from datetime import datetime

HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    required = ["title", "width", "height", "bg_color", "output"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing required config fields: {', '.join(missing)}")
    if not isinstance(cfg["title"], str) or not cfg["title"].strip():
        raise ValueError("Config 'title' must be a non-empty string")
    if not isinstance(cfg["width"], int) or cfg["width"] <= 0:
        raise ValueError("Config 'width' must be a positive integer")
    if not isinstance(cfg["height"], int) or cfg["height"] <= 0:
        raise ValueError("Config 'height' must be a positive integer")
    if not isinstance(cfg["bg_color"], str) or not HEX_COLOR_RE.match(cfg["bg_color"]):
        raise ValueError("Config 'bg_color' must be a hex color like #aabbcc")
    if not isinstance(cfg["output"], str) or not cfg["output"].strip():
        raise ValueError("Config 'output' must be a non-empty path string")
    return cfg


def ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def generate_svg(cfg):
    w = cfg["width"]
    h = cfg["height"]
    bg = cfg["bg_color"]
    title = cfg["title"]

    margin = 30
    plot_w = w - 2 * margin
    plot_h = h - 2 * margin

    # Simple synthetic data for a small line plot (normalized values)
    data = [0.15, 0.35, 0.3, 0.55, 0.7, 0.6, 0.8, 0.65, 0.5, 0.4]

    # Build grid lines
    grid_lines = []
    for i in range(0, 6):
        y = margin + i * (plot_h / 5.0)
        grid_lines.append(f'<line x1="{margin}" y1="{y:.2f}" x2="{margin + plot_w}" y2="{y:.2f}" stroke="#dddddd" stroke-width="1" />')

    # Axes
    axes = [
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{margin + plot_h}" stroke="#333333" stroke-width="2" />',
        f'<line x1="{margin}" y1="{margin + plot_h}" x2="{margin + plot_w}" y2="{margin + plot_h}" stroke="#333333" stroke-width="2" />'
    ]

    # Line path for data
    pts = []
    step = plot_w / (len(data) - 1)
    for i, v in enumerate(data):
        x = margin + i * step
        y = margin + plot_h - (v * plot_h)
        pts.append(f"{x:.2f},{y:.2f}")
    polyline = f'<polyline fill="none" stroke="#0077cc" stroke-width="2" points="{' '.join(pts)}" />'

    title_text = (
        f'<text x="{w/2:.2f}" y="{max(18, margin - 8):.2f}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="14" fill="#222222">{escape_svg_text(title)}</text>'
    )

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <rect x="0" y="0" width="{w}" height="{h}" fill="{bg}" />
  {''.join(grid_lines)}
  {''.join(axes)}
  {polyline}
  {title_text}
</svg>
'''
    return svg


def escape_svg_text(text):
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


def main():
    parser = argparse.ArgumentParser(description="Visuals readiness checker: generates a simple SVG and reports status.")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    parser.add_argument("--report", required=False, help="Path to write JSON status report")
    args = parser.parse_args()

    status = {
        "ok": False,
        "error": None,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "python_version": sys.version,
        "working_directory": os.getcwd(),
        "script": os.path.relpath(__file__) if hasattr(sys.modules[__name__], "__file__") else "tools/vischeck.py"
    }

    try:
        cfg = load_config(args.config)
        status["config"] = cfg
        out_path = cfg["output"]
        ensure_parent_dir(out_path)
        svg = generate_svg(cfg)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(svg)
        exists = os.path.exists(out_path)
        size = os.path.getsize(out_path) if exists else 0
        status.update({
            "output_file": out_path,
            "output_exists": exists,
            "output_size_bytes": int(size)
        })
        status["ok"] = exists and size > 0
    except Exception as e:
        status["error"] = str(e)
        status["ok"] = False

    # Write report file if requested
    if args.report:
        try:
            ensure_parent_dir(args.report)
            with open(args.report, "w", encoding="utf-8") as rf:
                json.dump(status, rf, indent=2)
        except Exception as e:
            # If report writing fails, at least reflect it in stdout
            status["error"] = (status.get("error") + "; " if status.get("error") else "") + f"report_write_failed: {e}"
            status["ok"] = False

    print(json.dumps(status, indent=2))
    sys.exit(0 if status.get("ok") else 1)


if __name__ == "__main__":
    main()
