import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def load_spec(spec_path):
    defaults = {
        "indicator_name": "LB RTH VWAP + Bands",
        "shorttitle": "LB_RTH_VWAP",
        "groups": [
            "Feature Toggles",
            "VWAP Settings",
            "VWAP Bands",
            "Session Settings",
            "Display Options",
            "Colors",
        ],
        "session_window": "0930-1600",
        "timezone": "America/New_York",
    }
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ind_name = data.get("indicator_name", defaults["indicator_name"])
        shorttitle = data.get("shorttitle", defaults["shorttitle"])
        groups = data.get("input_groups", defaults["groups"])
        if not isinstance(groups, list) or not groups:
            groups = defaults["groups"]
        session_window = data.get("session", {}).get("window", data.get("session_window", defaults["session_window"]))
        tz = data.get("session", {}).get("timezone", data.get("timezone", defaults["timezone"]))
        return {
            "indicator_name": ind_name,
            "shorttitle": shorttitle,
            "groups": groups,
            "session_window": session_window,
            "timezone": tz,
        }
    except Exception:
        return defaults

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    pine_path = os.path.join(output_dir, "LB_RTH_VWAP_Bands.pine.txt")
    usage_path = os.path.join(output_dir, "USAGE.md")
    spec_path = os.path.join(input_dir, "spec.json")

    checks = {
        "pine_exists": False,
        "usage_exists": False,
        "version6_header": False,
        "mpl_license": False,
        "indicator_decl_title_short_overlay": False,
        "groups_present_feature_toggles": False,
        "groups_present_vwap_settings": False,
        "groups_present_vwap_bands": False,
        "groups_present_session_settings": False,
        "groups_present_display_options": False,
        "groups_present_colors": False,
        "session_window_present": False,
        "timezone_present": False,
        "time_function_with_session": False,
        "daily_reset_present": False,
        "var_persistent_present": False,
        "vwap_accumulation_present": False,
        "stdev_math_present": False,
        "plots_three_or_more": False,
        "moving_avg_ema_sma_present": False,
        "moving_avg_input_select_present": False,
        "theme_toggle_present": False,
        "theme_color_usage_present": False,
        "error_handling_present": False,
        "resource_limits_present": False,
        "usage_mentions_indicator": False,
        "usage_describes_inputs": False,
        "usage_describes_plots": False,
    }

    spec = load_spec(spec_path)

    pine = ""
    if os.path.isfile(pine_path):
        checks["pine_exists"] = True
        pine = read_text(pine_path)

    usage = ""
    if os.path.isfile(usage_path):
        checks["usage_exists"] = True
        usage = read_text(usage_path)

    # Only proceed with pine checks if file exists
    if checks["pine_exists"]:
        # Starts with //@version=6 on the first non-empty line
        first_non_empty = ""
        for line in pine.splitlines():
            if line.strip():
                first_non_empty = line.strip()
                break
        if first_non_empty.startswith("//@version=6"):
            checks["version6_header"] = True

        # MPL license reference
        if ("Mozilla Public License 2.0" in pine) or ("https://mozilla.org/MPL/2.0" in pine) or ("MPL 2.0" in pine):
            checks["mpl_license"] = True

        # Indicator declaration
        # Find indicator(...) content (first occurrence)
        ind_match = re.search(r"indicator\s*\((.*?)\)", pine, re.S)
        indicator_ok = False
        if ind_match:
            inside = ind_match.group(1)
            # Title match: allow single or double quotes
            title_pat = re.escape(spec["indicator_name"])
            short_pat = re.escape(spec["shorttitle"])
            title_ok = re.search(r"['\"]" + title_pat + r"['\"]", inside) is not None
            short_ok = re.search(r"shorttitle\s*=\s*['\"]" + short_pat + r"['\"]", inside) is not None
            overlay_ok = re.search(r"overlay\s*=\s*true", inside) is not None
            # Resource limits presence can be anywhere, but we also check below
            if title_ok and short_ok and overlay_ok:
                indicator_ok = True
        checks["indicator_decl_title_short_overlay"] = indicator_ok

        # Input groups
        # Use spec-provided or defaults. We individually check the canonical six required groups.
        # Map group names to keys
        group_keys = {
            "Feature Toggles": "groups_present_feature_toggles",
            "VWAP Settings": "groups_present_vwap_settings",
            "VWAP Bands": "groups_present_vwap_bands",
            "Session Settings": "groups_present_session_settings",
            "Display Options": "groups_present_display_options",
            "Colors": "groups_present_colors",
        }
        for g_name, g_key in group_keys.items():
            if re.search(r'group\s*=\s*["\']' + re.escape(g_name) + r'["\']', pine):
                checks[g_key] = True

        # Session window and timezone presence
        if spec["session_window"] and spec["session_window"] in pine:
            checks["session_window_present"] = True
        if spec["timezone"] and spec["timezone"] in pine:
            checks["timezone_present"] = True

        # Use of time() with session string (presence of time(timeframe.period with session window)
        # Try to ensure a time() call that includes the session window and optionally timezone
        time_with_session = False
        for m in re.finditer(r"time\s*\(", pine):
            # Extract a window around the call to check arguments
            start = max(0, m.start())
            snippet = pine[start:start+200]
            if (spec["session_window"] in snippet) and ("timeframe.period" in snippet):
                time_with_session = True
                break
        checks["time_function_with_session"] = time_with_session

        # Daily/session reset using ta.change(time("D"))
        if re.search(r"ta\.change\s*\(\s*time\s*\(\s*['\"]D['\"]\s*\)\s*\)", pine):
            checks["daily_reset_present"] = True

        # Persistent state via var declarations
        if re.search(r"(?m)^\s*var\b", pine):
            checks["var_persistent_present"] = True

        # VWAP accumulation: look for "+= volume" and "+= volume * hlc3"
        vwap_accum = False
        if (re.search(r"\+=\s*volume", pine) and
            re.search(r"\+=\s*volume\s*\*\s*hlc3", pine)):
            vwap_accum = True
        checks["vwap_accumulation_present"] = vwap_accum

        # Standard deviation via math.sqrt
        if "math.sqrt" in pine:
            checks["stdev_math_present"] = True

        # At least three plot() calls
        plots_count = len(re.findall(r"\bplot\s*\(", pine))
        if plots_count >= 3:
            checks["plots_three_or_more"] = True

        # Moving averages: ta.ema and ta.sma present
        if ("ta.ema" in pine) and ("ta.sma" in pine):
            checks["moving_avg_ema_sma_present"] = True

        # Moving average input selection: options including SMA and EMA
        # Look for input.string with options containing SMA and EMA
        ma_input_ok = False
        # Allow different input types (string or options list)
        if re.search(r"input\.\w+\s*\(.*SMA.*EMA", pine, re.S):
            ma_input_ok = True
        elif re.search(r"options\s*=\s*\[.*SMA.*EMA.*\]", pine, re.S):
            ma_input_ok = True
        checks["moving_avg_input_select_present"] = ma_input_ok

        # Theme toggle presence and usage
        theme_toggle = False
        if re.search(r"input\.bool\s*\(\s*.*Light Theme", pine):
            theme_toggle = True
        checks["theme_toggle_present"] = theme_toggle

        theme_usage = False
        # Either variable name like useLightTheme used in ternary or any ternary with colors
        if ("useLightTheme" in pine and re.search(r"useLightTheme\s*\?", pine)) or re.search(r"\?\s*color", pine):
            theme_usage = True
        checks["theme_color_usage_present"] = theme_usage

        # Error handling: nz(…) or division-by-zero ternary guard
        if ("nz(" in pine) or re.search(r"!=\s*0\s*\?\s*", pine):
            checks["error_handling_present"] = True

        # Resource limits presence (anywhere in the indicator() or code)
        res_ok = all(s in pine for s in ["max_bars_back", "max_labels_count", "max_lines_count"])
        checks["resource_limits_present"] = res_ok

    # Usage.md checks
    if checks["usage_exists"]:
        if spec["indicator_name"] in usage:
            checks["usage_mentions_indicator"] = True
        # mentions inputs and plots (case-insensitive)
        if re.search(r"\binputs\b", usage, re.I):
            checks["usage_describes_inputs"] = True
        if re.search(r"\bplots\b", usage, re.I):
            checks["usage_describes_plots"] = True

    # Compute reward
    # If either primary output file is missing, reward must be 0.0
    if not (checks["pine_exists"] and checks["usage_exists"]):
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Exclude the two existence checks from denominator for scoring once they exist
        # but if they exist we already included them as passed; to keep simple, score by fraction of all checks.
        reward = passed / total if total > 0 else 0.0
        # If any critical checks fail, allow partial credit. Keep within [0,1].
        if reward == 0.0:
            reward = 0.0

    # Ensure last non-empty line is the JSON
    result = {"reward": round(float(reward), 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()