import json
import os
import sys
import re
import csv

def is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str):
        return False
    # Accept YYYY-MM-DDThh:mm:ss[.sss][Z|+hh:mm|-hh:mm]
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?$'
    return re.match(pattern, s) is not None

def is_number(x):
    if isinstance(x, bool):
        return False
    return isinstance(x, (int, float))

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def safe_get(d, key, expected_type=None):
    if not isinstance(d, dict):
        return None
    v = d.get(key, None)
    if expected_type is not None and not isinstance(v, expected_type):
        return None
    return v

def parse_csv(path):
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            content = f.read()
        # Check header exactly
        first_line = content.splitlines()[0] if content.splitlines() else ""
        header_ok = (first_line.strip() == "id,severity,types,description_count")
        if not header_ok:
            return False, None, None
        # Re-parse with csv
        with open(path, newline="", encoding="utf-8") as f2:
            reader = csv.DictReader(f2)
            for row in reader:
                rows.append(row)
        return True, ["id", "severity", "types", "description_count"], rows
    except Exception:
        return False, None, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "portfolio_file_valid": False,
        "portfolio_candidates_valid": False,
        "risk_register_file_valid": False,
        "risk_register_consistent_with_portfolio": False,
        "identity_links_file_valid": False,
        "identity_links_includes_portfolio": False,
        "leaderboard_file_valid": False,
        "trending_file_valid": False,
        "dossier_file_valid": False,
        "dossier_consistent_with_portfolio": False,
        "audit_file_exists": False,
        "audit_sections_present": False,
        "audit_shortlist_size_matches": False
    }

    # Paths
    portfolio_path = os.path.join(output_dir, "portfolio_candidates.json")
    risk_path = os.path.join(output_dir, "risk_register.csv")
    identity_path = os.path.join(output_dir, "identity_links.jsonl")
    leaderboard_path = os.path.join(output_dir, "leaderboard_snapshot.json")
    trending_path = os.path.join(output_dir, "trending_watchlist.json")
    dossier_path = os.path.join(output_dir, "dossier.json")
    audit_path = os.path.join(output_dir, "audit_readme.md")

    # Load portfolio
    portfolio = read_json(portfolio_path)
    portfolio_ids = set()
    portfolio_candidates = []
    portfolio_max_score = None

    if isinstance(portfolio, dict):
        applied_filters = portfolio.get("applied_filters")
        generated_at = portfolio.get("generated_at")
        candidates = portfolio.get("candidates")

        # Validate basic structure
        valid_applied = isinstance(applied_filters, dict) and \
                        isinstance(applied_filters.get("min_score"), (int, float)) and not isinstance(applied_filters.get("min_score"), bool) and \
                        isinstance(applied_filters.get("exclude_severities"), list) and all(isinstance(s, str) for s in applied_filters.get("exclude_severities")) and \
                        isinstance(applied_filters.get("max_candidates"), (int, float)) and not isinstance(applied_filters.get("max_candidates"), bool)
        valid_generated = is_iso8601_like(generated_at) if isinstance(generated_at, str) else False
        valid_candidates = isinstance(candidates, list)

        if valid_applied and valid_generated and valid_candidates:
            checks["portfolio_file_valid"] = True

            # Validate candidates rules
            ids_seen = set()
            ok = True
            exclude_severities = set([s.strip() for s in applied_filters.get("exclude_severities", [])])

            def decision_for(score):
                # Mapping for non-critical severities
                if score >= 80:
                    return "proceed"
                elif 60 <= score <= 79:
                    return "proceed"
                elif 40 <= score <= 59:
                    return "review"
                elif 20 <= score <= 39:
                    return "review"
                else:
                    return "reject"

            local_max = None
            for item in candidates:
                if not isinstance(item, dict):
                    ok = False
                    break
                cid = item.get("id")
                name = item.get("name")
                platform = item.get("platform")
                score = item.get("composite_score")
                severity = item.get("severity")
                decision = item.get("decision")
                breakdown = item.get("breakdown")

                # Check required fields and types
                if not (isinstance(cid, str) and isinstance(name, str) and isinstance(platform, str)):
                    ok = False
                    break
                if not (is_number(score) and 0 <= float(score) <= 100):
                    ok = False
                    break
                if severity not in {"clear", "low", "medium", "high", "critical"}:
                    ok = False
                    break
                if decision not in {"proceed", "review", "reject"}:
                    ok = False
                    break
                if not isinstance(breakdown, dict):
                    ok = False
                    break
                for key in ["moltbook_activity", "moltx_influence", "4claw_community", "engagement_quality", "security_record", "longevity"]:
                    if key not in breakdown or not is_number(breakdown[key]):
                        ok = False
                        break
                if not ok:
                    break

                # Exclude severities filtering
                if severity in exclude_severities:
                    ok = False
                    break

                # Decision mapping and critical policy
                if severity == "critical":
                    if not (float(score) == 0 and decision == "reject"):
                        ok = False
                        break
                else:
                    expected = decision_for(float(score))
                    if decision != expected:
                        ok = False
                        break

                # Unique IDs
                if cid in ids_seen:
                    ok = False
                    break
                ids_seen.add(cid)

                # Track max
                if local_max is None or float(score) > float(local_max):
                    local_max = float(score)

                portfolio_ids.add(cid)

            # candidates length vs max_candidates
            max_candidates = applied_filters.get("max_candidates")
            try:
                max_candidates_val = int(max_candidates)
            except Exception:
                max_candidates_val = None
            if ok and max_candidates_val is not None and len(candidates) <= max_candidates_val:
                checks["portfolio_candidates_valid"] = True
                portfolio_candidates = candidates
                portfolio_max_score = local_max
            else:
                # If any rule failed, keep False
                pass

    # Risk register
    header_ok, fields, rows = parse_csv(risk_path)
    if header_ok and isinstance(rows, list):
        # Validate rows
        ids = set()
        ok_rows = True
        severities_allowed = {"low", "medium", "high", "critical"}
        # Build expected set from portfolio: all candidates with severity != clear need a row
        portfolio_nonclear = {}
        for c in portfolio_candidates:
            if c.get("severity") in severities_allowed:
                portfolio_nonclear[c.get("id")] = c.get("severity")

        seen_ids_set = set()
        for row in rows:
            rid = row.get("id")
            sev = row.get("severity")
            types_field = row.get("types")
            desc = row.get("description_count")
            # Basic field checks
            if not isinstance(rid, str) or rid == "":
                ok_rows = False
                break
            if rid in ids:
                ok_rows = False
                break
            ids.add(rid)
            if sev not in severities_allowed:
                ok_rows = False
                break
            if not isinstance(types_field, str):
                ok_rows = False
                break
            # Require at least one non-empty type token
            tokens = [t for t in [t.strip() for t in types_field.split(";")] if t]
            if len(tokens) == 0:
                ok_rows = False
                break
            # description_count integer >=1
            try:
                d = int(desc)
            except Exception:
                ok_rows = False
                break
            if d < 1:
                ok_rows = False
                break
            seen_ids_set.add(rid)

        if ok_rows:
            checks["risk_register_file_valid"] = True
            # Consistency with portfolio non-clear
            consistent = True
            for pid, psev in portfolio_nonclear.items():
                # Each must exist with matching severity
                matches = [r for r in rows if r.get("id") == pid]
                if len(matches) != 1:
                    consistent = False
                    break
                if matches[0].get("severity") != psev:
                    consistent = False
                    break
            if consistent:
                checks["risk_register_consistent_with_portfolio"] = True

    # Identity links
    identity_lines = read_lines(identity_path)
    identity_records = []
    if identity_lines is not None:
        schema_ok = True
        includes_portfolio = False
        for line in identity_lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                schema_ok = False
                break
            if not isinstance(obj, dict):
                schema_ok = False
                break
            primary_id = obj.get("primary_id")
            is_multi = obj.get("is_multi_account")
            linked = obj.get("linked_accounts")
            if not (isinstance(primary_id, str) and isinstance(is_multi, bool) and isinstance(linked, list)):
                schema_ok = False
                break
            if is_multi and len(linked) < 2:
                schema_ok = False
                break
            for acc in linked:
                if not isinstance(acc, dict):
                    schema_ok = False
                    break
                if not (isinstance(acc.get("id"), str) and isinstance(acc.get("platform"), str) and isinstance(acc.get("name"), str)):
                    schema_ok = False
                    break
                conf = acc.get("confidence")
                if not is_number(conf) or not (0 <= float(conf) <= 1):
                    schema_ok = False
                    break
            if not schema_ok:
                break
            if primary_id in portfolio_ids:
                includes_portfolio = True
            identity_records.append(obj)
        if schema_ok:
            checks["identity_links_file_valid"] = True
            if includes_portfolio:
                checks["identity_links_includes_portfolio"] = True

    # Leaderboard snapshot
    leaderboard = read_json(leaderboard_path)
    if isinstance(leaderboard, dict):
        top = leaderboard.get("top")
        if isinstance(top, list) and len(top) >= 10:
            ranks_ok = True
            scores_ok = True
            prev_score = None
            expected_rank = 1
            for entry in top:
                if not isinstance(entry, dict):
                    ranks_ok = False
                    break
                rank = entry.get("rank")
                cid = entry.get("id")
                name = entry.get("name")
                platform = entry.get("platform")
                score = entry.get("composite_score")
                if not (isinstance(rank, int) and rank == expected_rank):
                    ranks_ok = False
                    break
                if not (isinstance(cid, str) and isinstance(name, str) and isinstance(platform, str)):
                    ranks_ok = False
                    break
                if not (is_number(score) and 0 <= float(score) <= 100):
                    ranks_ok = False
                    break
                if prev_score is not None and float(score) > float(prev_score):
                    scores_ok = False
                    break
                prev_score = float(score)
                expected_rank += 1
            if ranks_ok and scores_ok:
                checks["leaderboard_file_valid"] = True

    # Trending watchlist
    trending = read_json(trending_path)
    if isinstance(trending, dict):
        topics = trending.get("topics")
        rising = trending.get("rising_agents")
        timestamp = trending.get("timestamp")
        topics_ok = isinstance(topics, list) and len(topics) >= 3
        rising_ok = isinstance(rising, list) and len(rising) >= 1
        ts_ok = is_iso8601_like(timestamp) if isinstance(timestamp, str) else False
        if topics_ok and rising_ok and ts_ok:
            details_ok = True
            for t in topics:
                if not isinstance(t, dict):
                    details_ok = False
                    break
                if not (isinstance(t.get("topic"), str)):
                    details_ok = False
                    break
                pc = t.get("posts_count")
                if not (isinstance(pc, int) and pc >= 0):
                    details_ok = False
                    break
                if t.get("sentiment") not in {"positive", "neutral", "negative"}:
                    details_ok = False
                    break
            if details_ok:
                for a in rising:
                    if not isinstance(a, dict):
                        details_ok = False
                        break
                    if not (isinstance(a.get("id"), str) and isinstance(a.get("name"), str) and is_number(a.get("score_change"))):
                        details_ok = False
                        break
            if details_ok:
                checks["trending_file_valid"] = True

    # Dossier
    dossier = read_json(dossier_path)
    if isinstance(dossier, dict):
        id_ok = isinstance(dossier.get("id"), str)
        name_ok = isinstance(dossier.get("name"), str)
        platform_ok = isinstance(dossier.get("platform"), str)
        handle_ok = isinstance(dossier.get("handle"), str)
        bio_ok = isinstance(dossier.get("bio"), str)
        rep = dossier.get("reputation")
        rep_ok = isinstance(rep, dict) and is_number(rep.get("composite_score")) and isinstance(rep.get("breakdown"), dict) and \
                 ("security_record" in rep.get("breakdown")) and ("longevity" in rep.get("breakdown"))
        metrics = dossier.get("metrics")
        metrics_ok = isinstance(metrics, dict) and all(k in metrics for k in ["posts_count", "followers", "following", "avg_engagement"]) and \
                     is_number(metrics.get("posts_count")) and is_number(metrics.get("followers")) and is_number(metrics.get("following")) and is_number(metrics.get("avg_engagement"))
        ap_ok = isinstance(dossier.get("active_platforms"), list)
        last_ok = is_iso8601_like(dossier.get("last_activity")) if isinstance(dossier.get("last_activity"), str) else False
        first_ok = is_iso8601_like(dossier.get("first_seen")) if isinstance(dossier.get("first_seen"), str) else False
        upd_ok = is_iso8601_like(dossier.get("updated_at")) if isinstance(dossier.get("updated_at"), str) else False

        if id_ok and name_ok and platform_ok and handle_ok and bio_ok and rep_ok and metrics_ok and ap_ok and last_ok and first_ok and upd_ok:
            checks["dossier_file_valid"] = True

            # Consistency with portfolio
            did = dossier.get("id")
            dscore = None
            try:
                dscore = float(rep.get("composite_score")) if rep else None
            except Exception:
                dscore = None
            in_portfolio = did in portfolio_ids
            max_equal = (portfolio_max_score is not None and dscore is not None and abs(float(dscore) - float(portfolio_max_score)) < 1e-9)
            if in_portfolio and max_equal:
                checks["dossier_consistent_with_portfolio"] = True

    # Audit readme
    audit_content = read_text(audit_path)
    if isinstance(audit_content, str):
        checks["audit_file_exists"] = True
        required_sections = ["Methodology", "Applied Filters", "Decision Framework", "Findings", "Risks", "Next steps"]
        if all(section in audit_content for section in required_sections):
            checks["audit_sections_present"] = True
        # Shortlist size line
        m = re.search(r'(?m)^Shortlist size:\s*(\d+)\s*$', audit_content)
        if m is not None and isinstance(portfolio, dict) and isinstance(portfolio.get("candidates"), list):
            try:
                val = int(m.group(1))
                if val == len(portfolio.get("candidates")):
                    checks["audit_shortlist_size_matches"] = True
            except Exception:
                pass

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if no output files exist, ensure reward 0.0
    output_files_exist = any(os.path.exists(os.path.join(output_dir, fname)) for fname in [
        "portfolio_candidates.json", "risk_register.csv", "identity_links.jsonl",
        "leaderboard_snapshot.json", "trending_watchlist.json", "dossier.json", "audit_readme.md"
    ])
    if not output_files_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()