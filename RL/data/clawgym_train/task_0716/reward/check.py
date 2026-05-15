import csv
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        # CSV checks
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_row_count_11": False,
        "csv_tickers_complete": False,
        "csv_sector_mapping_ok": False,
        "csv_values_integral_nonneg": False,
        "csv_totals_match": False,
        "csv_avg_conf_in_range": False,
        "csv_accuracy_in_range": False,
        "csv_cw_score_values_valid": False,
        "csv_cw_score_4decimals": False,
        # Raw JSON checks for five major sectors
        "raw_XLK_ok": False,
        "raw_XLF_ok": False,
        "raw_XLE_ok": False,
        "raw_XLV_ok": False,
        "raw_XLI_ok": False,
        # Report checks
        "report_exists": False,
        "report_length_ok": False,
        "report_has_sections": False,
        "report_mentions_all_sectors_or_tickers": False,
        "report_has_disclaimer_phrases": False,
    }

    expected_tickers = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLB", "XLRE", "XLU"]
    sector_map = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "XLI": "Industrials",
        "XLC": "Communication Services",
        "XLY": "Consumer Discretionary",
        "XLP": "Consumer Staples",
        "XLB": "Materials",
        "XLRE": "Real Estate",
        "XLU": "Utilities",
    }
    expected_header = [
        "ticker",
        "sector",
        "bullish",
        "bearish",
        "neutral",
        "total_analysts",
        "avg_confidence",
        "prediction_accuracy",
        "cw_bullish_score",
    ]

    # 1) Validate CSV aggregation
    csv_path = os.path.join(output_dir, "sector_signals.csv")
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                # Header exact match check
                if reader.fieldnames == expected_header:
                    checks["csv_header_ok"] = True

                rows = list(reader)
        except Exception:
            rows = []
        if rows:
            # row count check
            if len(rows) == 11:
                checks["csv_row_count_11"] = True

            # ticker completeness
            seen = set()
            all_sector_map_ok = True
            ints_ok = True
            totals_ok = True
            avg_conf_ok = True
            acc_ok = True
            cw_value_ok = True
            cw_format_ok = True

            for row in rows:
                ticker = (row.get("ticker") or "").strip().upper()
                seen.add(ticker)

                # Sector mapping
                expected_sector = sector_map.get(ticker)
                sector_val = (row.get("sector") or "").strip()
                if expected_sector is None or sector_val != expected_sector:
                    all_sector_map_ok = False

                # Int values check
                def parse_int(val):
                    try:
                        ival = int(str(val).strip())
                        return ival, True
                    except Exception:
                        return None, False

                b_bull, ok1 = parse_int(row.get("bullish"))
                b_bear, ok2 = parse_int(row.get("bearish"))
                b_neut, ok3 = parse_int(row.get("neutral"))
                b_total, ok4 = parse_int(row.get("total_analysts"))
                if not (ok1 and ok2 and ok3 and ok4):
                    ints_ok = False
                    totals_ok = False
                else:
                    # non-negative
                    if b_bull is None or b_bear is None or b_neut is None or b_total is None:
                        ints_ok = False
                        totals_ok = False
                    else:
                        if any(x < 0 for x in [b_bull, b_bear, b_neut, b_total]):
                            ints_ok = False
                        # totals match
                        if b_total != (b_bull + b_bear + b_neut):
                            totals_ok = False

                # avg_confidence and prediction_accuracy in [0,1]
                def parse_decimal_in_01(val):
                    try:
                        d = Decimal(str(val).strip())
                        if d < Decimal("0") or d > Decimal("1"):
                            return None
                        return d
                    except (InvalidOperation, AttributeError):
                        return None

                avg_conf = parse_decimal_in_01(row.get("avg_confidence"))
                if avg_conf is None:
                    avg_conf_ok = False

                acc = parse_decimal_in_01(row.get("prediction_accuracy"))
                if acc is None:
                    acc_ok = False

                # cw_bullish_score validation
                cw_str = str(row.get("cw_bullish_score") or "").strip()
                # format must be exactly 4 decimals
                if not re.fullmatch(r"^(0\.\d{4}|1\.0000)$", cw_str):
                    cw_format_ok = False
                cw_val = None
                try:
                    cw_val = Decimal(cw_str)
                except (InvalidOperation, ValueError):
                    cw_value_ok = False

                if cw_val is not None:
                    # ensure in [0,1]
                    if cw_val < Decimal("0") or cw_val > Decimal("1"):
                        cw_value_ok = False
                    # compute expected cw
                    expected_cw = Decimal("0")
                    if (b_total is not None and b_total > 0) and (avg_conf is not None):
                        try:
                            ratio = (Decimal(b_bull) / Decimal(b_total))
                            expected_cw = (ratio * avg_conf).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        except Exception:
                            # computation failure
                            expected_cw = None
                    elif b_total == 0:
                        expected_cw = Decimal("0.0000")
                    else:
                        # missing inputs to compute expected cw
                        expected_cw = None

                    if expected_cw is not None:
                        # Compare quantized expected to reported
                        try:
                            reported_cw = cw_val.quantize(Decimal("0.0001"))
                            if reported_cw != expected_cw:
                                cw_value_ok = False
                        except Exception:
                            cw_value_ok = False

            if set(expected_tickers) == seen:
                checks["csv_tickers_complete"] = True
            checks["csv_sector_mapping_ok"] = all_sector_map_ok
            checks["csv_values_integral_nonneg"] = ints_ok
            checks["csv_totals_match"] = totals_ok
            checks["csv_avg_conf_in_range"] = avg_conf_ok
            checks["csv_accuracy_in_range"] = acc_ok
            checks["csv_cw_score_values_valid"] = cw_value_ok
            checks["csv_cw_score_4decimals"] = cw_format_ok

    # 2) Raw JSON snapshots for five major sectors
    def raw_ok(ticker):
        raw_path = os.path.join(output_dir, "raw", f"{ticker}.json")
        if not os.path.isfile(raw_path):
            return False
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            # minimal keys presence per spec
            if "latest_consensus" not in data or "avg_confidence" not in data:
                return False
            return True
        except Exception:
            return False

    checks["raw_XLK_ok"] = raw_ok("XLK")
    checks["raw_XLF_ok"] = raw_ok("XLF")
    checks["raw_XLE_ok"] = raw_ok("XLE")
    checks["raw_XLV_ok"] = raw_ok("XLV")
    checks["raw_XLI_ok"] = raw_ok("XLI")

    # 3) Narrative report validation
    report_path = os.path.join(output_dir, "sector_rotation_briefing.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""
        if len(report_text) > 1500:
            checks["report_length_ok"] = True

        lower_text = report_text.lower()

        required_sections = [
            "Executive Summary",
            "Rotation Gradient",
            "Sector-by-Sector Notes",
            "Methodology & Limitations",
            "Risk Disclaimer",
            "Monitoring Plan",
        ]
        if all(section.lower() in lower_text for section in required_sections):
            checks["report_has_sections"] = True

        # Mentions all 11 tickers or sector names
        def mention_ok(ticker):
            sector_name = sector_map[ticker]
            return (ticker.lower() in lower_text) or (sector_name.lower() in lower_text)

        if all(mention_ok(t) for t in expected_tickers):
            checks["report_mentions_all_sectors_or_tickers"] = True

        # Contains both phrases
        if ("ai-generated" in lower_text) and ("not financial advice" in lower_text):
            checks["report_has_disclaimer_phrases"] = True

    # Compute reward as average of passed checks; ensure 0.0 if no relevant output files
    bool_values = list(checks.values())
    passed = sum(1 for v in bool_values if v)
    total = len(bool_values)
    reward = (passed / total) if total > 0 else 0.0

    # Explicitly set reward to 0.0 if output directory is missing or empty of required artifacts
    essential_files = [
        os.path.join(output_dir, "sector_signals.csv"),
        os.path.join(output_dir, "sector_rotation_briefing.md"),
    ]
    essential_exist = any(os.path.isfile(p) for p in essential_files)
    if not essential_exist:
        reward = 0.0

    # Print final JSON with "reward" first
    out = {"reward": round(reward, 6)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()