import os
import json
import hashlib
from datetime import datetime

# Standard library only. You may modify anything in this file.
try:
    import yaml
except Exception:
    # Fallback minimal YAML loader using json if needed, but assume PyYAML is available only if preinstalled.
    yaml = None

CONFIG_PATH = os.path.join("input", "config.yaml")

DESCRIPTION = """
This is a skeleton for a hybrid yoga + strength plan prototype.
Implement the pipeline so that running `python src/app.py`:
  1) Reads input/config.yaml
  2) Performs search engine queries to find one .gov/.edu strength page and one .org yoga pose page
  3) Downloads those two pages to downloads/strength_source_1.html and downloads/yoga_source_1.html
  4) Extracts structured data into data/strength_movements.json and data/yoga_poses.json
  5) Generates outputs/weekly_plan.json, outputs/compliance_report.json, outputs/sources.json per the user request
Use only standard library networking and parsing approaches (e.g., urllib, html.parser). No hardcoded external content.
"""


def load_config(path: str) -> dict:
    # Minimal YAML/JSON loader (YAML preferred). If PyYAML isn't available, expect JSON content.
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if yaml is not None:
        return yaml.safe_load(text)
    else:
        return json.loads(text)


def ensure_dirs(cfg: dict):
    for key in ("downloads_dir", "data_dir", "outputs_dir"):
        d = cfg["paths"][key]
        os.makedirs(d, exist_ok=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# TODO: Implement these functions in your solution

def perform_search_and_download(cfg: dict) -> dict:
    """
    Use a general search engine to find:
      - One .gov or .edu strength training/movement patterns page
      - One .org yoga pose library page with categories & difficulty
    Save their raw HTML to downloads/strength_source_1.html and downloads/yoga_source_1.html.
    Return a dict with structure suitable for outputs/sources.json including queries, URLs, saved paths, sha256, and retrieved_at.
    """
    raise NotImplementedError


def extract_strength_movements(download_path: str, source_url: str) -> list:
    """
    Parse the saved strength HTML file and return a list of dicts with fields:
      {"source_url", "movement_category", "exercise_name"}
    Ensure >= 8 entries across >= 3 distinct movement_category values.
    """
    raise NotImplementedError


def extract_yoga_poses(download_path: str, source_url: str) -> list:
    """
    Parse the saved yoga HTML file and return a list of dicts with fields:
      {"source_url", "name", "category", "difficulty"}
    Ensure >= 12 entries with >= 3 categories and >= 2 difficulty levels.
    """
    raise NotImplementedError


def generate_weekly_plan(cfg: dict, yoga_poses: list, strength_moves: list) -> dict:
    """
    Use cfg.plan values to construct a 7-day plan with exactly cfg.plan.active_days active days.
    Each active day splits time ~60:40 (yoga:strength) within ±2 minutes, total equals session_length_minutes.
    Yoga segments must include at least 2 pose names drawn from yoga_poses.
    Strength segments must include a movement_category and at least 2 exercise names from strength_moves.
    Include at least two distinct yoga styles across the week if possible; avoid repeating the same yoga category on consecutive active days.
    Cover at least four of the five strength patterns across the week.
    Represent days as keys "1".."7" with list of segments; rest days: single segment type "rest" duration 0.
    """
    raise NotImplementedError


def build_compliance_report(cfg: dict, plan: dict, yoga_poses: list, strength_moves: list) -> dict:
    """
    Compute totals, unique yoga styles used, strength patterns covered, and whether constraints from cfg are met.
    Return a dict with keys: total_sessions, total_minutes, yoga_minutes, strength_minutes,
    yoga_styles_used (list), strength_patterns_covered (list), constraints_met (bool), violations (list).
    """
    raise NotImplementedError


def main():
    cfg = load_config(CONFIG_PATH)
    ensure_dirs(cfg)

    # 1) Search + download
    sources_manifest = perform_search_and_download(cfg)

    # 2) Extract structured data
    strength_html = os.path.join(cfg["paths"]["downloads_dir"], "strength_source_1.html")
    yoga_html = os.path.join(cfg["paths"]["downloads_dir"], "yoga_source_1.html")

    strength_data = extract_strength_movements(strength_html, sources_manifest["sources"][0]["url"])  # type: ignore[index]
    yoga_data = extract_yoga_poses(yoga_html, sources_manifest["sources"][1]["url"])  # type: ignore[index]

    # Save extracted datasets
    with open(os.path.join(cfg["paths"]["data_dir"], "strength_movements.json"), "w", encoding="utf-8") as f:
        json.dump(strength_data, f, indent=2, ensure_ascii=False)
    with open(os.path.join(cfg["paths"]["data_dir"], "yoga_poses.json"), "w", encoding="utf-8") as f:
        json.dump(yoga_data, f, indent=2, ensure_ascii=False)

    # 3) Generate plan
    plan = generate_weekly_plan(cfg, yoga_data, strength_data)
    with open(os.path.join(cfg["paths"]["outputs_dir"], "weekly_plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    # 4) Compliance report
    report = build_compliance_report(cfg, plan, yoga_data, strength_data)
    with open(os.path.join(cfg["paths"]["outputs_dir"], "compliance_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 5) Sources manifest
    with open(os.path.join(cfg["paths"]["outputs_dir"], "sources.json"), "w", encoding="utf-8") as f:
        json.dump(sources_manifest, f, indent=2, ensure_ascii=False)

    print("Prototype run complete. Outputs saved to:")
    print(" -", os.path.join(cfg["paths"]["outputs_dir"], "weekly_plan.json"))
    print(" -", os.path.join(cfg["paths"]["outputs_dir"], "compliance_report.json"))
    print(" -", os.path.join(cfg["paths"]["outputs_dir"], "sources.json"))


if __name__ == "__main__":
    main()
