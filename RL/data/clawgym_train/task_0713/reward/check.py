import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_owner_repo(s):
    if not isinstance(s, str):
        return False
    if "http" in s.lower():
        return False
    # Pattern: one slash, no additional slashes
    return re.fullmatch(r"[^/]+/[^/]+", s) is not None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "files_exist_skills_catalog": False,
        "files_exist_installation_plan": False,
        "files_exist_governance_md": False,
        "files_exist_readme_md": False,
        "skills_catalog_json_valid": False,
        "skills_catalog_items_schema_valid": False,
        "coverage_official_partner_present": False,
        "coverage_community_present": False,
        "category_distinct_count_at_least_3": False,
        "category_has_devops": False,
        "category_has_security": False,
        "installation_plan_valid_json_structure": False,
        "phases_present_nonempty": False,
        "all_catalog_skills_in_phases": False,
        "governance_contains_keywords": False,
        "readme_has_5_bullets_with_owner_repo": False,
    }

    # Paths
    skills_catalog_path = os.path.join(output_dir, "skills_catalog.json")
    installation_plan_path = os.path.join(output_dir, "installation_plan.json")
    governance_md_path = os.path.join(output_dir, "governance.md")
    readme_md_path = os.path.join(output_dir, "README.md")

    # Existence checks
    if os.path.isfile(skills_catalog_path):
        checks["files_exist_skills_catalog"] = True
    if os.path.isfile(installation_plan_path):
        checks["files_exist_installation_plan"] = True
    if os.path.isfile(governance_md_path):
        checks["files_exist_governance_md"] = True
    if os.path.isfile(readme_md_path):
        checks["files_exist_readme_md"] = True

    # Load and validate skills_catalog.json
    skills_catalog = None
    if checks["files_exist_skills_catalog"]:
        data, err = load_json_file(skills_catalog_path)
        if isinstance(data, list):
            # Length between 8 and 12 inclusive
            if 8 <= len(data) <= 12:
                checks["skills_catalog_json_valid"] = True
                skills_catalog = data

    # Schema validation
    catalog_owner_repos = set()
    categories_seen = set()
    if checks["skills_catalog_json_valid"] and skills_catalog is not None:
        valid = True
        has_devops = False
        has_security = False

        allowed_categories = {"frontend", "devops", "security", "database", "payments", "misc"}
        allowed_source_types = {"official_partner", "community"}
        allowed_risk_levels = {"low", "medium", "high"}

        for item in skills_catalog:
            if not isinstance(item, dict):
                valid = False
                break
            # Required keys
            required_keys = ["name", "owner_repo", "category", "source_type", "use_cases",
                             "risk_level", "risk_notes", "rationale", "priority_score"]
            if any(k not in item for k in required_keys):
                valid = False
                break

            # Types and constraints
            if not isinstance(item["name"], str) or not item["name"].strip():
                valid = False
                break
            if not isinstance(item["owner_repo"], str) or not is_owner_repo(item["owner_repo"]):
                valid = False
                break
            if not isinstance(item["category"], str) or item["category"] not in allowed_categories:
                valid = False
                break
            if not isinstance(item["source_type"], str) or item["source_type"] not in allowed_source_types:
                valid = False
                break
            if not isinstance(item["use_cases"], list) or len(item["use_cases"]) < 2 or not all(isinstance(u, str) and u.strip() for u in item["use_cases"]):
                valid = False
                break
            if not isinstance(item["risk_level"], str) or item["risk_level"] not in allowed_risk_levels:
                valid = False
                break
            if not isinstance(item["risk_notes"], str) or len(item["risk_notes"]) < 30:
                valid = False
                break
            if not isinstance(item["rationale"], str) or len(item["rationale"]) < 50:
                valid = False
                break
            # Number between 0 and 100 inclusive
            pr = item["priority_score"]
            if not (isinstance(pr, int) or isinstance(pr, float)):
                valid = False
                break
            if pr < 0 or pr > 100:
                valid = False
                break

            # Collect for coverage
            catalog_owner_repos.add(item["owner_repo"])
            categories_seen.add(item["category"])
            if item["category"] == "devops":
                has_devops = True
            if item["category"] == "security":
                has_security = True

        if valid:
            checks["skills_catalog_items_schema_valid"] = True

            # Source coverage
            official_partners = {
                "anthropics/skills",
                "vercel-labs/agent-skills",
                "expo/skills",
                "remotion-dev/skills",
                "supabase/agent-skills",
                "stripe/ai",
            }
            community_collections = {
                "trailofbits/skills",
                "obra/superpowers",
                "wshobson/agents",
                "ComposioHQ/awesome-claude-skills",
                "langgenius/dify",
                "better-auth/skills",
                "elysiajs/skills",
                "rohitg00/kubectl-mcp-server",
            }
            if any(repo in official_partners for repo in catalog_owner_repos):
                checks["coverage_official_partner_present"] = True
            if any(repo in community_collections for repo in catalog_owner_repos):
                checks["coverage_community_present"] = True

            # Category coverage checks
            if len(categories_seen) >= 3:
                checks["category_distinct_count_at_least_3"] = True
            if has_devops:
                checks["category_has_devops"] = True
            if has_security:
                checks["category_has_security"] = True

    # Validate installation_plan.json
    installation_plan = None
    if checks["files_exist_installation_plan"]:
        plan_data, plan_err = load_json_file(installation_plan_path)
        if isinstance(plan_data, dict):
            required_phases = ["discovery", "poc", "canary", "production"]
            phases_ok = all(k in plan_data and isinstance(plan_data[k], dict) for k in required_phases)
            if phases_ok:
                checks["installation_plan_valid_json_structure"] = True
                # Phases non-empty and required keys
                nonempty_ok = True
                all_listed_skills = set()
                for phase in required_phases:
                    phase_obj = plan_data.get(phase, {})
                    # Required keys
                    if not isinstance(phase_obj.get("skills"), list):
                        nonempty_ok = False
                        break
                    if not isinstance(phase_obj.get("goals"), str):
                        nonempty_ok = False
                        break
                    if not isinstance(phase_obj.get("exit_criteria"), str):
                        nonempty_ok = False
                        break
                    # Non-empty checks
                    if len(phase_obj.get("skills", [])) == 0:
                        nonempty_ok = False
                        break
                    if len(phase_obj.get("goals", "").strip()) == 0:
                        nonempty_ok = False
                        break
                    if len(phase_obj.get("exit_criteria", "").strip()) == 0:
                        nonempty_ok = False
                        break
                    # Collect skills
                    for s in phase_obj.get("skills", []):
                        if isinstance(s, str):
                            all_listed_skills.add(s)
                if nonempty_ok:
                    checks["phases_present_nonempty"] = True

                # Coverage: every owner_repo from catalog appears in at least one phase
                if catalog_owner_repos:
                    if catalog_owner_repos.issubset(all_listed_skills):
                        checks["all_catalog_skills_in_phases"] = True
                else:
                    # If no catalog parsed, leave as False
                    pass

            installation_plan = plan_data

    # Governance keywords
    if checks["files_exist_governance_md"]:
        gov_text, gov_err = read_text(governance_md_path)
        if isinstance(gov_text, str):
            content_lower = gov_text.lower()
            needed_keywords = ["rollback", "approval", "risk", "security", "license", "monitoring"]
            if all(k in content_lower for k in needed_keywords):
                checks["governance_contains_keywords"] = True

    # README bullets with owner/repo
    if checks["files_exist_readme_md"]:
        readme_text, readme_err = read_text(readme_md_path)
        if isinstance(readme_text, str):
            lines = readme_text.splitlines()
            bullet_pattern = re.compile(r"^\s*[-*]\s+.*\b[^/\s]+/[^/\s]+\b")
            count = 0
            for line in lines:
                if bullet_pattern.search(line):
                    count += 1
            if count >= 5:
                checks["readme_has_5_bullets_with_owner_repo"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()