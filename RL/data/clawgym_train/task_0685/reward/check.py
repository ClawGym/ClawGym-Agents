import json
import os
import re
import sys
from typing import Dict, Any, Tuple, Set, List

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def validate_search_json(data: Any) -> Tuple[bool, Set[str]]:
    """
    Validates the search JSON structure and returns (is_valid, high_trust_urls)
    """
    high_trust_urls: Set[str] = set()
    if not isinstance(data, dict):
        return False, high_trust_urls

    # Required top-level keys
    for k in ["query", "count", "disclaimer", "security", "results"]:
        if k not in data:
            return False, high_trust_urls

    if not isinstance(data["query"], str):
        return False, high_trust_urls
    if not is_number(data["count"]):
        return False, high_trust_urls
    if not isinstance(data["disclaimer"], str):
        return False, high_trust_urls
    if not isinstance(data["security"], str):
        return False, high_trust_urls
    if not isinstance(data["results"], list):
        return False, high_trust_urls

    for item in data["results"]:
        if not isinstance(item, dict):
            return False, high_trust_urls
        for k in ["title", "url", "snippet", "trust"]:
            if k not in item:
                return False, high_trust_urls
        if not isinstance(item["title"], str):
            return False, high_trust_urls
        if not isinstance(item["url"], str):
            return False, high_trust_urls
        if not isinstance(item["snippet"], str):
            return False, high_trust_urls
        trust = item["trust"]
        if not isinstance(trust, dict):
            return False, high_trust_urls
        for tk in ["score", "tier", "reason"]:
            if tk not in trust:
                return False, high_trust_urls
        if not is_number(trust["score"]):
            return False, high_trust_urls
        # Enforce score in [0,1]
        if trust["score"] < 0 or trust["score"] > 1:
            return False, high_trust_urls
        if not isinstance(trust["tier"], str):
            return False, high_trust_urls
        if not isinstance(trust["reason"], str):
            return False, high_trust_urls
        if trust["tier"].lower() == "high":
            high_trust_urls.add(item["url"])

    return True, high_trust_urls

def find_philosophy_file(meta_dir: str) -> str:
    """
    Finds a file matching YYYY-MM-DD-greenroof-analytics-philosophy.md
    Returns the absolute path if found, else empty string.
    """
    if not os.path.isdir(meta_dir):
        return ""
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-greenroof-analytics-philosophy\.md$")
    for name in os.listdir(meta_dir):
        if pattern.match(name):
            return os.path.join(meta_dir, name)
    return ""

def has_required_sections_once(content: str, sections: List[str]) -> bool:
    for s in sections:
        if content.count(s) != 1:
            return False
    return True

def extract_urls(content: str) -> Set[str]:
    # Simple URL regex; stop at whitespace or closing punctuation
    # Allow () and [] but stop before common trailing punctuation.
    url_pattern = re.compile(r"https?://[^\s<>\)\]\}]+")
    return set(url_pattern.findall(content))

def plan_has_headings(content: str, headings: List[str]) -> bool:
    for h in headings:
        # Look for markdown heading lines with the exact heading text
        pattern = re.compile(rf"^\s*#+\s*{re.escape(h)}\s*$", re.MULTILINE)
        if not pattern.search(content):
            return False
    return True

