import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks - all False until confirmed
    checks = {
        "evidence_exists": False,
        "email_exists": False,
        "evidence_json_valid": False,
        "evidence_company_ok": False,
        "evidence_decision_maker_name_nonempty": False,
        "evidence_decision_maker_title_nonempty": False,
        "evidence_facts_min3": False,
        "evidence_fact_items_valid": False,
        "evidence_fact_sources_3plus_unique": False,
        "evidence_email_path_ok": False,
        "email_subject_line_ok": False,
        "email_contains_decision_maker_name": False,
        "email_contains_i_noticed": False,
        "email_contains_revenue_keyword": False,
        "email_has_3plus_source_refs": False,
        "email_contains_all_evidence_sources": False,
    }

    # Paths
    evidence_path = os.path.join(output_dir, "evidence.json")
    email_path = os.path.join(output_dir, "email.md")

    # Allowed sources
    allowed_filenames = {
        "company_site.html",
        "about.md",
        "blog_snippet.md",
        "news.csv",
        "linkedin_search_results.txt",
    }
    allowed_sources = {f"input/{fn}" for fn in allowed_filenames}

    evidence = None
    email_content = None

    # Check evidence.json existence and validity
    if os.path.isfile(evidence_path):
        checks["evidence_exists"] = True
        evidence = load_json(evidence_path)
        if isinstance(evidence, dict):
            checks["evidence_json_valid"] = True

            # Company check
            company = evidence.get("company")
            if isinstance(company, str) and company == "HelioAnalytics":
                checks["evidence_company_ok"] = True

            # Decision maker checks
            dm = evidence.get("decision_maker")
            if isinstance(dm, dict):
                name = dm.get("name")
                title = dm.get("title")
                if isinstance(name, str) and name.strip():
                    checks["evidence_decision_maker_name_nonempty"] = True
                if isinstance(title, str) and title.strip():
                    checks["evidence_decision_maker_title_nonempty"] = True
            else:
                name = None

            # Facts checks
            facts = evidence.get("facts")
            facts_valid = True
            sources = []
            if isinstance(facts, list) and len(facts) >= 3:
                checks["evidence_facts_min3"] = True
                for fact in facts:
                    if not isinstance(fact, dict):
                        facts_valid = False
                        break
                    text = fact.get("text")
                    source = fact.get("source")
                    if not (isinstance(text, str) and text.strip()):
                        facts_valid = False
                        break
                    if not (isinstance(source, str) and source.startswith("input/")):
                        facts_valid = False
                        break
                    if source not in allowed_sources:
                        facts_valid = False
                        break
                    sources.append(source)
                if facts_valid:
                    checks["evidence_fact_items_valid"] = True
                    # Unique sources >= 3
                    if len(set(sources)) >= 3:
                        checks["evidence_fact_sources_3plus_unique"] = True
            # evidence_email_path_ok
            ep = evidence.get("email_path")
            if isinstance(ep, str) and ep == "output/email.md":
                checks["evidence_email_path_ok"] = True
        else:
            # evidence remained None or invalid
            name = None
            sources = []
    else:
        name = None
        sources = []

    # Check email.md presence and content requirements
    if os.path.isfile(email_path):
        checks["email_exists"] = True
        email_content = read_text(email_path)
        if isinstance(email_content, str):
            # Subject line check: line starting with "Subject:" and containing "HelioAnalytics" (case-insensitive)
            subject_ok = False
            for line in email_content.splitlines():
                stripped = line.lstrip()
                if stripped.startswith("Subject:"):
                    if "helioanalytics" in stripped.lower():
                        subject_ok = True
                        break
            if subject_ok:
                checks["email_subject_line_ok"] = True

            # Contains decision maker full name (from evidence)
            if name and isinstance(name, str) and name.strip():
                if name in email_content:
                    checks["email_contains_decision_maker_name"] = True

            # Contains "I noticed" (case-insensitive)
            if "i noticed" in email_content.lower():
                checks["email_contains_i_noticed"] = True

            # Contains one of revenue, conversion, churn (case-insensitive)
            lc = email_content.lower()
            if any(k in lc for k in ["revenue", "conversion", "churn"]):
                checks["email_contains_revenue_keyword"] = True

            # At least 3 bracketed source refs in exact format: [source: input/<filename>]
            # Restrict to allowed filenames to avoid counting invalid refs
            pattern = r"\[source: input/(company_site\.html|about\.md|blog_snippet\.md|news\.csv|linkedin_search_results\.txt)\]"
            refs = re.findall(pattern, email_content)
            if len(refs) >= 3:
                checks["email_has_3plus_source_refs"] = True

            # Every source listed in evidence.json facts appears in the email content in exact bracket format
            if evidence and checks["evidence_fact_items_valid"]:
                all_present = True
                for src in set(sources):
                    token = f"[source: {src}]"
                    if token not in email_content:
                        all_present = False
                        break
                if all_present:
                    checks["email_contains_all_evidence_sources"] = True

    # Compute reward as fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure baseline with no outputs gets 0.0 (already satisfied by fraction)
    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()