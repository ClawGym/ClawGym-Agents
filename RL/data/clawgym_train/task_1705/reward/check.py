import json
import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def find_function_body(source: str, func_name: str) -> Optional[str]:
    # Very simple PHP function body extractor based on brace counting.
    pattern = re.compile(rf"\bfunction\s+{re.escape(func_name)}\s*\(", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(source)
    if not m:
        return None
    start = m.end()
    brace_start = source.find("{", start)
    if brace_start == -1:
        return None
    depth = 0
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start:i + 1]
    return None


def contains_regex(text: str, pattern: str, flags=0) -> bool:
    try:
        return re.search(pattern, text, flags) is not None
    except re.error:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "fetch_php_redis_integration_tokens": 0.0,
        "fetch_php_structure_intact": 0.0,
        "expensive_compute_unchanged": 0.0,
        "config_enabled_redis_and_ttl": 0.0,
        "config_after_is_copy": 0.0,
        "readme_section_replaced": 0.0,
        "readme_contains_exact_config_strings": 0.0,
        "readme_references_and_fallback_explained": 0.0,
        "changes_summary_complete": 0.0,
    }

    # Paths
    fetch_php = workspace / "src" / "fetch.php"
    config_json = workspace / "config" / "app.json"
    config_after_json = workspace / "output" / "config_after.json"
    readme_md = workspace / "README.md"
    changes_txt = workspace / "output" / "redis_changes.txt"

    # Read files
    fetch_text = read_text_safe(fetch_php) or ""
    readme_text = read_text_safe(readme_md) or ""
    cfg = load_json_safe(config_json)
    cfg_after = load_json_safe(config_after_json)

    # 1) src/fetch.php Redis integration tokens
    # Check for class_exists('Redis'), setEx() with $ttl, and 'key_prefix' usage
    has_class_exists = contains_regex(fetch_text, r"class_exists\s*\(\s*['\"]Redis['\"]\s*\)", flags=re.IGNORECASE)
    has_setex_call = contains_regex(fetch_text, r"->\s*setEx\s*\(", flags=re.IGNORECASE)
    has_setex_with_ttl = contains_regex(fetch_text, r"setEx\s*\([^)]*\$ttl[^)]*\)", flags=re.IGNORECASE)
    has_key_prefix_literal = "key_prefix" in fetch_text

    if fetch_text and has_class_exists and has_setex_call and has_key_prefix_literal:
        # Require TTL to be used in setEx as an added strictness
        if has_setex_with_ttl:
            scores["fetch_php_redis_integration_tokens"] = 1.0

    # 1b) Structure intact: functions exist (only meaningful when Redis integration is added)
    if scores["fetch_php_redis_integration_tokens"] > 0.0:
        exp_body = find_function_body(fetch_text, "expensiveCompute")
        loadcfg_body = find_function_body(fetch_text, "loadConfig")
        getval_body = find_function_body(fetch_text, "getValue")
        if exp_body and loadcfg_body and getval_body:
            # Also ensure $prefix is referenced beyond assignment inside getValue (heuristic)
            prefix_count = getval_body.count("$prefix")
            if prefix_count >= 2:
                scores["fetch_php_structure_intact"] = 1.0

        # 1c) expensiveCompute unchanged behavior: should hash sha256 of "value:" . $key
        if exp_body:
            has_sha256 = "sha256" in exp_body
            has_value_prefix = "value:" in exp_body
            has_hash_call = "hash(" in exp_body
            if has_sha256 and has_value_prefix and has_hash_call:
                scores["expensive_compute_unchanged"] = 1.0

    # 2) Config enabled redis and ttl_seconds 60, key_prefix cache:
    if isinstance(cfg, dict):
        try:
            backend = cfg.get("cache", {}).get("backend", None)
            ttl = cfg.get("cache", {}).get("ttl_seconds", None)
            prefix = cfg.get("cache", {}).get("key_prefix", None)
            if backend == "redis" and ttl == 60 and prefix == "cache:":
                scores["config_enabled_redis_and_ttl"] = 1.0
        except Exception:
            pass

    # 2b) output/config_after.json is a copy of final config
    if isinstance(cfg, dict) and isinstance(cfg_after, dict):
        try:
            if cfg == cfg_after:
                scores["config_after_is_copy"] = 1.0
        except Exception:
            pass

    # 3) README.md changes
    if readme_text:
        has_todo_section = "## Caching (TODO)" in readme_text
        has_placeholder = "Replace this section with a brief guide" in readme_text
        # Require that the TODO header and placeholder are removed
        if not has_todo_section and not has_placeholder:
            scores["readme_section_replaced"] = 1.0

        has_backend = "Backend: redis" in readme_text
        has_ttl = "TTL: 60" in readme_text
        has_prefix = "Key prefix: cache:" in readme_text
        if has_backend and has_ttl and has_prefix:
            scores["readme_contains_exact_config_strings"] = 1.0

        refs_files = ("src/fetch.php" in readme_text) and ("config/app.json" in readme_text)
        # Fallback explanation detection
        mentions_redis_extension = ("Redis extension" in readme_text) or ("Redis" in readme_text)
        phrases_unavailable = [
            "not available",
            "unavailable",
            "not present",
            "missing",
            "not installed",
            "absent",
        ]
        mentions_unavailable = any(phrase.lower() in readme_text.lower() for phrase in phrases_unavailable)
        mentions_fallback = "fallback" in readme_text.lower()
        if refs_files and mentions_redis_extension and mentions_unavailable and mentions_fallback:
            scores["readme_references_and_fallback_explained"] = 1.0

    # 4) output/redis_changes.txt content
    changes_text = read_text_safe(changes_txt)
    if changes_text is not None:
        lines = [ln.strip() for ln in changes_text.splitlines() if ln.strip()]
        expected_paths = ["src/fetch.php", "config/app.json", "README.md"]
        if len(lines) == 3:
            ok = True
            seen = set()
            for ln in lines:
                if ":" not in ln:
                    ok = False
                    break
                path_part, summary_part = ln.split(":", 1)
                path_part = path_part.strip()
                summary_part = summary_part.strip()
                if path_part not in expected_paths or not summary_part:
                    ok = False
                    break
                seen.add(path_part)
            if ok and set(expected_paths) == seen:
                scores["changes_summary_complete"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()