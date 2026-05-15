import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def subst(template: str, slug: str) -> str:
    return template.replace("${slug}", slug)


def check_files(base_dir: Path, required: List[str]) -> List[str]:
    missing: List[str] = []
    if not base_dir.is_dir():
        return list(required)
    for name in required:
        if not (base_dir / name).exists():
            missing.append(name)
    return missing


def find_player_report(players: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for p in players:
        if p.get("player") == name:
            return p
    return None


def grade(transcript: list, workspace_path: str) -> Dict[str, float]:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_slug_correct": 0.0,
        "config_social_required_snippets_exact": 0.0,
        "config_features_dir_exists": 0.0,
        "config_social_dir_exists": 0.0,
        "config_recomputed_missing_empty": 0.0,
        "report_exists_and_valid": 0.0,
        "report_overall_status_ok": 0.0,
        "report_marie_status_ok_missing_empty": 0.0,
        "report_fields_match_config_for_marie": 0.0,
        "report_players_count_matches_config": 0.0,
        "report_missing_matches_recomputed": 0.0,
    }

    config_path = workspace / "config" / "team_config.json"
    report_path = workspace / "reports" / "sync_report.json"

    cfg = safe_load_json(config_path)
    marie_cfg: Optional[Dict[str, Any]] = None
    slug = ""
    features_dir_tpl = ""
    social_dir_tpl = ""
    req_features_list: List[str] = []
    req_social_list: List[str] = []

    if isinstance(cfg, dict):
        players_cfg = cfg.get("players")
        if isinstance(players_cfg, list):
            for p in players_cfg:
                if isinstance(p, dict) and p.get("name") == "Marie Pollmann":
                    marie_cfg = p
                    break

    if isinstance(marie_cfg, dict):
        slug = marie_cfg.get("slug", "")
        if slug == "marie-pollmann":
            scores["config_slug_correct"] = 1.0

        features_dir_tpl = marie_cfg.get("features_dir", "")
        social_dir_tpl = marie_cfg.get("social_dir", "")

        required = marie_cfg.get("required_files", {})
        if isinstance(required, dict):
            rf = required.get("features", [])
            rs = required.get("social", [])
            if isinstance(rf, list) and all(isinstance(x, str) for x in rf):
                req_features_list = rf
            if isinstance(rs, list) and all(isinstance(x, str) for x in rs):
                req_social_list = rs

        # Check required social files exactly match what's on disk by spec (snippets.jsonl)
        if req_social_list == ["snippets.jsonl"]:
            scores["config_social_required_snippets_exact"] = 1.0

        # Check that substituted directories exist
        features_dir_rel = subst(str(features_dir_tpl), slug)
        social_dir_rel = subst(str(social_dir_tpl), slug)
        features_dir = workspace / features_dir_rel
        social_dir = workspace / social_dir_rel

        if features_dir.is_dir():
            scores["config_features_dir_exists"] = 1.0
        if social_dir.is_dir():
            scores["config_social_dir_exists"] = 1.0

        # Recompute missing using same logic as validator
        missing_features = check_files(features_dir, req_features_list)
        missing_social = check_files(social_dir, req_social_list)
        if len(missing_features) == 0 and len(missing_social) == 0 and req_features_list is not None and req_social_list is not None:
            scores["config_recomputed_missing_empty"] = 1.0

    # Load and validate report
    report = safe_load_json(report_path)
    marie_report: Optional[Dict[str, Any]] = None
    if isinstance(report, dict):
        scores["report_exists_and_valid"] = 1.0
        if report.get("overall_status") == "ok":
            scores["report_overall_status_ok"] = 1.0

        players_report = report.get("players")
        if isinstance(players_report, list) and isinstance(cfg, dict):
            cfg_players = cfg.get("players")
            if isinstance(cfg_players, list) and len(players_report) == len(cfg_players):
                scores["report_players_count_matches_config"] = 1.0
            marie_report = find_player_report(players_report, "Marie Pollmann")

        if isinstance(marie_report, dict):
            # Status and missing empty
            missing = marie_report.get("missing", {})
            mf: List[str] = []
            ms: List[str] = []
            if isinstance(missing, dict):
                f = missing.get("features", [])
                s = missing.get("social", [])
                if isinstance(f, list):
                    mf = f
                if isinstance(s, list):
                    ms = s
            status = marie_report.get("status")
            if status == "ok" and len(mf) == 0 and len(ms) == 0:
                scores["report_marie_status_ok_missing_empty"] = 1.0

            # Cross-check report fields vs config for Marie
            if isinstance(marie_cfg, dict):
                slug_cfg = marie_cfg.get("slug", "")
                features_dir_tpl = marie_cfg.get("features_dir", "")
                social_dir_tpl = marie_cfg.get("social_dir", "")
                reqs_cfg = marie_cfg.get("required_files", {})
                rf_cfg: List[str] = []
                rs_cfg: List[str] = []
                if isinstance(reqs_cfg, dict):
                    rf = reqs_cfg.get("features", [])
                    rs = reqs_cfg.get("social", [])
                    if isinstance(rf, list):
                        rf_cfg = rf
                    if isinstance(rs, list):
                        rs_cfg = rs
                features_dir_expected = subst(str(features_dir_tpl), slug_cfg)
                social_dir_expected = subst(str(social_dir_tpl), slug_cfg)

                match = True
                if marie_report.get("slug") != slug_cfg:
                    match = False
                if marie_report.get("features_dir") != features_dir_expected:
                    match = False
                if marie_report.get("social_dir") != social_dir_expected:
                    match = False
                req_rep = marie_report.get("required_files", {})
                if not isinstance(req_rep, dict):
                    match = False
                else:
                    rf_rep = req_rep.get("features", [])
                    rs_rep = req_rep.get("social", [])
                    if rf_rep != rf_cfg or rs_rep != rs_cfg:
                        match = False
                if match:
                    scores["report_fields_match_config_for_marie"] = 1.0

                # Compare report missing to recomputed missing
                features_dir = workspace / features_dir_expected
                social_dir = workspace / social_dir_expected
                recomputed_mf = check_files(features_dir, rf_cfg)
                recomputed_ms = check_files(social_dir, rs_cfg)
                if isinstance(mf, list) and isinstance(ms, list):
                    if mf == recomputed_mf and ms == recomputed_ms:
                        scores["report_missing_matches_recomputed"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()