import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True
    except Exception:
        return "", False

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def parse_strategy_overrides(text):
    # Defaults
    result = {
        "symbol": "BTC/USDT",
        "timeframe": "15m",
        "capital": 10000.0,
    }
    # Regex patterns for explicit overrides (lines like "symbol: ETH/USDT", "timeframe: 1h", "capital: 12000")
    sym_re = re.compile(r'^\s*(symbol|pair)\s*:\s*([A-Za-z0-9:_./-]+)\s*$', re.IGNORECASE | re.MULTILINE)
    tf_re = re.compile(r'^\s*timeframe\s*:\s*([0-9]+[smhdw])\s*$', re.IGNORECASE | re.MULTILINE)
    cap_re = re.compile(r'^\s*(capital|budget|equity)\s*:\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)\s*$', re.IGNORECASE | re.MULTILINE)

    m = sym_re.search(text)
    if m:
        result["symbol"] = m.group(2).strip()
    m = tf_re.search(text)
    if m:
        result["timeframe"] = m.group(1).strip()
    m = cap_re.search(text)
    if m:
        num = m.group(2).replace(",", "")
        try:
            result["capital"] = float(num)
        except Exception:
            pass
    return result

def ensure_string(val):
    return isinstance(val, str)

def str_not_identical(a, b):
    if not (isinstance(a, str) and isinstance(b, str)):
        return False
    return a != b

def length_ok(s, maxlen):
    return isinstance(s, str) and len(s) <= maxlen

def normalize_ws(s):
    return re.sub(r'\s+', ' ', s.strip().lower())

def contains_line_starting_with(lines, prefix):
    p = prefix.lower()
    for line in lines:
        if line.strip().lower().startswith(p):
            return True
    return False