def strategy_headings_with_content(content: str, headings: List[str]) -> bool:
    lines = content.splitlines()
    # Build indexed lines for easier search
    for heading in headings:
        found_index = -1
        # Match either plain line equal to heading or markdown heading with hashes
        heading_regex = re.compile(rf"^\s*#*\s*{re.escape(heading)}\s*$")
        for idx, line in enumerate(lines):
            if heading_regex.match(line):
                found_index = idx
                break
        if found_index == -1:
            return False
        # Find next non-empty line after the heading
        content_line_index = -1
        for j in range(found_index + 1, len(lines)):
            if lines[j].strip() != "":
                content_line_index = j
                break
        if content_line_index == -1:
            return False
        # Ensure the next non-empty line is not another heading marker-only line
        next_line = lines[content_line_index]
        # Consider any line starting with '#' as a heading and thus not content
        if re.match(r"^\s*#+\s*\S", next_line):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks: Dict[str, bool] = {
        "search1_exists_and_valid": False,
        "search2_exists_and_valid": False,
        "has_high_trust_source": False,
        "philosophy_exists_with_correct_filename": False,
        "philosophy_has_required_sections_once_each": False,
        "philosophy_has_two_urls": False,
        "philosophy_cites_high_trust_url_from_searches": False,
        "plan_exists": False,
        "plan_has_required_headings": False,
        "company_dirs_exist": False,
        "strategy_exists": False,
        "strategy_has_required_headings_with_content": False,
    }

    # 1) Validate search JSONs
    research_dir = os.path.join(output_dir, "research")
    high_trust_urls_all: Set[str] = set()

    s1_path = os.path.join(research_dir, "search_1.json")
    s2_path = os.path.join(research_dir, "search_2.json")
    # Optional s3, but not required for passing
    s3_path = os.path.join(research_dir, "search_3.json")

    for label, path, key in [
        ("s1", s1_path, "search1_exists_and_valid"),
        ("s2", s2_path, "search2_exists_and_valid"),
    ]:
        ok, data = load_json(path)
        if ok:
            valid, high_urls = validate_search_json(data)
            if valid:
                checks[key] = True
                high_trust_urls_all.update(high_urls)

    # If optional search_3.json exists and is valid, include its high trust URLs for citation matching
    ok3, data3 = load_json(s3_path)
    if ok3:
        valid3, high_urls3 = validate_search_json(data3)
        if valid3:
            high_trust_urls_all.update(high_urls3)

    if len(high_trust_urls_all) > 0:
        checks["has_high_trust_source"] = True

    # 2) Philosophy document checks
    meta_dir = os.path.join(output_dir, "docs", "metaphysics")
    philosophy_path = find_philosophy_file(meta_dir)
    content_phil = ""
    if philosophy_path and os.path.isfile(philosophy_path):
        checks["philosophy_exists_with_correct_filename"] = True
        content_phil = read_text(philosophy_path)

        required_sections = [
            "I. Ontology",
            "II. Teleology",
            "III. Methodology",
            "IV. Boundaries",
            "V. Decision Criteria",
        ]
        if content_phil:
            if has_required_sections_once(content_phil, required_sections):
                checks["philosophy_has_required_sections_once_each"] = True
            urls_in_phil = extract_urls(content_phil)
            if len(urls_in_phil) >= 2:
                checks["philosophy_has_two_urls"] = True
            if any(u in high_trust_urls_all for u in urls_in_phil) and checks["philosophy_has_two_urls"]:
                checks["philosophy_cites_high_trust_url_from_searches"] = True

    # 3) Lean go-to-market plan
    plan_path = os.path.join(output_dir, "plan", "lean_go_to_market.md")
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_content = read_text(plan_path)
        required_plan_headings = ["MVP", "First Customers", "Pricing", "Marketing Plan"]
        if plan_content and plan_has_headings(plan_content, required_plan_headings):
            checks["plan_has_required_headings"] = True

    # 4) Company skeleton and strategy
    base_company_dir = os.path.join(output_dir, "company", "greenroof-analytics")
    deps = ["sales", "marketing", "operations", "hr", "accounting"]
    all_dirs_ok = True
    for d in deps:
        path_workers = os.path.join(base_company_dir, "departments", d, "supervisor", "workers")
        if not os.path.isdir(path_workers):
            all_dirs_ok = False
            break
    if all_dirs_ok:
        checks["company_dirs_exist"] = True

    strategy_path = os.path.join(base_company_dir, "strategy.md")
    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        strat_content = read_text(strategy_path)
        strat_headings = [
            "Big Obsessional Goal (BOG)",
            "Current Bottleneck",
            "Target Audience",
            "Positioning",
        ]
        if strat_content and strategy_headings_with_content(strat_content, strat_headings):
            checks["strategy_has_required_headings_with_content"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure baseline no-op yields exactly 0.0
    if not os.path.isdir(output_dir) or all(not v for v in checks.values()):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()