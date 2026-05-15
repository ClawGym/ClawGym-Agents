#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Dict, List

def load_config(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def subst(template: str, slug: str) -> str:
    return template.replace("${slug}", slug)

def check_files(base_dir: str, required: List[str]) -> List[str]:
    missing = []
    if not os.path.isdir(base_dir):
        # If the directory itself is missing, treat all required as missing
        return list(required)
    for name in required:
        if not os.path.exists(os.path.join(base_dir, name)):
            missing.append(name)
    return missing

def validate(config_path: str) -> Dict:
    cfg = load_config(config_path)
    report_players = []
    any_errors = False

    for p in cfg.get("players", []):
        name = p.get("name")
        slug = p.get("slug", "")
        features_dir_tpl = p.get("features_dir", "")
        social_dir_tpl = p.get("social_dir", "")
        required = p.get("required_files", {})
        req_features = list(required.get("features", []))
        req_social = list(required.get("social", []))

        features_dir = subst(features_dir_tpl, slug)
        social_dir = subst(social_dir_tpl, slug)

        missing_features = check_files(features_dir, req_features)
        missing_social = check_files(social_dir, req_social)

        status = "ok" if (not missing_features and not missing_social) else "error"
        if status != "ok":
            any_errors = True

        report_players.append({
            "player": name,
            "slug": slug,
            "features_dir": features_dir,
            "social_dir": social_dir,
            "required_files": {
                "features": req_features,
                "social": req_social
            },
            "missing": {
                "features": missing_features,
                "social": missing_social
            },
            "status": status
        })

    return {
        "overall_status": "ok" if not any_errors else "error",
        "players": report_players
    }

def main() -> int:
    ap = argparse.ArgumentParser(description="Validate content sync for players")
    ap.add_argument("--config", required=True, help="Path to team_config.json")
    ap.add_argument("--report", required=True, help="Path to write JSON report")
    args = ap.parse_args()

    report = validate(args.config)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return 0 if report.get("overall_status") == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
