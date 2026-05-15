#!/usr/bin/env python3
import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def id_present(text, the_id):
    # Ensure the ID appears as a standalone token (not embedded in a longer alphanumeric string)
    pattern = r'(?<![A-Za-z0-9])' + re.escape(the_id) + r'(?![A-Za-z0-9])'
    return re.search(pattern, text) is not None

def get_section(text, header_name, all_headers):
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header_name:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    # Find next header after start
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip() in all_headers:
            end_idx = j
            break
    section_text = "\n".join(lines[start_idx:end_idx])
    return section_text

def compute_okrs_metrics(data):
    # Return dict with orphans (list of team okr ids), gaps (list of company ids),
    # overindexed (list of company ids), conflicts (set of tuple pairs), totals
    if not data or "company" not in data or "teams" not in data:
        return {
            "company_ids": set(),
            "orphans": [],
            "gaps": [],
            "overindexed": [],
            "conflicts": set(),
            "total_team_okrs": 0,
            "total_company_okrs": 0,
        }
    company_okrs = data.get("company", {}).get("okrs", []) or []
    company_ids = set()
    for okr in company_okrs:
        cid = okr.get("id")
        if isinstance(cid, str):
            company_ids.add(cid)

    teams = data.get("teams", []) or []

    # Orphans and coverage mapping
    orphans = []
    coverage = {cid: [] for cid in company_ids}
    total_team_okrs = 0
    for team in teams:
        okrs = team.get("okrs", []) or []
        total_team_okrs += len(okrs)
        for okr in okrs:
            okr_id = okr.get("id")
            parent = okr.get("parent_company_okr_id")
            if parent is None or parent not in company_ids:
                if isinstance(okr_id, str):
                    orphans.append(okr_id)
            else:
                coverage[parent].append({"team": team.get("name", ""), "okr_id": okr_id})

    # Gaps and over-indexed
    gaps = []
    overindexed = []
    for cid in company_ids:
        supporting = coverage.get(cid, [])
        if len(supporting) == 0:
            gaps.append(cid)
        if len(supporting) >= 4:
            overindexed.append(cid)

    # Conflicts
    conflicts_pairs = set()
    # known_conflicts
    for c in data.get("known_conflicts", []) or []:
        a = c.get("okr_a")
        b = c.get("okr_b")
        if isinstance(a, str) and isinstance(b, str) and a and b and a != b:
            pair = tuple(sorted((a, b)))
            conflicts_pairs.add(pair)
    # potential_conflicts from each OKR
    for team in teams:
        okrs = team.get("okrs", []) or []
        for okr in okrs:
            a = okr.get("id")
            if not isinstance(a, str) or not a:
                continue
            for b in okr.get("potential_conflicts", []) or []:
                if isinstance(b, str) and b and a != b:
                    pair = tuple(sorted((a, b)))
                    conflicts_pairs.add(pair)

    return {
        "company_ids": company_ids,
        "orphans": orphans,
        "gaps": gaps,
        "overindexed": overindexed,
        "conflicts": conflicts_pairs,
        "total_team_okrs": total_team_okrs,
        "total_company_okrs": len(company_ids),
    }

