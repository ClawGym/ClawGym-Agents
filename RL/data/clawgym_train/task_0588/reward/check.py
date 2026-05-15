import json
import os
import sys
import re

def read_text_file(path):
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

def briefing_checks(file_path, prefix):
    checks = {}
    key = lambda name: f"{prefix}_{name}"

    checks[key("exists")] = False
    checks[key("has_header_phrase")] = False
    checks[key("status_line_valid")] = False
    checks[key("has_what_you_should_do_section")] = False
    checks[key("bullet_count_between_4_and_6")] = False
    checks[key("has_daily_life_section")] = False
    checks[key("has_flights_line")] = False
    checks[key("has_schools_line")] = False
    checks[key("has_work_line")] = False
    checks[key("has_supplies_line")] = False
    checks[key("has_roads_line")] = False
    checks[key("has_hospitals_line")] = False
    checks[key("contains_outlook_word")] = False
    checks[key("contains_sources_word")] = False
    checks[key("contains_emergency_999")] = False
    checks[key("contains_official_and_guidance")] = False

    if not os.path.isfile(file_path):
        return checks

    content = read_text_file(file_path)
    if content is None:
        return checks

    checks[key("exists")] = True

    # Exact header phrase
    if "SITUATION UPDATE — Dubai, UAE" in content:
        checks[key("has_header_phrase")] = True

    # Status line
    status_valid = False
    for line in content.splitlines():
        if line.strip().startswith("Status:"):
            if ("CRITICAL" in line) or ("HIGH" in line) or ("MEDIUM" in line):
                status_valid = True
                break
    checks[key("status_line_valid")] = status_valid

    # What you should do section
    if "What you should do:" in content:
        checks[key("has_what_you_should_do_section")] = True

    # Bullet count across entire file for lines starting with "- " or "→ "
    bullet_count = 0
    for line in content.splitlines():
        if line.startswith("- ") or line.startswith("→ "):
            bullet_count += 1
    if 4 <= bullet_count <= 6:
        checks[key("bullet_count_between_4_and_6")] = True

    # Daily life section + required lines
    if "How this affects daily life:" in content:
        checks[key("has_daily_life_section")] = True

    # Start-of-line checks for daily life lines
    lines = content.splitlines()
    def has_line_prefix(prefix_text):
        for l in lines:
            if l.startswith(prefix_text):
                return True
        return False

    checks[key("has_flights_line")] = has_line_prefix("Flights:")
    checks[key("has_schools_line")] = has_line_prefix("Schools:")
    checks[key("has_work_line")] = has_line_prefix("Work:")
    checks[key("has_supplies_line")] = has_line_prefix("Supplies:")
    checks[key("has_roads_line")] = has_line_prefix("Roads:")
    checks[key("has_hospitals_line")] = has_line_prefix("Hospitals:")

    # Outlook word (case-sensitive as specified)
    if "Outlook" in content:
        checks[key("contains_outlook_word")] = True

    # Sources word (case-sensitive as specified)
    if "Sources" in content:
        checks[key("contains_sources_word")] = True

    # Emergency line
    if "Emergency: 999" in content:
        checks[key("contains_emergency_999")] = True

    # Disclaimer words "official" and "guidance" (case-insensitive)
    low = content.lower()
    if ("official" in low) and ("guidance" in low):
        checks[key("contains_official_and_guidance")] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Ensure no-op baseline: if output dir missing or empty, reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    output_has_any = False
    if output_exists:
        for root, dirs, files in os.walk(output_dir):
            if files:
                output_has_any = True
                break

    # Config checks
    cfg_path = os.path.join(output_dir, "aegis-config.json")
    checks["config_exists"] = False
    checks["config_valid_json"] = False
    checks["config_location_country_AE"] = False
    checks["config_location_city_Dubai"] = False
    checks["config_location_timezone_Asia_Dubai"] = False
    checks["config_language_en"] = False
    checks["config_alerts_critical_instant_true"] = False
    checks["config_briefings_enabled_true"] = False
    checks["config_briefings_morning_0800"] = False
    checks["config_briefings_evening_2000"] = False
    checks["config_scan_interval_15"] = False
    checks["config_llm_enabled_false"] = False
    checks["config_llm_provider_none_or_omitted"] = False
    checks["config_filters_require_location_match_true"] = False
    checks["config_tone_factual"] = False
    checks["config_include_preparedness_true"] = False
    checks["config_api_keys_newsapi_null_or_omitted"] = False

    cfg = None
    if os.path.isfile(cfg_path):
        checks["config_exists"] = True
        cfg = load_json(cfg_path)
        if isinstance(cfg, dict):
            checks["config_valid_json"] = True
            # location
            loc = cfg.get("location", {})
            if isinstance(loc, dict):
                if loc.get("country") == "AE":
                    checks["config_location_country_AE"] = True
                if loc.get("city") == "Dubai":
                    checks["config_location_city_Dubai"] = True
                if loc.get("timezone") == "Asia/Dubai":
                    checks["config_location_timezone_Asia_Dubai"] = True
            # language
            if cfg.get("language") == "en":
                checks["config_language_en"] = True
            # alerts
            alerts = cfg.get("alerts", {})
            if isinstance(alerts, dict) and alerts.get("critical_instant") is True:
                checks["config_alerts_critical_instant_true"] = True
            # briefings
            brief = cfg.get("briefings", {})
            if isinstance(brief, dict):
                if brief.get("enabled") is True:
                    checks["config_briefings_enabled_true"] = True
                if brief.get("morning") == "08:00":
                    checks["config_briefings_morning_0800"] = True
                if brief.get("evening") == "20:00":
                    checks["config_briefings_evening_2000"] = True
            # scan interval
            if cfg.get("scan_interval_minutes") == 15:
                checks["config_scan_interval_15"] = True
            # llm
            llm = cfg.get("llm", {})
            if isinstance(llm, dict):
                if llm.get("enabled") is False:
                    checks["config_llm_enabled_false"] = True
                # provider "none" or omitted
                provider = llm.get("provider", None)
                if provider is None or str(provider).lower() == "none":
                    checks["config_llm_provider_none_or_omitted"] = True
            else:
                # If llm omitted entirely, enabled false requirement is not met; must be explicit per spec
                pass
            # filters
            filters = cfg.get("filters", {})
            if isinstance(filters, dict) and filters.get("require_location_match") is True:
                checks["config_filters_require_location_match_true"] = True
            # tone
            if cfg.get("tone") == "factual":
                checks["config_tone_factual"] = True
            # include_preparedness
            if cfg.get("include_preparedness") is True:
                checks["config_include_preparedness_true"] = True
            # api_keys.newsapi null or omitted
            api_keys = cfg.get("api_keys", None)
            api_ok = False
            if api_keys is None:
                api_ok = True
            elif isinstance(api_keys, dict):
                # If newsapi omitted or is None -> ok
                if "newsapi" not in api_keys or api_keys.get("newsapi") is None:
                    api_ok = True
            checks["config_api_keys_newsapi_null_or_omitted"] = api_ok

    # Briefings checks
    morning_path = os.path.join(output_dir, "briefings", "morning.md")
    evening_path = os.path.join(output_dir, "briefings", "evening.md")
    checks.update(briefing_checks(morning_path, "morning"))
    checks.update(briefing_checks(evening_path, "evening"))

    # Ops checks
    ops_path = os.path.join(output_dir, "ops", "operations.md")
    checks["ops_exists"] = False
    checks["ops_contains_anti_hoax_protocol"] = False
    checks["ops_contains_source_tiers"] = False
    checks["ops_contains_critical_validation"] = False
    checks["ops_contains_fail_open"] = False
    checks["ops_contains_corroboration"] = False
    checks["ops_contains_posting_schedule"] = False
    checks["ops_contains_cooldown"] = False

    if os.path.isfile(ops_path):
        ops_content = read_text_file(ops_path) or ""
        checks["ops_exists"] = True
        low_ops = ops_content.lower()
        if "anti-hoax protocol".lower() in low_ops:
            checks["ops_contains_anti_hoax_protocol"] = True
        if "source tiers".lower() in low_ops:
            checks["ops_contains_source_tiers"] = True
        if "critical validation".lower() in low_ops:
            checks["ops_contains_critical_validation"] = True
        if re.search(r"fail[-\s]?open", ops_content, flags=re.IGNORECASE):
            checks["ops_contains_fail_open"] = True
        if "corroboration".lower() in low_ops:
            checks["ops_contains_corroboration"] = True
        if "posting schedule".lower() in low_ops:
            checks["ops_contains_posting_schedule"] = True
        if "cooldown".lower() in low_ops:
            checks["ops_contains_cooldown"] = True

    # Changelog checks
    changelog_path = os.path.join(output_dir, "changelog.jsonl")
    checks["changelog_exists"] = False
    checks["changelog_has_valid_line"] = False
    if os.path.isfile(changelog_path):
        checks["changelog_exists"] = True
        try:
            with open(changelog_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    ev = obj.get("event")
                    ts = obj.get("timestamp")
                    rat = obj.get("rationale")
                    if ev == "config_created" and isinstance(ts, str) and ts.strip() != "" and isinstance(rat, str) and rat.strip() != "":
                        checks["changelog_has_valid_line"] = True
                        break
        except Exception:
            pass

    # Compute reward
    total_checks = len(checks)
    true_count = sum(1 for v in checks.values() if v)

    # No-op baseline: if output/ missing or empty, force 0.0
    if (not output_exists) or (not output_has_any):
        reward = 0.0
    else:
        reward = (true_count / total_checks) if total_checks > 0 else 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()