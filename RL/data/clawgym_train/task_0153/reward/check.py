import json
import os
import sys
import csv

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def approx_equal(a, b, tol=1e-9):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "risk_report_exists": False,
        "risk_report_is_array": False,
        "risk_report_length_matches": False,
        "risk_report_users_exact": False,
        "risk_report_keys_exact": False,
        "risk_report_types_correct": False,
        "risk_report_values_canonical": False,
        "risk_report_buckets_correct": False,
        "risk_report_portfolio_mapping_correct": False,
        "summary_exists": False,
        "summary_header_correct": False,
        "summary_rows_count_matches": False,
        "summary_users_match": False,
        "summary_values_canonical": False,
        "aggregate_exists": False,
        "aggregate_structure_correct": False,
        "aggregate_counts_correct": False,
    }

    # Load reference input data
    expected_users = []
    user_to_portfolio = {}
    users_csv_path = os.path.join(input_dir, "users.csv")
    users_rows = parse_csv_rows(users_csv_path)
    if users_rows and len(users_rows) >= 2:
        header = users_rows[0]
        # Expect columns userId,portfolio_id
        # Find indices to be robust
        try:
            uid_idx = header.index("userId")
            pid_idx = header.index("portfolio_id")
            for row in users_rows[1:]:
                if len(row) <= max(uid_idx, pid_idx):
                    continue
                uid = row[uid_idx].strip()
                pid = row[pid_idx].strip()
                if uid:
                    expected_users.append(uid)
                    user_to_portfolio[uid] = pid
        except ValueError:
            # Header missing expected columns; fall back to known users
            expected_users = ["u_alice", "u_bob", "u_carla"]
            user_to_portfolio = {"u_alice": "p1", "u_bob": "p2", "u_carla": "p3"}
    else:
        # Fallback to known expected users as per task
        expected_users = ["u_alice", "u_bob", "u_carla"]
        user_to_portfolio = {"u_alice": "p1", "u_bob": "p2", "u_carla": "p3"}

    expected_user_set = set(expected_users)
    expected_len = len(expected_users)

    # Reference portfolios file existence (for mapping validation if needed)
    portfolios_path = os.path.join(input_dir, "portfolios.json")
    portfolios_data = load_json_file(portfolios_path)
    portfolios_ids = set()
    if isinstance(portfolios_data, dict):
        portfolios_ids = set(portfolios_data.keys())

    # Canonical tool outputs
    CANON_RISK_SCORE = 0.45
    CANON_EXPOSURE = 0.35
    CANON_DRAWDOWN = "-15%"
    CANON_NOTE = "Risk evaluator simulation."

    # ========== Check risk_report.json ==========
    risk_report_path = os.path.join(output_dir, "risk_report.json")
    risk_report = load_json_file(risk_report_path)
    if risk_report is not None:
        checks["risk_report_exists"] = True
        if isinstance(risk_report, list):
            checks["risk_report_is_array"] = True
            if len(risk_report) == expected_len:
                checks["risk_report_length_matches"] = True

            # Collect userIds
            user_ids_found = []
            keys_exact_ok = True
            types_ok = True
            values_ok = True
            buckets_ok = True
            mapping_ok = True

            expected_keys = {"userId", "portfolio_id", "risk_score", "portfolio_exposure", "max_drawdown", "note", "bucket"}

            for entry in risk_report if isinstance(risk_report, list) else []:
                # Keys exact
                if not isinstance(entry, dict) or set(entry.keys()) != expected_keys:
                    keys_exact_ok = False
                else:
                    # Track userId
                    uid = entry.get("userId")
                    pid = entry.get("portfolio_id")

                    # Types
                    # risk_score and portfolio_exposure must be numbers (int or float)
                    rs = entry.get("risk_score")
                    pe = entry.get("portfolio_exposure")
                    md = entry.get("max_drawdown")
                    note = entry.get("note")
                    bucket = entry.get("bucket")

                    rs_num = isinstance(rs, (int, float))
                    pe_num = isinstance(pe, (int, float))
                    md_str = isinstance(md, str)
                    note_str = isinstance(note, str)
                    bucket_str = isinstance(bucket, str)
                    uid_str = isinstance(uid, str)
                    pid_str = isinstance(pid, str)
                    if not (rs_num and pe_num and md_str and note_str and bucket_str and uid_str and pid_str):
                        types_ok = False

                    # Values canonical
                    if rs_num:
                        if not approx_equal(rs, CANON_RISK_SCORE):
                            values_ok = False
                    else:
                        values_ok = False
                    if pe_num:
                        if not approx_equal(pe, CANON_EXPOSURE):
                            values_ok = False
                    else:
                        values_ok = False
                    if md != CANON_DRAWDOWN:
                        values_ok = False
                    if note != CANON_NOTE:
                        values_ok = False

                    # Bucket correctness: classify by thresholds
                    # low if rs < 0.3; medium if 0.3 <= rs < 0.7; high if rs >= 0.7
                    computed_bucket = None
                    try:
                        rsv = float(rs)
                        if rsv < 0.3:
                            computed_bucket = "low"
                        elif rsv < 0.7:
                            computed_bucket = "medium"
                        else:
                            computed_bucket = "high"
                    except Exception:
                        computed_bucket = None
                    if bucket != computed_bucket:
                        buckets_ok = False

                    # Portfolio mapping correctness: check matches input mapping and exists in portfolios.json if available
                    expected_pid = user_to_portfolio.get(uid)
                    if expected_pid is None or pid != expected_pid:
                        mapping_ok = False
                    # If portfolios.json available, ensure pid exists in it
                    if portfolios_ids:
                        if pid not in portfolios_ids:
                            mapping_ok = False

                    # Collect userId for uniqueness and set check
                    if uid is not None:
                        user_ids_found.append(uid)

            # Check users exact set and no duplicates
            if set(user_ids_found) == expected_user_set and len(user_ids_found) == expected_len:
                checks["risk_report_users_exact"] = True

            checks["risk_report_keys_exact"] = keys_exact_ok
            checks["risk_report_types_correct"] = types_ok
            checks["risk_report_values_canonical"] = values_ok
            checks["risk_report_buckets_correct"] = buckets_ok
            checks["risk_report_portfolio_mapping_correct"] = mapping_ok

    # ========== Check summary.csv ==========
    summary_path = os.path.join(output_dir, "summary.csv")
    summary_rows = parse_csv_rows(summary_path)
    if summary_rows:
        checks["summary_exists"] = True
        # Header check
        header_expected = ["userId", "risk_score", "portfolio_exposure", "max_drawdown", "bucket"]
        header_ok = False
        if len(summary_rows) >= 1:
            header = summary_rows[0]
            # Exact header match
            if header == header_expected:
                header_ok = True
        checks["summary_header_correct"] = header_ok

        # Rows count
        data_rows = summary_rows[1:] if len(summary_rows) > 1 else []
        if len(data_rows) == expected_len:
            checks["summary_rows_count_matches"] = True

        # Validate each row
        users_in_csv = []
        values_ok = True
        users_ok = False
        if data_rows:
            for row in data_rows:
                if len(row) != len(header_expected):
                    values_ok = False
                    continue
                uid, rs_s, pe_s, md_s, bucket_s = row
                users_in_csv.append(uid)
                # Compare values: numeric fields compare by float; strings exact
                if not approx_equal(rs_s, CANON_RISK_SCORE):
                    values_ok = False
                if not approx_equal(pe_s, CANON_EXPOSURE):
                    values_ok = False
                if md_s != CANON_DRAWDOWN:
                    values_ok = False
                if bucket_s != "medium":
                    values_ok = False

            if set(users_in_csv) == expected_user_set and len(users_in_csv) == expected_len:
                users_ok = True

        checks["summary_users_match"] = users_ok
        checks["summary_values_canonical"] = values_ok

    # ========== Check aggregate.json ==========
    aggregate_path = os.path.join(output_dir, "aggregate.json")
    aggregate = load_json_file(aggregate_path)
    if isinstance(aggregate, dict):
        checks["aggregate_exists"] = True
        structure_ok = ("processed_count" in aggregate and
                        "bucket_counts" in aggregate and
                        isinstance(aggregate.get("bucket_counts"), dict))
        if structure_ok:
            bc = aggregate["bucket_counts"]
            structure_ok = all(k in bc for k in ["low", "medium", "high"])
            # Type checks
            if structure_ok:
                if not isinstance(aggregate.get("processed_count"), int):
                    structure_ok = False
                if not (isinstance(bc.get("low"), int) and isinstance(bc.get("medium"), int) and isinstance(bc.get("high"), int)):
                    structure_ok = False
        checks["aggregate_structure_correct"] = structure_ok

        counts_ok = False
        if structure_ok:
            if (aggregate.get("processed_count") == expected_len and
                aggregate["bucket_counts"].get("low") == 0 and
                aggregate["bucket_counts"].get("medium") == expected_len and
                aggregate["bucket_counts"].get("high") == 0):
                counts_ok = True
        checks["aggregate_counts_correct"] = counts_ok

    # Compute reward
    # Weights: risk_report group 0.6, summary group 0.25, aggregate group 0.15
    reward = 0.0

    # Risk report sub-weights sum to 0.6
    rr_checks = [
        "risk_report_exists",
        "risk_report_is_array",
        "risk_report_length_matches",
        "risk_report_users_exact",
        "risk_report_keys_exact",
        "risk_report_types_correct",
        "risk_report_values_canonical",
        "risk_report_buckets_correct",
        "risk_report_portfolio_mapping_correct",
    ]
    rr_weight = 0.6
    if rr_checks:
        per = rr_weight / len(rr_checks)
        for k in rr_checks:
            if checks.get(k, False):
                reward += per

    # Summary sub-weights sum to 0.25
    sum_checks = [
        "summary_exists",
        "summary_header_correct",
        "summary_rows_count_matches",
        "summary_users_match",
        "summary_values_canonical",
    ]
    sum_weight = 0.25
    if sum_checks:
        per = sum_weight / len(sum_checks)
        for k in sum_checks:
            if checks.get(k, False):
                reward += per

    # Aggregate sub-weights sum to 0.15
    agg_checks = [
        "aggregate_exists",
        "aggregate_structure_correct",
        "aggregate_counts_correct",
    ]
    agg_weight = 0.15
    if agg_checks:
        per = agg_weight / len(agg_checks)
        for k in agg_checks:
            if checks.get(k, False):
                reward += per

    # Ensure reward is between 0 and 1
    reward = max(0.0, min(1.0, reward))

    # No-op baseline: if output is missing entirely, reward should be exactly 0.0
    # This is already handled by checks being False.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()