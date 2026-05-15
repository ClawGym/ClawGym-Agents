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

def file_nonempty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def has_link(content, target):
    if content is None:
        return False
    # Look for anchor tags with href pointing to the target. Support single/double/unquoted (basic).
    patterns = [
        r'<a[^>]*\bhref\s*=\s*"' + re.escape(target) + r'"',
        r"<a[^>]*\bhref\s*=\s*'" + re.escape(target) + r"'",
        r'<a[^>]*\bhref\s*=\s*' + re.escape(target) + r'([>\s])',
    ]
    return any(re.search(p, content, flags=re.IGNORECASE) for p in patterns)

def all_nav_links_present(content):
    return (has_link(content, "index.html") and
            has_link(content, "docs.html") and
            has_link(content, "contact.html"))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    index_path = os.path.join(output_dir, "site", "index.html")
    docs_path = os.path.join(output_dir, "site", "docs.html")
    contact_path = os.path.join(output_dir, "site", "contact.html")
    serve_instructions_path = os.path.join(output_dir, "serve_instructions.md")
    urls_json_path = os.path.join(output_dir, "urls.json")
    server_log_path = os.path.join(output_dir, "server_log.txt")

    checks = {
        "has_index_html": False,
        "has_docs_html": False,
        "has_contact_html": False,
        "has_serve_instructions": False,
        "has_urls_json": False,
        "has_server_log": False,
        "index_has_all_nav_links": False,
        "docs_has_all_nav_links": False,
        "contact_has_all_nav_links": False,
        "instructions_mentions_directory": False,
        "instructions_has_8000_url": False,
        "instructions_has_9000_url": False,
        "urls_json_valid": False,
        "urls_json_has_expected_keys": False,
        "urls_json_port8000_exact": False,
        "urls_json_port9000_exact": False,
        "server_log_mentions_ports": False,
        "server_log_has_localhost_url": False,
    }

    # Existence and non-empty checks
    if file_nonempty(index_path):
        checks["has_index_html"] = True
        index_content = read_text(index_path)
        if index_content and all_nav_links_present(index_content):
            checks["index_has_all_nav_links"] = True
    else:
        index_content = None

    if file_nonempty(docs_path):
        checks["has_docs_html"] = True
        docs_content = read_text(docs_path)
        if docs_content and all_nav_links_present(docs_content):
            checks["docs_has_all_nav_links"] = True
    else:
        docs_content = None

    if file_nonempty(contact_path):
        checks["has_contact_html"] = True
        contact_content = read_text(contact_path)
        if contact_content and all_nav_links_present(contact_content):
            checks["contact_has_all_nav_links"] = True
    else:
        contact_content = None

    serve_instructions_content = None
    if file_nonempty(serve_instructions_path):
        checks["has_serve_instructions"] = True
        serve_instructions_content = read_text(serve_instructions_path)
        if serve_instructions_content:
            # Must mention the directory "output/site"
            if "output/site" in serve_instructions_content:
                checks["instructions_mentions_directory"] = True
            # Must include the exact URLs for index.html on ports 8000 and 9000
            if "http://localhost:8000/index.html" in serve_instructions_content:
                checks["instructions_has_8000_url"] = True
            if "http://localhost:9000/index.html" in serve_instructions_content:
                checks["instructions_has_9000_url"] = True

    # urls.json checks
    urls_data = None
    if file_nonempty(urls_json_path):
        checks["has_urls_json"] = True
        try:
            with open(urls_json_path, "r", encoding="utf-8") as f:
                urls_data = json.load(f)
            if isinstance(urls_data, dict):
                checks["urls_json_valid"] = True
                expected_keys = {"port8000", "port9000"}
                if set(urls_data.keys()) == expected_keys:
                    checks["urls_json_has_expected_keys"] = True

                # Validate arrays for each port if keys are as expected
                for port_key, port in [("port8000", 8000), ("port9000", 9000)]:
                    if port_key in urls_data and isinstance(urls_data[port_key], list):
                        arr = urls_data[port_key]
                        expected_set = {
                            f"http://localhost:{port}/index.html",
                            f"http://localhost:{port}/docs.html",
                            f"http://localhost:{port}/contact.html",
                        }
                        if len(arr) == 3 and set(arr) == expected_set:
                            if port_key == "port8000":
                                checks["urls_json_port8000_exact"] = True
                            else:
                                checks["urls_json_port9000_exact"] = True
        except Exception:
            # Parsing failed; leave related checks as False
            pass

    # server_log checks
    server_log_content = None
    if file_nonempty(server_log_path):
        checks["has_server_log"] = True
        server_log_content = read_text(server_log_path)
        if server_log_content:
            if ("8000" in server_log_content) and ("9000" in server_log_content):
                checks["server_log_mentions_ports"] = True
            if "http://localhost:" in server_log_content:
                checks["server_log_has_localhost_url"] = True

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # Reward is proportion of checks passed; if no required outputs, it will be 0.0
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print single JSON object as last line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()