def find_lines_starting_with(lines, prefix):
    out = []
    p = prefix.lower()
    for line in lines:
        if line.strip().lower().startswith(p):
            out.append(line.rstrip("\n"))
    return out

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Prepare checks dict with all False by default
    checks = {
        # bot_params.json
        "has_bot_params_file": False,
        "bot_params_valid_json": False,
        "bot_params_required_keys": False,
        "bot_params_defaults_or_overrides_ok": False,
        "bot_params_evolution_enabled_true": False,
        "bot_params_leverage_within_cap": False,
        "bot_params_sl_atr_mult_present_numeric": False,
        "bot_params_high_leverage_requires_wide_sl": False,
        "bot_params_bilingual_fields_present": False,
        "bot_params_bilingual_lengths_ok": False,
        "bot_params_bilingual_not_identical": False,

        # evolution_schedule.json
        "has_evolution_schedule_file": False,
        "evolution_schedule_valid_json": False,
        "evolution_schedule_min_len": False,
        "evolution_schedule_rounds_incrementing": False,
        "evolution_schedule_params_present": False,
        "evolution_schedule_meaningful_change": False,

        # backtest_result.json
        "has_backtest_result_file": False,
        "backtest_result_valid_json": False,
        "backtest_result_mode_evolution": False,
        "backtest_result_metrics_fields": False,
        "backtest_result_csv_path_correct": False,
        "backtest_result_evolution_log_present": False,

        # execution_summary.txt
        "has_execution_summary_file": False,
        "execution_summary_has_required_lines": False,
        "execution_summary_evolution_on": False,
        "execution_summary_datasource_correct": False,
        "execution_summary_next_steps_present": False,
        "execution_summary_has_paragraph": False,

        # risk_disclosure.md
        "has_risk_disclosure_file": False,
        "risk_disclosure_required_phrases": False,
    }

    # Load strategy overrides from input/strategy.md if available
    strategy_path = os.path.join(input_dir, "strategy.md")
    strategy_text, _ = load_text_file(strategy_path)
    expected = parse_strategy_overrides(strategy_text)

    # 1) bot_params.json checks
    bot_params_path = os.path.join(output_dir, "bot_params.json")
    if os.path.isfile(bot_params_path):
        checks["has_bot_params_file"] = True
        bot_params, ok = load_json_file(bot_params_path)
        if ok and isinstance(bot_params, dict):
            checks["bot_params_valid_json"] = True
            # Required keys
            required_keys_present = (
                "symbol" in bot_params and
                "timeframe" in bot_params and
                "capital" in bot_params and
                "leverage" in bot_params and
                "sl_atr_mult" in bot_params and
                "evolution_enabled" in bot_params and
                "name_i18n" in bot_params and
                "personality_i18n" in bot_params and
                "description_i18n" in bot_params
            )
            checks["bot_params_required_keys"] = required_keys_present

            if required_keys_present:
                # Defaults vs overrides
                sym_ok = isinstance(bot_params["symbol"], str) and bot_params["symbol"] == expected["symbol"]
                tf_ok = isinstance(bot_params["timeframe"], str) and bot_params["timeframe"] == expected["timeframe"]
                cap_ok = is_number(bot_params["capital"]) and float(bot_params["capital"]) == float(expected["capital"])
                checks["bot_params_defaults_or_overrides_ok"] = bool(sym_ok and tf_ok and cap_ok)

                # evolution_enabled true
                checks["bot_params_evolution_enabled_true"] = bool(bot_params["evolution_enabled"] is True)

                # leverage cap
                lev = bot_params["leverage"]
                lev_num_ok = is_number(lev)
                lev_cap_ok = lev_num_ok and float(lev) <= 150.0
                checks["bot_params_leverage_within_cap"] = bool(lev_cap_ok)

                # sl_atr_mult numeric
                slv = bot_params["sl_atr_mult"]
                sl_num_ok = is_number(slv)
                checks["bot_params_sl_atr_mult_present_numeric"] = bool(sl_num_ok)

                # high leverage rule
                high_lev_rule_ok = False
                if lev_num_ok and sl_num_ok:
                    if float(lev) > 20.0:
                        high_lev_rule_ok = float(slv) >= 2.5
                    else:
                        high_lev_rule_ok = True
                checks["bot_params_high_leverage_requires_wide_sl"] = bool(high_lev_rule_ok)

                # bilingual fields presence and structure
                def valid_i18n(obj):
                    return isinstance(obj, dict) and "zh" in obj and "en" in obj and ensure_string(obj["zh"]) and ensure_string(obj["en"])

                bi_present = valid_i18n(bot_params.get("name_i18n")) and valid_i18n(bot_params.get("personality_i18n")) and valid_i18n(bot_params.get("description_i18n"))
                checks["bot_params_bilingual_fields_present"] = bool(bi_present)

                if bi_present:
                    name_zh = bot_params["name_i18n"]["zh"]
                    name_en = bot_params["name_i18n"]["en"]
                    pers_zh = bot_params["personality_i18n"]["zh"]
                    pers_en = bot_params["personality_i18n"]["en"]
                    desc_zh = bot_params["description_i18n"]["zh"]
                    desc_en = bot_params["description_i18n"]["en"]

                    lengths_ok = (
                        length_ok(name_zh, 64) and length_ok(name_en, 64) and
                        length_ok(pers_zh, 64) and length_ok(pers_en, 64) and
                        length_ok(desc_zh, 280) and length_ok(desc_en, 280)
                    )
                    checks["bot_params_bilingual_lengths_ok"] = bool(lengths_ok)

                    # zh and en must not be identical strings for each field
                    not_identical = (
                        str_not_identical(name_zh, name_en) and
                        str_not_identical(pers_zh, pers_en) and
                        str_not_identical(desc_zh, desc_en)
                    )
                    checks["bot_params_bilingual_not_identical"] = bool(not_identical)

    # 2) evolution_schedule.json checks
    evo_sched_path = os.path.join(output_dir, "evolution_schedule.json")
    if os.path.isfile(evo_sched_path):
        checks["has_evolution_schedule_file"] = True
        evo_sched, ok = load_json_file(evo_sched_path)
        if ok and isinstance(evo_sched, list):
            checks["evolution_schedule_valid_json"] = True
            checks["evolution_schedule_min_len"] = len(evo_sched) >= 3

            # rounds incrementing starting at 1
            rounds_ok = False
            params_present = False
            meaningful_change = False
            if len(evo_sched) >= 1:
                try:
                    rounds = [item.get("round") for item in evo_sched]
                    params_list = [item.get("params") for item in evo_sched]
                    params_present = all(isinstance(p, dict) for p in params_list)
                    if all(isinstance(r, int) for r in rounds):
                        expected_rounds = list(range(1, len(rounds) + 1))
                        rounds_ok = rounds == expected_rounds
                    # meaningful change: any later params differ from round 1
                    if params_present and len(params_list) >= 2:
                        first = params_list[0]
                        for later in params_list[1:]:
                            if later != first:
                                meaningful_change = True
                                break
                except Exception:
                    rounds_ok = False
                    params_present = False
                    meaningful_change = False

            checks["evolution_schedule_rounds_incrementing"] = bool(rounds_ok)
            checks["evolution_schedule_params_present"] = bool(params_present)
            checks["evolution_schedule_meaningful_change"] = bool(meaningful_change)

    # 3) backtest_result.json checks
    backtest_path = os.path.join(output_dir, "backtest_result.json")
    if os.path.isfile(backtest_path):
        checks["has_backtest_result_file"] = True
        backtest, ok = load_json_file(backtest_path)
        if ok and isinstance(backtest, dict):
            checks["backtest_result_valid_json"] = True
            checks["backtest_result_mode_evolution"] = (backtest.get("mode") == "evolution")

            # metrics object with numeric fields
            metrics = backtest.get("metrics")
            metrics_ok = False
            if isinstance(metrics, dict):
                ret = metrics.get("return")
                shr = metrics.get("sharpe")
                trd = metrics.get("trades")
                metrics_ok = is_number(ret) and is_number(shr) and is_number(trd)
            checks["backtest_result_metrics_fields"] = bool(metrics_ok)

            # csv_path correctness
            checks["backtest_result_csv_path_correct"] = (backtest.get("csv_path") == "input/BTCUSDT_15m_148d.csv")

            # evolution_log presence and at least one entry
            evo_log = backtest.get("evolution_log")
            evo_log_ok = False
            if isinstance(evo_log, list):
                evo_log_ok = len(evo_log) >= 1
            elif isinstance(evo_log, dict):
                evo_log_ok = len(evo_log.keys()) >= 1
            checks["backtest_result_evolution_log_present"] = bool(evo_log_ok)

    # 4) execution_summary.txt checks
    exec_summary_path = os.path.join(output_dir, "execution_summary.txt")
    if os.path.isfile(exec_summary_path):
        checks["has_execution_summary_file"] = True
        txt, ok = load_text_file(exec_summary_path)
        if ok and txt:
            lines = txt.splitlines()

            # Required lines: Symbol, Timeframe, Capital, Evolution, Data source
            has_symbol = any(re.match(r'^\s*Symbol\s*:\s*.+', ln, re.IGNORECASE) for ln in lines)
            has_timeframe = any(re.match(r'^\s*Timeframe\s*:\s*.+', ln, re.IGNORECASE) for ln in lines)
            # Capital numeric
            cap_line = None
            for ln in lines:
                if re.match(r'^\s*Capital\s*:\s*', ln, re.IGNORECASE):
                    cap_line = ln
                    break
            cap_num_ok = False
            if cap_line:
                m = re.search(r'Capital\s*:\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)', cap_line, re.IGNORECASE)
                if m:
                    try:
                        float(m.group(1).replace(",", ""))
                        cap_num_ok = True
                    except Exception:
                        cap_num_ok = False

            has_evo = any(re.match(r'^\s*Evolution\s*:\s*.+', ln, re.IGNORECASE) for ln in lines)
            has_datasource = any(re.match(r'^\s*Data\s+source\s*:\s*input/BTCUSDT_15m_148d\.csv\s*$', ln, re.IGNORECASE) for ln in lines)
            checks["execution_summary_has_required_lines"] = bool(has_symbol and has_timeframe and cap_num_ok and has_evo and has_datasource)

            # Evolution on
            evo_on = False
            for ln in lines:
                m = re.match(r'^\s*Evolution\s*:\s*(.+)$', ln, re.IGNORECASE)
                if m:
                    val = m.group(1).strip().lower()
                    if val == "on":
                        evo_on = True
                    break
            checks["execution_summary_evolution_on"] = bool(evo_on)

            checks["execution_summary_datasource_correct"] = bool(has_datasource)

            # Next steps A/B/C with expected phrases
            # Find lines starting with A), B), C)
            a_lines = find_lines_starting_with(lines, "A)")
            b_lines = find_lines_starting_with(lines, "B)")
            c_lines = find_lines_starting_with(lines, "C)")
            # content keywords
            def has_phrase(line_list, phrase):
                ph = phrase.lower()
                for l in line_list:
                    if ph in l.strip().lower():
                        return True
                return False

            a_ok = len(a_lines) >= 1 and has_phrase(a_lines, "start live auto trading")
            b_ok = len(b_lines) >= 1 and has_phrase(b_lines, "upload to platform for verification")
            c_ok = len(c_lines) >= 1 and has_phrase(c_lines, "adjust parameters and rerun")
            # Also ensure "Next step:" exists
            next_step_line = any("next step" in ln.strip().lower() for ln in lines)
            checks["execution_summary_next_steps_present"] = bool(next_step_line and a_ok and b_ok and c_ok)

            # One-paragraph execution summary: at least one non-empty line that is not a key-value header or next step header
            def is_header_line(ln):
                low = ln.strip().lower()
                if not low:
                    return True
                if any(low.startswith(pfx) for pfx in ["symbol:", "timeframe:", "capital:", "evolution:", "data source:", "next step:"]):
                    return True
                if re.match(r'^[ABCabc]\)\s', ln.strip()):
                    return True
                return False

            has_paragraph = any((ln.strip() and not is_header_line(ln)) for ln in lines)
            checks["execution_summary_has_paragraph"] = bool(has_paragraph)

    # 5) risk_disclosure.md checks
    risk_path = os.path.join(output_dir, "risk_disclosure.md")
    if os.path.isfile(risk_path):
        checks["has_risk_disclosure_file"] = True
        risk_text, ok = load_text_file(risk_path)
        if ok:
            phrases_ok = (
                "Backtesting results do not guarantee future performance" in risk_text and
                "Leverage cap: 150x" in risk_text and
                "sl_atr_mult >= 2.5 for leverage > 20x" in risk_text
            )
            checks["risk_disclosure_required_phrases"] = bool(phrases_ok)

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, force reward 0.0
    if not os.path.isdir(output_dir) or not any(os.scandir(output_dir)):
        reward = 0.0

    # Print JSON result (single line as last non-empty line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()