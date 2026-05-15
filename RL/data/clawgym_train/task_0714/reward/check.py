import json
import os
import sys
import re

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def word_count(text):
    # Simple word count: split on whitespace
    return len([w for w in re.split(r"\s+", text.strip()) if w])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    strategy_yaml_path = os.path.join(output_dir, "strategy.yaml")
    summary_json_path = os.path.join(output_dir, "summary.json")
    notes_md_path = os.path.join(output_dir, "notes.md")
    factors_catalog_path = os.path.join(input_dir, "factors_catalog.json")

    checks = {
        # Existence and basic validation
        "strategy_yaml_exists": False,
        "strategy_yaml_nonempty": False,
        "summary_json_exists": False,
        "summary_json_valid": False,
        "notes_md_exists": False,
        "notes_md_200w": False,

        # Summary validations
        "summary_name_version_correct": False,
        "summary_inline_factors_correct": False,
        "summary_external_factors_two_distinct_allowed": False,
        "summary_weights_four_positive_sum1": False,
        "summary_normalize_zscore": False,
        "summary_limits_correct": False,
        "summary_condition_counts_ok": False,
        "summary_output_columns_include_required": False,

        # YAML content validations
        "yaml_has_name_version": False,
        "yaml_has_core_sections": False,
        "yaml_has_inline_factor_exprs": False,
        "yaml_has_external_factors_and_weights": False,
        "yaml_has_normalize_zscore": False,
    }

    # Load allowed external factors catalog
    allowed_external_factors = set()
    allowed_catalog_data, _ = load_json_file(factors_catalog_path)
    if isinstance(allowed_catalog_data, list):
        # Allow only string identifiers
        for item in allowed_catalog_data:
            if isinstance(item, str):
                allowed_external_factors.add(item)

    # Check strategy.yaml
    strategy_content, err = read_text_file(strategy_yaml_path)
    if strategy_content is not None:
        checks["strategy_yaml_exists"] = True
        if strategy_content.strip():
            checks["strategy_yaml_nonempty"] = True

            # YAML: name and version
            if ("name: Hybrid Value-Momentum Screen v1" in strategy_content
                and "version: 1.0.0" in strategy_content):
                checks["yaml_has_name_version"] = True

            # YAML: core sections
            # Ensure presence of keys screening:, factors:, ranking:, output:
            if all(k in strategy_content for k in ["screening:", "factors:", "ranking:", "output:"]):
                checks["yaml_has_core_sections"] = True

            # YAML: inline factor names and expressions
            has_momentum_name = "name: momentum_20d" in strategy_content or "momentum_20d" in strategy_content
            has_ma_name = "name: ma10_deviation" in strategy_content or "ma10_deviation" in strategy_content
            has_delay_expr = "delay(close, 20)" in strategy_content
            has_ma_expr = "ma(close, 10)" in strategy_content
            if has_momentum_name and has_ma_name and has_delay_expr and has_ma_expr:
                checks["yaml_has_inline_factor_exprs"] = True

            # YAML: normalize zscore
            if "normalize: zscore" in strategy_content:
                checks["yaml_has_normalize_zscore"] = True

    # Check notes.md
    notes_content, _ = read_text_file(notes_md_path)
    if notes_content is not None:
        checks["notes_md_exists"] = True
        if word_count(notes_content) >= 200:
            checks["notes_md_200w"] = True

    # Check summary.json
    summary_data, err = load_json_file(summary_json_path)
    if summary_data is not None:
        checks["summary_json_exists"] = True
        checks["summary_json_valid"] = True

        # Summary: name and version
        if (summary_data.get("strategy_name") == "Hybrid Value-Momentum Screen v1"
                and summary_data.get("version") == "1.0.0"):
            checks["summary_name_version_correct"] = True

        # Summary: inline factors exactly
        inline_factors = summary_data.get("inline_factors")
        if isinstance(inline_factors, list) and inline_factors == ["momentum_20d", "ma10_deviation"]:
            checks["summary_inline_factors_correct"] = True

        # Summary: external factors two distinct and allowed
        external_factors = summary_data.get("external_factors")
        if (isinstance(external_factors, list)
                and len(external_factors) == 2
                and len(set(external_factors)) == 2
                and all(isinstance(x, str) for x in external_factors)
                and len(allowed_external_factors) > 0
                and all(x in allowed_external_factors for x in external_factors)):
            checks["summary_external_factors_two_distinct_allowed"] = True

        # Summary: weights coverage and sum
        weights = summary_data.get("weights")
        if isinstance(weights, dict):
            # Expected keys: inline factors + external
            expected_keys_set = set(["momentum_20d", "ma10_deviation"])
            if isinstance(external_factors, list) and len(external_factors) == 2:
                expected_keys_set.update(external_factors)
            # Validate exact keys set, positive weights, sum within [0.99, 1.01]
            keys_match = set(weights.keys()) == expected_keys_set
            if keys_match:
                try:
                    values = [float(weights[k]) for k in weights.keys()]
                    positive = all(v > 0 for v in values)
                    s = sum(values)
                    within_tolerance = 0.99 <= s <= 1.01
                    if positive and within_tolerance:
                        checks["summary_weights_four_positive_sum1"] = True
                except Exception:
                    pass

        # Summary: normalize zscore
        if summary_data.get("normalize") == "zscore":
            checks["summary_normalize_zscore"] = True

        # Summary: limits
        if summary_data.get("screening_limit") == 150 and summary_data.get("output_limit") == 30:
            checks["summary_limits_correct"] = True

        # Summary: condition counts
        fc = summary_data.get("fundamental_conditions_count")
        dc = summary_data.get("daily_conditions_count")
        try:
            if int(fc) >= 3 and int(dc) >= 2:
                checks["summary_condition_counts_ok"] = True
        except Exception:
            pass

        # Summary: output columns include required
        output_columns = summary_data.get("output_columns")
        required_cols_base = ["symbol", "name", "score", "roe", "pe_ttm", "momentum_20d", "ma10_deviation"]
        if isinstance(output_columns, list):
            base_ok = all(col in output_columns for col in required_cols_base)
            externals_ok = False
            if isinstance(external_factors, list) and len(external_factors) == 2:
                externals_ok = all(col in output_columns for col in external_factors)
            if base_ok and externals_ok:
                checks["summary_output_columns_include_required"] = True

        # YAML cross-checks that depend on summary (external factor ids in YAML factors and ranking)
        if checks["strategy_yaml_nonempty"] and checks["summary_external_factors_two_distinct_allowed"]:
            yaml_text = strategy_content if strategy_content is not None else ""
            externals_present_in_yaml = all(x in yaml_text for x in external_factors)
            # Try to ensure they are mentioned under ranking weights as well
            # We will look for a "ranking:" section and see if identifiers appear after that
            ranking_index = yaml_text.find("ranking:")
            ranking_contains = False
            if ranking_index != -1:
                ranking_text = yaml_text[ranking_index:]
                ranking_contains = all(x in ranking_text for x in external_factors)
            if externals_present_in_yaml and ranking_contains:
                checks["yaml_has_external_factors_and_weights"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Enforce no-op baseline: if output directory missing or all three key files missing -> reward 0.0
    # Key files are strategy.yaml, summary.json, notes.md
    key_files_exist = any(os.path.isfile(p) for p in [strategy_yaml_path, summary_json_path, notes_md_path])
    if not key_files_exist:
        reward = 0.0

    # Print result JSON (single line, reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()