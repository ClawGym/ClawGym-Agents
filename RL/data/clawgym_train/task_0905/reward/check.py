import json
import sys
import re
import csv
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in s:
        s = s.replace("\\n", "\n")
    return s


def _load_json(path: Path) -> Optional[dict]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_csv_text(text: str) -> Optional[List[Dict[str, str]]]:
    try:
        norm = _normalize_text(text)
        from io import StringIO
        buf = StringIO(norm)
        reader = csv.DictReader(buf)
        if reader.fieldnames is None:
            return None
        rows = []
        for row in reader:
            if row is None:
                continue
            if all((v is None or str(v).strip() == "") for v in row.values()):
                continue
            rows.append({k: (v if v is not None else "") for k, v in row.items()})
        return rows
    except Exception:
        return None


def _parse_csv_file(path: Path) -> Optional[List[Dict[str, str]]]:
    text = _read_text(path)
    if text is None:
        return None
    return _parse_csv_text(text)


def _parse_log_last_error_info(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return (None, None)
    norm = _normalize_text(text)
    lines = norm.split("\n")
    ts = None
    error_idx = None
    ts_regex = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+ERROR\b")
    for i, line in enumerate(lines):
        m = ts_regex.match(line.strip())
        if m:
            ts = m.group(1)
            error_idx = i
    if ts is None:
        matches = list(re.finditer(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", norm))
        if matches:
            ts = matches[-1].group(1)
    signature = None
    keyerr_re = re.compile(r"^\s*([A-Za-z_]+Error: .+)\s*$")
    start = error_idx + 1 if error_idx is not None else 0
    for j in range(start, len(lines)):
        m = keyerr_re.match(lines[j].strip())
        if m:
            signature = m.group(1)
    if signature is None:
        for j in range(len(lines)):
            m = keyerr_re.match(lines[j].strip())
            if m:
                signature = m.group(1)
    return (ts, signature)


def _compute_totals_from_transactions(tx_rows: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    try:
        totals: Dict[str, Decimal] = {}
        for row in tx_rows:
            if 'currency' not in row or 'amount' not in row:
                return None
            currency = (row['currency'] or "").strip()
            amt_str = (row['amount'] or "").strip()
            if currency == "" or amt_str == "":
                return None
            amt = Decimal(amt_str).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            totals[currency] = totals.get(currency, Decimal("0.00")) + amt
        return {k: f"{v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}" for k, v in totals.items()}
    except (InvalidOperation, Exception):
        return None


def _parse_revenue_summary(path: Path) -> Optional[Dict[str, str]]:
    rows = _parse_csv_file(path)
    if rows is None:
        return None
    text = _read_text(path)
    if text is None:
        return None
    norm = _normalize_text(text)
    header_line = norm.split("\n", 1)[0].strip()
    if header_line.replace(" ", "") != "currency,total_amount":
        return None
    totals: Dict[str, str] = {}
    for row in rows:
        if 'currency' not in row or 'total_amount' not in row:
            return None
        curr = (row['currency'] or "").strip()
        total = (row['total_amount'] or "").strip()
        if curr == "" or total == "":
            return None
        try:
            _ = Decimal(total)
        except InvalidOperation:
            return None
        totals[curr] = total
    return totals


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "incident_report_has_expected_fields": 0.0,
        "failed_timestamp_matches_log": 0.0,
        "error_signature_matches_log": 0.0,
        "repro_stderr_captured_with_keyerror": 0.0,
        "scripts_not_modified": 0.0,
        "config_fixed_for_input_dir": 0.0,
        "success_output_exists": 0.0,
        "success_run_logs_captured": 0.0,
        "revenue_summary_totals_correct": 0.0,
        "incident_report_totals_match_output": 0.0,
    }

    log_path = workspace / "logs" / "reconcile-2026-04-15.log"
    repro_stderr_path = workspace / "artifacts" / "repro_stderr.txt"
    success_run_path = workspace / "artifacts" / "success_run.txt"
    incident_report_path = workspace / "artifacts" / "incident_report.json"
    output_csv_path = workspace / "out" / "revenue_summary.csv"
    config_path = workspace / "config" / "finance.json"
    script_path = workspace / "scripts" / "reconcile.py"
    tx_path = workspace / "data" / "incoming" / "transactions.csv"

    # Parse expected timestamp and error signature from log
    expected_failed_ts = None
    expected_error_sig = None
    log_text = _read_text(log_path)
    if log_text is not None:
        expected_failed_ts, expected_error_sig = _parse_log_last_error_info(log_text)

    # Incident report validation
    incident = _load_json(incident_report_path)
    incident_ok = False
    if isinstance(incident, dict):
        if (
            incident.get("incident") == "monthly_revenue_reconcile"
            and isinstance(incident.get("failed_at_utc"), str)
            and isinstance(incident.get("error_signature"), str)
            and isinstance(incident.get("root_cause"), str)
            and isinstance(incident.get("fix_applied"), str)
            and isinstance(incident.get("verification"), dict)
        ):
            ver = incident.get("verification", {})
            totals_dict = ver.get("totals")
            if (
                ver.get("output_file") == "out/revenue_summary.csv"
                and isinstance(totals_dict, dict)
                and "USD" in totals_dict
                and "EUR" in totals_dict
            ):
                rc = incident.get("root_cause", "").lower()
                fa_str = incident.get("fix_applied", "")
                fa = fa_str.lower()
                rc_ok = ("input_dir" in rc) and ("keyerror" in rc or "missing" in rc)
                fa_ok = ("config/finance.json" in fa_str) and ("input_dir" in fa) and ("data/incoming" in fa)
                if rc_ok and fa_ok:
                    incident_ok = True
    if incident_ok:
        scores["incident_report_has_expected_fields"] = 1.0

    # Cross-check incident fields with log
    if incident_ok and expected_failed_ts is not None:
        if incident.get("failed_at_utc") == expected_failed_ts:
            scores["failed_timestamp_matches_log"] = 1.0
    if incident_ok and expected_error_sig is not None:
        if incident.get("error_signature") == expected_error_sig:
            scores["error_signature_matches_log"] = 1.0

    # Repro stderr captured
    repro_text = _read_text(repro_stderr_path)
    if repro_text is not None:
        repro_norm = _normalize_text(repro_text)
        if ("Traceback (most recent call last)" in repro_norm) and ("KeyError: 'input_dir'" in repro_norm):
            scores["repro_stderr_captured_with_keyerror"] = 1.0

    # Only award scripts_not_modified if work was attempted (avoid baseline credit)
    work_attempted = any([
        incident_report_path.exists(),
        output_csv_path.exists(),
        repro_stderr_path.exists(),
        success_run_path.exists(),
    ])
    if work_attempted:
        expected_script = (
            "import argparse\n"
            "import json\n"
            "import os\n"
            "import csv\n"
            "from decimal import Decimal, ROUND_HALF_UP\n\n\n"
            "def read_config(path):\n"
            "    with open(path, 'r', encoding='utf-8') as f:\n"
            "        return json.load(f)\n\n\n"
            "def main():\n"
            "    parser = argparse.ArgumentParser(description=\"Studio revenue reconciliation\")\n"
            "    parser.add_argument('--config', required=True, help='Path to JSON config')\n"
            "    args = parser.parse_args()\n\n"
            "    cfg = read_config(args.config)\n"
            "    # Expect required keys; KeyError here should fail loudly if config is wrong\n"
            "    input_dir = cfg['input_dir']\n"
            "    output_dir = cfg['output_dir']\n\n"
            "    tx_path = os.path.join(input_dir, 'transactions.csv')\n"
            "    if not os.path.exists(tx_path):\n"
            "        raise FileNotFoundError(f\"transactions.csv not found at {tx_path}\")\n\n"
            "    os.makedirs(output_dir, exist_ok=True)\n\n"
            "    totals = {}\n"
            "    count = 0\n"
            "    with open(tx_path, 'r', encoding='utf-8', newline='') as f:\n"
            "        reader = csv.DictReader(f)\n"
            "        for row in reader:\n"
            "            currency = row['currency'].strip()\n"
            "            amt = Decimal(row['amount']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)\n"
            "            totals[currency] = totals.get(currency, Decimal('0.00')) + amt\n"
            "            count += 1\n\n"
            "    out_path = os.path.join(output_dir, 'revenue_summary.csv')\n"
            "    with open(out_path, 'w', encoding='utf-8', newline='') as f:\n"
            "        writer = csv.writer(f)\n"
            "        writer.writerow(['currency', 'total_amount'])\n"
            "        for curr in sorted(totals.keys()):\n"
            "            writer.writerow([curr, f\"{totals[curr]:.2f}\"])\n\n"
            "    print(f\"Processed {count} transactions from {tx_path}\")\n"
            "    print(f\"Wrote summary to {out_path}\")\n\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        actual_script_text = _read_text(script_path)
        if actual_script_text is not None:
            if _normalize_text(actual_script_text).strip() == _normalize_text(expected_script).strip():
                scores["scripts_not_modified"] = 1.0

    # Config fixed check (must include input_dir and output_dir)
    cfg = _load_json(config_path)
    if isinstance(cfg, dict):
        input_dir_val = cfg.get("input_dir")
        output_dir_val = cfg.get("output_dir")
        if isinstance(input_dir_val, str) and isinstance(output_dir_val, str):
            if input_dir_val == "data/incoming" and output_dir_val == "out":
                scores["config_fixed_for_input_dir"] = 1.0

    # Success output existence
    if output_csv_path.exists() and output_csv_path.is_file():
        scores["success_output_exists"] = 1.0

    # Success run logs captured
    success_text = _read_text(success_run_path)
    if success_text is not None:
        s_norm = _normalize_text(success_text)
        if ("Processed " in s_norm) and ("Wrote summary to out/revenue_summary.csv" in s_norm):
            scores["success_run_logs_captured"] = 1.0

    # Verify revenue_summary totals against transactions.csv
    rev_totals = None
    if output_csv_path.exists():
        rev_totals = _parse_revenue_summary(output_csv_path)
    tx_rows = None
    if tx_path.exists():
        tx_rows = _parse_csv_file(tx_path)
    expected_totals = None
    if tx_rows is not None:
        expected_totals = _compute_totals_from_transactions(tx_rows)
    if rev_totals is not None and expected_totals is not None:
        if set(rev_totals.keys()) == set(expected_totals.keys()) and all(
            rev_totals.get(k) == expected_totals.get(k) for k in expected_totals.keys()
        ):
            if "USD" in rev_totals and "EUR" in rev_totals:
                scores["revenue_summary_totals_correct"] = 1.0

    # Incident report totals must match output file totals
    if incident_ok and rev_totals is not None:
        ver_totals = incident["verification"]["totals"]
        if (
            "USD" in ver_totals
            and "EUR" in ver_totals
            and ver_totals["USD"] == rev_totals.get("USD")
            and ver_totals["EUR"] == rev_totals.get("EUR")
        ):
            scores["incident_report_totals_match_output"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()