def compute_score(orphans_count, total_team_okrs, gaps_count, total_company_okrs, conflicts_count):
    denom_team = max(total_team_okrs, 1)
    denom_company = max(total_company_okrs, 1)
    orphan_penalty = 30.0 * (orphans_count / denom_team)
    gap_penalty = 30.0 * (gaps_count / denom_company)
    conflict_penalty = min(10.0 * conflicts_count, 30.0)
    raw = 100.0 - (orphan_penalty + gap_penalty + conflict_penalty)
    score = max(0.0, raw)
    return int(round(score))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        # Report checks
        "has_alignment_report": False,
        "score_line_correct": False,
        "orphans_listed": False,
        "gaps_listed_in_section": False,
        "overindexed_listed_in_section": False,
        "conflict_pair_listed_in_section": False,
        # Plan checks
        "has_realignment_plan": False,
        "plan_length_ok": False,
        "plan_mentions_all_orphans": False,
        "plan_mentions_all_gaps": False,
        "plan_has_guardrail_and_ownership": False,
        "plan_has_cadence_keywords": False,
    }

    # Load input data
    input_path = os.path.join(input_dir, "okrs.json")
    data = read_json(input_path)
    metrics = compute_okrs_metrics(data)

    orphans = metrics["orphans"]
    gaps = metrics["gaps"]
    overindexed = metrics["overindexed"]
    conflicts_pairs = metrics["conflicts"]
    total_team_okrs = metrics["total_team_okrs"]
    total_company_okrs = metrics["total_company_okrs"]

    computed_score = compute_score(
        len(orphans), total_team_okrs, len(gaps), total_company_okrs, len(conflicts_pairs)
    )

    # Check alignment report
    report_path = os.path.join(output_dir, "alignment_report.txt")
    report_text = ""
    if os.path.isfile(report_path):
        checks["has_alignment_report"] = True
        try:
            with open(report_path, "r", encoding="utf-8", errors="replace") as f:
                report_text = f.read()
        except Exception:
            report_text = ""

        # Score line regex
        m = re.search(r'^\s*Alignment Score:\s*(\d{1,3})\s*out of\s*100\s*$', report_text, flags=re.MULTILINE)
        if m:
            try:
                reported = int(m.group(1))
                if reported == computed_score:
                    checks["score_line_correct"] = True
            except Exception:
                pass

        # Orphans listed anywhere in report
        if orphans:
            if all(id_present(report_text, oid) for oid in orphans):
                checks["orphans_listed"] = True
        else:
            # No orphans expected → vacuously true
            checks["orphans_listed"] = True

        # Sections parsing
        headers = [
            "Summary",
            "Orphan Team OKRs",
            "Conflicting OKRs",
            "Coverage Gaps",
            "Over-indexed Company OKRs",
            "Recommendations at a glance",
        ]

        coverage_section = get_section(report_text, "Coverage Gaps", headers)
        if gaps:
            if all(id_present(coverage_section, gid) for gid in gaps):
                checks["gaps_listed_in_section"] = True
        else:
            checks["gaps_listed_in_section"] = True

        overidx_section = get_section(report_text, "Over-indexed Company OKRs", headers)
        if overindexed:
            if all(id_present(overidx_section, cid) for cid in overindexed):
                checks["overindexed_listed_in_section"] = True
        else:
            checks["overindexed_listed_in_section"] = True

        conflicts_section = get_section(report_text, "Conflicting OKRs", headers)
        conflict_listed = False
        if conflicts_pairs:
            for a, b in conflicts_pairs:
                if id_present(conflicts_section, a) and id_present(conflicts_section, b):
                    conflict_listed = True
                    break
        # If there are no conflicts expected, consider this check true (nothing to list)
        checks["conflict_pair_listed_in_section"] = conflict_listed or (len(conflicts_pairs) == 0)

    # Check realignment plan
    plan_path = os.path.join(output_dir, "realignment_plan.md")
    plan_text = ""
    if os.path.isfile(plan_path):
        checks["has_realignment_plan"] = True
        try:
            with open(plan_path, "r", encoding="utf-8", errors="replace") as f:
                plan_text = f.read()
        except Exception:
            plan_text = ""

        # Length: at least 500 words and >= 2500 characters
        words = re.findall(r'\b\w+\b', plan_text)
        if len(plan_text) >= 2500 and len(words) >= 500:
            checks["plan_length_ok"] = True

        # Mentions all orphan OKR IDs
        if orphans:
            if all(id_present(plan_text, oid) for oid in orphans):
                checks["plan_mentions_all_orphans"] = True
        else:
            checks["plan_mentions_all_orphans"] = True

        # Mentions all gap company OKR IDs
        if gaps:
            if all(id_present(plan_text, gid) for gid in gaps):
                checks["plan_mentions_all_gaps"] = True
        else:
            checks["plan_mentions_all_gaps"] = True

        # Contains "guardrail" and ("owner" or "ownership")
        lt = plan_text.lower()
        if ("guardrail" in lt) and (("owner" in lt) or ("ownership" in lt)):
            checks["plan_has_guardrail_and_ownership"] = True

        # Cadence keywords: at least one of "workshop", "quarterly", "90-day"
        cadence = ("workshop" in lt) or ("quarterly" in lt) or ("90-day" in lt)
        if cadence:
            checks["plan_has_cadence_keywords"] = True

    # Compute reward
    # No-op baseline: if output/ is empty or both artifacts missing, reward must be 0.0
    if not checks["has_alignment_report"] and not checks["has_realignment_plan"]:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print single JSON line
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()