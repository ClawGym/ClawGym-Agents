import json
import os
import re
import sys
from datetime import datetime

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Paths
    md_path = os.path.join(output_dir, "skills", "mindgraph", "mindskills", "knockout-test", "results", "ai-ops-co-pilot.md")
    report_path = os.path.join(output_dir, "mindgraph_report.json")
    context_path = os.path.join(input_dir, "context.json")
    idea_path = os.path.join(input_dir, "idea.md")  # reference only

    checks = {
        "md_exists": False,
        "json_exists": False,
        "frontmatter_present": False,
        "frontmatter_mindskill_ok": False,
        "frontmatter_subject_ok": False,
        "frontmatter_date_ok": False,
        "frontmatter_verdict_ok": False,
        "has_round1": False,
        "has_round2": False,
        "has_round3": False,
        "has_round4": False,
        "has_connections": False,
        "has_change_my_mind_section_if_required": False,
        "wikilinks_count_ge_8": False,
        "competitors_all_linked": False,
        "markets_two_linked": False,
        "json_valid": False,
        "json_keys_ok": False,
        "json_wikilinks_match": False,
        "json_unique_count_ok": False,
        "json_unique_ge_8": False,
    }

    # Helper regex
    wikilink_re = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]")

    # Load context.json (reference)
    context_competitors = []
    context_markets = []
    try:
        if os.path.isfile(context_path):
            with open(context_path, "r", encoding="utf-8") as f:
                ctx = json.load(f)
            if isinstance(ctx, dict):
                if isinstance(ctx.get("competitors"), list):
                    context_competitors = [str(x) for x in ctx.get("competitors") if isinstance(x, (str, int, float))]
                if isinstance(ctx.get("markets"), list):
                    context_markets = [str(x) for x in ctx.get("markets") if isinstance(x, (str, int, float))]
    except Exception:
        # If context cannot be read or parsed, leave lists empty; related checks will remain False
        context_competitors = []
        context_markets = []

    # Parse markdown file
    md_content = ""
    frontmatter = {}
    body = ""
    verdict_norm = None
    if os.path.isfile(md_path):
        checks["md_exists"] = True
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
        except Exception:
            md_content = ""

        # Extract frontmatter at top delimited by '---'
        fm_present = False
        fm_text = ""
        if md_content.startswith("\ufeff"):
            md_content = md_content[1:]
        lines = md_content.splitlines()
        if len(lines) >= 3 and lines[0].strip() == "---":
            # find closing '---' on a line by itself
            end_idx = None
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    end_idx = i
                    break
            if end_idx is not None:
                fm_present = True
                fm_text = "\n".join(lines[1:end_idx])
                body = "\n".join(lines[end_idx+1:])
        checks["frontmatter_present"] = fm_present

        # Parse frontmatter keys: mindskill, subject, date, verdict
        if fm_present:
            frontmatter = {}
            for raw_line in fm_text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    key = k.strip().lower()
                    val = v.strip().strip('"').strip("'")
                    frontmatter[key] = val

            # mindskill
            mindskill_val = frontmatter.get("mindskill", "")
            if isinstance(mindskill_val, str) and mindskill_val.strip().lower() == "knockout-test":
                checks["frontmatter_mindskill_ok"] = True

            # subject
            subject_val = frontmatter.get("subject", "")
            if isinstance(subject_val, str) and subject_val.strip() == "AI Ops Co-pilot":
                checks["frontmatter_subject_ok"] = True

            # date
            date_val = frontmatter.get("date", "")
            if isinstance(date_val, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_val.strip()):
                try:
                    datetime.strptime(date_val.strip(), "%Y-%m-%d")
                    checks["frontmatter_date_ok"] = True
                except Exception:
                    pass

            # verdict
            verdict_val = frontmatter.get("verdict", "")
            if isinstance(verdict_val, str):
                # Normalize by stripping non A-Z letters, uppercase
                cleaned = "".join([ch for ch in verdict_val.upper() if "A" <= ch <= "Z"])
                verdict_norm = cleaned
                if cleaned in {"BUILD", "PIVOT", "PARK"}:
                    checks["frontmatter_verdict_ok"] = True

        # Section checks in body
        body_l = body.lower() if body else ""
        if "round 1" in body_l:
            checks["has_round1"] = True
        if "round 2" in body_l:
            checks["has_round2"] = True
        if "round 3" in body_l:
            checks["has_round3"] = True
        if "round 4" in body_l:
            checks["has_round4"] = True
        if "connections" in body_l:
            checks["has_connections"] = True

        # "What would change my mind" subsection requirement for PIVOT/PARK
        change_check = False
        if verdict_norm in {"PIVOT", "PARK"}:
            # Find section
            pattern = re.compile(r"what would change my mind", re.IGNORECASE)
            m = pattern.search(body or "")
            if m:
                # Ensure at least one non-empty line after the section header line
                # Determine line index of match
                post = (body or "")[m.end():]
                # look for at least one non-whitespace character beyond the header
                # but ensure it's not immediately empty
                post_lines = post.splitlines()
                found_content = False
                for ln in post_lines:
                    if ln.strip() != "":
                        found_content = True
                        break
                if found_content:
                    change_check = True
        else:
            # Not required if verdict is BUILD or invalid
            change_check = True if verdict_norm == "BUILD" else False
        checks["has_change_my_mind_section_if_required"] = change_check

        # Wikilinks
        wikilinks = []
        if md_content:
            wikilinks = wikilink_re.findall(md_content)
        # Unique set as they appear (case-sensitive uniqueness not specified; we will consider case-insensitive for counting)
        unique_wikilinks_set = set([w.strip() for w in wikilinks if w.strip() != ""])
        if len(unique_wikilinks_set) >= 8:
            checks["wikilinks_count_ge_8"] = True

        # Competitors and markets linked
        def norm(s):
            return " ".join(str(s).strip().lower().split())

        wikilinks_norm = {norm(w) for w in unique_wikilinks_set}
        # Competitors: all must be present as wikilinks
        if context_competitors:
            comp_norms = {norm(c) for c in context_competitors}
            if comp_norms and comp_norms.issubset(wikilinks_norm):
                checks["competitors_all_linked"] = True
        # Markets: at least two terms linked
        if context_markets:
            market_norms = [norm(m) for m in context_markets]
            linked_markets = [m for m in market_norms if m in wikilinks_norm]
            if len(set(linked_markets)) >= 2:
                checks["markets_two_linked"] = True

    # Validate JSON report
    if os.path.isfile(report_path):
        checks["json_exists"] = True
        json_data = None
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            checks["json_valid"] = isinstance(json_data, dict)
        except Exception:
            json_data = None

        if isinstance(json_data, dict):
            has_keys = ("unique_wikilinks" in json_data and "wikilinks" in json_data)
            if has_keys and isinstance(json_data.get("unique_wikilinks"), int) and isinstance(json_data.get("wikilinks"), list):
                # Ensure all elements in wikilinks are strings
                if all(isinstance(x, str) for x in json_data.get("wikilinks")):
                    checks["json_keys_ok"] = True

                    # If markdown was parsed, compare sets
                    md_links_set = set()
                    if checks["md_exists"]:
                        # Recompute wikilinks from markdown content
                        try:
                            with open(md_path, "r", encoding="utf-8") as f:
                                md_text_for_json = f.read()
                            md_links = wikilink_re.findall(md_text_for_json)
                            md_links_set = set([w.strip() for w in md_links if w.strip() != ""])
                        except Exception:
                            md_links_set = set()

                    json_links_list = json_data.get("wikilinks", [])
                    json_links_set = set([x.strip() for x in json_links_list if isinstance(x, str)])
                    if md_links_set and json_links_set == md_links_set:
                        checks["json_wikilinks_match"] = True

                    # unique count correctness
                    if json_data.get("unique_wikilinks") == len(json_links_set):
                        checks["json_unique_count_ok"] = True

                    if json_data.get("unique_wikilinks", 0) >= 8:
                        checks["json_unique_ge_8"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure baseline: if required outputs missing, reward must be 0.0
    # If both primary artifacts missing or md missing, keep as computed (likely 0); enforce zero if md missing
    if not checks["md_exists"]:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()