import argparse
import json
import os
import re
import sys
import math

ALLOWED_SHAPES = {"circle", "square", "hex"}
ALLOWED_ICONS = {"star", "heart", "bolt"}
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def write_log(logf, line):
    if logf is not None:
        logf.write(line + "\n")
        logf.flush()


def validate_spec(spec, line_no):
    if not isinstance(spec, dict):
        return None, f"Invalid spec on line {line_no}: not a JSON object"
    _id = spec.get("id")
    if not _id or not isinstance(_id, str):
        return None, "Missing or empty 'id'"
    shape = spec.get("shape")
    if not shape or not isinstance(shape, str) or shape not in ALLOWED_SHAPES:
        return _id, f"Unsupported shape '{shape}'"
    color = spec.get("bg_color")
    if not color or not isinstance(color, str) or not HEX_COLOR_RE.fullmatch(color):
        return _id, f"Invalid color '{color}'"
    icon = spec.get("icon")
    if not icon or not isinstance(icon, str) or icon not in ALLOWED_ICONS:
        allowed = "|".join(sorted(ALLOWED_ICONS))
        return _id, f"Unsupported icon '{icon}'. Allowed: {allowed}"
    return None, None


def svg_polygon_points(cx, cy, r, sides):
    pts = []
    for i in range(sides):
        angle = 2 * math.pi * i / sides - math.pi / 2.0
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        pts.append(f"{x:.2f},{y:.2f}")
    return " ".join(pts)


def render_svg(shape, color, icon, out_path, size=256):
    cx = cy = size / 2
    r = size * 0.35
    if shape == "circle":
        shape_el = f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='{color}' />"
    elif shape == "square":
        side = r * 2
        x = cx - r
        y = cy - r
        shape_el = f"<rect x='{x}' y='{y}' width='{side}' height='{side}' rx='12' ry='12' fill='{color}' />"
    elif shape == "hex":
        pts = svg_polygon_points(cx, cy, r, 6)
        shape_el = f"<polygon points='{pts}' fill='{color}' />"
    else:
        raise ValueError(f"Unexpected shape: {shape}")

    # simple icon label
    text_el = (
        f"<text x='{cx}' y='{cy + 8}' font-family='Arial, Helvetica, sans-serif' "
        f"font-size='28' fill='#ffffff' text-anchor='middle'>{icon}</text>"
    )

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 {size} {size}'>"
        f"<rect width='100%' height='100%' fill='#111111'/>"
        f"{shape_el}{text_el}</svg>"
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(svg)


def main():
    parser = argparse.ArgumentParser(description="Render simple SVG avatar previews from JSONL specs.")
    parser.add_argument("--specs", required=True, help="Path to JSONL specs file")
    parser.add_argument("--outdir", required=True, help="Directory to write SVG outputs")
    parser.add_argument("--continue", dest="cont", action="store_true", help="Continue on errors and report summary")
    parser.add_argument("--log", dest="log_path", help="Optional path to write a combined log")
    args = parser.parse_args()

    logf = open(args.log_path, 'w', encoding='utf-8') if args.log_path else None

    total = 0
    ok = 0
    errors = 0

    try:
        with open(args.specs, 'r', encoding='utf-8') as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    spec = json.loads(line)
                except json.JSONDecodeError as e:
                    errors += 1
                    msg = f"Invalid JSON on line {line_no}: {e.msg}"
                    eprint(f"ERROR line-{line_no} {msg}")
                    write_log(logf, f"ERROR line-{line_no} {msg}")
                    if not args.cont:
                        if logf: logf.close()
                        sys.exit(2)
                    continue

                bad_id, err = validate_spec(spec, line_no)
                if err:
                    errors += 1
                    ident = bad_id if bad_id else f"line-{line_no}"
                    eprint(f"ERROR {ident} {err}")
                    write_log(logf, f"ERROR {ident} {err}")
                    if not args.cont:
                        if logf: logf.close()
                        sys.exit(2)
                    continue

                _id = spec["id"]
                shape = spec["shape"]
                color = spec["bg_color"]
                icon = spec["icon"]
                out_path = os.path.join(args.outdir, f"{_id}.svg")
                try:
                    render_svg(shape, color, icon, out_path)
                    ok += 1
                    msg = f"OK {_id} {out_path}"
                    print(msg)
                    write_log(logf, msg)
                except Exception as ex:
                    errors += 1
                    emsg = f"Render failed: {type(ex).__name__}: {ex}"
                    eprint(f"ERROR {_id} {emsg}")
                    write_log(logf, f"ERROR {_id} {emsg}")
                    if not args.cont:
                        if logf: logf.close()
                        sys.exit(2)

    finally:
        summary = f"SUMMARY total={total} ok={ok} errors={errors}"
        print(summary)
        write_log(logf, summary)
        if logf:
            logf.close()

    # exit codes: 0 if all ok; 1 if continued with errors; 2 was used for immediate failure paths
    if errors > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
