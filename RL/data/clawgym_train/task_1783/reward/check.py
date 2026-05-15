import json
import os
import sys
from datetime import datetime, timezone

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_iso8601_z(ts: str):
    # Accept ISO8601 with 'Z'
    try:
        if ts.endswith("Z"):
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        # Fallbacks
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None

def compute_expected_from_inputs(input_dir):
    # Defaults if parsing fails; overridden if inputs are valid
    expected = {
        "score": 70,
        "verdict": "FAIL",
        "evidence": {
            "keyFiles": {"SOUL.md": True, "USER.md": False, "TOOLS.md": True, "MEMORY.md": True},
            "backupRoots_primary": {"root": "input/backups/primary", "exists": True, "count": 2},
            "newestBackupAgeHours": 76.0,
            "runbookSignals": []
        }
    }
    ws = load_json(os.path.join(input_dir, "workspace.json")) or {}
    bkp = load_json(os.path.join(input_dir, "backups.json")) or {}

    # keyFiles
    kf = expected["evidence"]["keyFiles"].copy()
    try:
        ws_kf = ws.get("key_files") or ws.get("keyFiles") or {}
        for name in ["SOUL.md", "USER.md", "TOOLS.md", "MEMORY.md"]:
            val = ws_kf.get(name)
            if isinstance(val, bool):
                kf[name] = val
    except Exception:
        pass
    expected["evidence"]["keyFiles"] = kf

    # runbook signals
    try:
        rb = ws.get("runbook_signals") or ws.get("runbookSignals") or []
        if isinstance(rb, list):
            expected["evidence"]["runbookSignals"] = rb
    except Exception:
        pass

    # backups
    primary_root = "input/backups/primary"
    primary_exists = True
    primary_count = 2
    newest_age_hours = 76.0
    try:
        current_time = bkp.get("current_time") or bkp.get("currentTime")
        roots = bkp.get("roots") or []
        # Find primary entry
        pr = None
        for r in roots:
            r_root = r.get("root") or r.get("path")
            if r_root == primary_root:
                pr = r
                break
        if pr is not None:
            primary_exists = bool(pr.get("exists", True))
            artifacts = pr.get("artifacts") or pr.get("entries") or []
            primary_count = len(artifacts)
            # compute newest mtime
            newest = None
            for a in artifacts:
                mt = a.get("mtime") or a.get("modified") or a.get("mtimeMs")
                if isinstance(mt, (int, float)):
                    # epoch ms or seconds unknown; skip ambiguous numeric
                    continue
                if isinstance(mt, str):
                    dt = parse_iso8601_z(mt)
                    if dt is not None and (newest is None or dt > newest):
                        newest = dt
            ct = parse_iso8601_z(current_time) if isinstance(current_time, str) else None
            if newest and ct:
                diff = ct - newest
                newest_age_hours = round(diff.total_seconds() / 3600.0, 1)
        expected["evidence"]["backupRoots_primary"] = {
            "root": primary_root,
            "exists": primary_exists,
            "count": primary_count
        }
        expected["evidence"]["newestBackupAgeHours"] = newest_age_hours
    except Exception:
        pass

    # Score and verdict fixed by audit_spec; but if inputs imply otherwise, we keep dataset expectation
    expected["score"] = 70
    expected["verdict"] = "FAIL"
    return expected

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "report_score_70": False,
        "report_verdict_fail": False,
        "report_summary_nonempty": False,
        "findings_missing_user_high": False,
        "findings_backup_freshness_medium": False,
        "findings_runbook_medium": False,
        "recs_count_ge3": False,
        "recs_mentions_user_md": False,
        "recs_mentions_runbook_or_document": False,
        "recs_mentions_backup_freshness": False,
        "drillplan_len_ge5": False,
        "drillplan_first_step_phrase": False,
        "evidence_keyfiles_map_correct": False,
        "evidence_backuproots_contains_primary": False,
        "evidence_newest_age_in_range": False,
        "evidence_runbook_signals_empty": False,
        "summary_exists": False,
        "summary_contains_verdict_fail": False,
        "summary_contains_score_70": False,
        "summary_has_at_least_three_bullets": False,
        "summary_has_drill_restore_phrase": False,
    }

    expected = compute_expected_from_inputs(input_dir)

    # Check report.json
    report_path = os.path.join(output_dir, "report.json")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report = load_json(report_path)
        if isinstance(report, dict):
            checks["report_json_valid"] = True
            # score
            if isinstance(report.get("score"), (int, float)) and report.get("score") == expected["score"]:
                checks["report_score_70"] = True
            # verdict
            if report.get("verdict") == expected["verdict"]:
                checks["report_verdict_fail"] = True
            # summary
            if isinstance(report.get("summary"), str) and report.get("summary").strip():
                checks["report_summary_nonempty"] = True
            # findings checks
            findings = report.get("findings")
            if isinstance(findings, list):
                # missing USER.md high
                for f in findings:
                    if isinstance(f, dict):
                        lvl = f.get("level")
                        area = f.get("area")
                        issue = f.get("issue", "")
                        if lvl == "HIGH" and area == "workspace" and isinstance(issue, str) and "missing core operator file: USER.md" in issue:
                            checks["findings_missing_user_high"] = True
                            break
                # backup freshness medium area backup-freshness
                if not checks["findings_backup_freshness_medium"]:
                    for f in findings:
                        if isinstance(f, dict) and f.get("level") == "MEDIUM" and f.get("area") == "backup-freshness":
                            checks["findings_backup_freshness_medium"] = True
                            break
                # runbook medium
                if not checks["findings_runbook_medium"]:
                    for f in findings:
                        if isinstance(f, dict) and f.get("level") == "MEDIUM" and f.get("area") == "runbook":
                            checks["findings_runbook_medium"] = True
                            break
            # recommendations
            recs = report.get("recommendations")
            if isinstance(recs, list):
                if len(recs) >= 3:
                    checks["recs_count_ge3"] = True
                # mention USER.md
                for r in recs:
                    if isinstance(r, str) and "USER.md" in r:
                        checks["recs_mentions_user_md"] = True
                        break
                # mention runbook or document
                for r in recs:
                    if isinstance(r, str) and ("runbook" in r.lower() or "document" in r.lower()):
                        checks["recs_mentions_runbook_or_document"] = True
                        break
                # mention backup freshness (refresh backups or similar)
                for r in recs:
                    if isinstance(r, str):
                        rl = r.lower()
                        if "backup" in rl and ("refresh" in rl or "fresh" in rl or "freshness" in rl):
                            checks["recs_mentions_backup_freshness"] = True
                            break
            # drill plan
            dp = report.get("drillPlan")
            if isinstance(dp, list):
                if len(dp) >= 5:
                    checks["drillplan_len_ge5"] = True
                if len(dp) >= 1 and isinstance(dp[0], str) and "Restore the newest backup into a safe test path" in dp[0]:
                    checks["drillplan_first_step_phrase"] = True
            # evidence
            ev = report.get("evidence")
            if isinstance(ev, dict):
                # keyFiles booleans
                kf = ev.get("keyFiles")
                expected_kf = expected["evidence"]["keyFiles"]
                if isinstance(kf, dict):
                    ok = True
                    for k, v in expected_kf.items():
                        if k not in kf or bool(kf[k]) != bool(v):
                            ok = False
                            break
                    if ok:
                        checks["evidence_keyfiles_map_correct"] = True
                # backupRoots contains primary
                br = ev.get("backupRoots")
                primary_expected = expected["evidence"].get("backupRoots_primary")
                if isinstance(br, list) and isinstance(primary_expected, dict):
                    found = False
                    for entry in br:
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("root") == primary_expected["root"] and bool(entry.get("exists")) == bool(primary_expected["exists"]) and entry.get("count") == primary_expected["count"]:
                            found = True
                            break
                    if found:
                        checks["evidence_backuproots_contains_primary"] = True
                # newest age
                age = ev.get("newestBackupAgeHours")
                if isinstance(age, (int, float)):
                    if 75.9 <= float(age) <= 76.1:
                        checks["evidence_newest_age_in_range"] = True
                # runbookSignals empty
                rbs = ev.get("runbookSignals")
                if isinstance(rbs, list) and len(rbs) == 0:
                    checks["evidence_runbook_signals_empty"] = True

    # Check summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""
        # Lines checks
        lines = [ln.rstrip("\n") for ln in text.splitlines()]
        # required lines
        if any("Verdict: FAIL" in ln for ln in lines):
            checks["summary_contains_verdict_fail"] = True
        if any("Score: 70" in ln for ln in lines):
            checks["summary_contains_score_70"] = True
        # bullet points count
        bullet_lines = [ln for ln in lines if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* ")]
        if len(bullet_lines) >= 3:
            checks["summary_has_at_least_three_bullets"] = True
        # drill restore phrase somewhere (ideally in drill steps)
        if any("Restore the newest backup into a safe test path" in ln for ln in lines):
            checks["summary_has_drill_restore_phrase"] = True

    # Compute reward
    # No-op baseline: if output missing or required artifact missing, reward must be 0.0
    # We enforce: if report.json missing -> 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    if not checks["report_exists"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()