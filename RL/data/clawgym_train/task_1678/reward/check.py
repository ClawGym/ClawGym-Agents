import json
import csv
import sys
import subprocess
from pathlib import Path


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames
        return rows, header
    except Exception:
        return None, None


def _parse_float_maybe(s):
    try:
        return float(s)
    except Exception:
        return None


def _parse_int_maybe(s):
    try:
        return int(s)
    except Exception:
        try:
            f = float(s)
            if abs(f - int(f)) < 1e-9:
                return int(f)
            return None
        except Exception:
            return None


def _split_tokens(s):
    if s is None:
        return []
    tokens = [t.strip() for t in s.split(";")]
    return [t for t in tokens if t]


def _run_script(script_path: Path, cwd: Path, timeout: int = 20) -> bool:
    try:
        proc = subprocess.run([sys.executable, str(script_path)], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0
    except Exception:
        return False


def _compute_expected(items_csv: Path, suppliers_json: Path, policy_json: Path):
    suppliers = _load_json(suppliers_json)
    items_rows, _ = _load_csv_dicts(items_csv)
    policy = _load_json(policy_json)
    if suppliers is None or items_rows is None or policy is None:
        return None

    suppliers_map = {s["supplier_id"]: s for s in suppliers if isinstance(s, dict) and "supplier_id" in s}
    local_radius = policy.get("local_radius_miles")

    expected_noncompliant = []
    supplier_stats = {}
    total_items = 0
    compliant_items = 0
    noncompliant_items = 0

    for r in items_rows:
        try:
            item_id = r["item_id"].strip()
            item_name = r["item_name"].strip()
            supplier_id = r["supplier_id"].strip()
            distance = float(r["distance_miles"])
            claimed_labels = _split_tokens(r.get("claimed_labels", ""))
        except Exception:
            return None

        total_items += 1
        if supplier_id not in supplier_stats:
            supplier_stats[supplier_id] = {
                "supplier_id": supplier_id,
                "supplier_name": suppliers_map.get(supplier_id, {}).get("name", ""),
                "total_items": 0,
                "noncompliant_items": 0,
                "false_local_count": 0,
                "false_usda_organic_count": 0,
            }

        supplier_stats[supplier_id]["total_items"] += 1

        violations = []
        severity = 0
        if "LOCAL" in claimed_labels:
            if local_radius is None:
                return None
            if distance > float(local_radius):
                violations.append("false_local")
                severity += 1
        if "USDA_ORGANIC" in claimed_labels:
            sup = suppliers_map.get(supplier_id, {})
            certified = bool(sup.get("usda_organic_certified", False))
            if not certified:
                violations.append("false_usda_organic")
                severity += 2

        if violations:
            noncompliant_items += 1
            supplier_stats[supplier_id]["noncompliant_items"] += 1
            supplier_stats[supplier_id]["false_local_count"] += 1 if "false_local" in violations else 0
            supplier_stats[supplier_id]["false_usda_organic_count"] += 1 if "false_usda_organic" in violations else 0
            expected_noncompliant.append({
                "item_id": item_id,
                "item_name": item_name,
                "supplier_id": supplier_id,
                "distance_miles": float(distance),
                "claimed_labels": ";".join(claimed_labels),
                "violations": ";".join(violations),
                "severity_score": int(severity),
            })
        else:
            compliant_items += 1

    expected_noncompliant.sort(key=lambda x: (-x["severity_score"], x["item_id"]))

    expected_supplier_rows = []
    for sid, stats in supplier_stats.items():
        total = stats["total_items"]
        noncomp = stats["noncompliant_items"]
        rate = (noncomp / total) if total > 0 else 0.0
        expected_supplier_rows.append({
            "supplier_id": sid,
            "supplier_name": stats["supplier_name"],
            "total_items": int(total),
            "noncompliant_items": int(noncomp),
            "noncompliance_rate": round(rate, 2),
            "false_local_count": int(stats["false_local_count"]),
            "false_usda_organic_count": int(stats["false_usda_organic_count"]),
        })
    expected_supplier_rows.sort(key=lambda x: (-x["noncompliance_rate"], x["supplier_id"]))

    overall = {
        "local_radius_miles": int(policy.get("local_radius_miles")) if policy.get("local_radius_miles") is not None else None,
        "total_items": int(total_items),
        "compliant_items": int(compliant_items),
        "noncompliant_items": int(noncompliant_items),
        "noncompliance_rate": round(noncompliant_items / total_items, 2) if total_items > 0 else 0.0,
        "disclaimers": policy.get("disclaimers"),
    }

    return {
        "noncompliant": expected_noncompliant,
        "supplier_summary": expected_supplier_rows,
        "overall": overall,
    }


def _parse_noncompliance_file(path: Path):
    rows, header = _load_csv_dicts(path)
    if rows is None or header is None:
        return None, None
    expected_header = ["item_id", "item_name", "supplier_id", "distance_miles", "claimed_labels", "violations", "severity_score"]
    if header != expected_header:
        return {"__header_mismatch__": header}, expected_header

    parsed = []
    for r in rows:
        item_id = r.get("item_id", "").strip()
        item_name = r.get("item_name", "").strip()
        supplier_id = r.get("supplier_id", "").strip()
        dm = _parse_float_maybe(r.get("distance_miles", "").strip())
        cl = r.get("claimed_labels", "").strip()
        v = r.get("violations", "").strip()
        sev = _parse_int_maybe(r.get("severity_score", "").strip())
        if not item_id or dm is None or sev is None:
            return None, None
        parsed.append({
            "item_id": item_id,
            "item_name": item_name,
            "supplier_id": supplier_id,
            "distance_miles": dm,
            "claimed_labels": cl,
            "violations": v,
            "severity_score": sev,
        })
    return parsed, expected_header


def _parse_supplier_summary_file(path: Path):
    rows, header = _load_csv_dicts(path)
    if rows is None or header is None:
        return None, None
    expected_header = ["supplier_id", "supplier_name", "total_items", "noncompliant_items", "noncompliance_rate", "false_local_count", "false_usda_organic_count"]
    if header != expected_header:
        return {"__header_mismatch__": header}, expected_header
    parsed = []
    for r in rows:
        sid = r.get("supplier_id", "").strip()
        sname = r.get("supplier_name", "").strip()
        total = _parse_int_maybe(r.get("total_items", "").strip())
        noncomp = _parse_int_maybe(r.get("noncompliant_items", "").strip())
        rate = _parse_float_maybe(r.get("noncompliance_rate", "").strip())
        flc = _parse_int_maybe(r.get("false_local_count", "").strip())
        fuc = _parse_int_maybe(r.get("false_usda_organic_count", "").strip())
        if not sid or total is None or noncomp is None or rate is None or flc is None or fuc is None:
            return None, None
        parsed.append({
            "supplier_id": sid,
            "supplier_name": sname,
            "total_items": total,
            "noncompliant_items": noncomp,
            "noncompliance_rate": rate,
            "false_local_count": flc,
            "false_usda_organic_count": fuc,
        })
    return parsed, expected_header


def _check_overall_summary(path: Path, expected):
    text = _read_text(path)
    if text is None:
        return 0.0
    lines = [ln.strip() for ln in text.splitlines()]

    keys = {
        "local_radius_miles": None,
        "total_items": None,
        "compliant_items": None,
        "noncompliant_items": None,
        "noncompliance_rate": None,
    }
    for ln in lines:
        if ":" in ln:
            parts = ln.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key in keys and keys[key] is None:
                keys[key] = val

    try:
        if keys["local_radius_miles"] is None or int(float(keys["local_radius_miles"])) != expected["local_radius_miles"]:
            return 0.0
        if keys["total_items"] is None or int(float(keys["total_items"])) != expected["total_items"]:
            return 0.0
        if keys["compliant_items"] is None or int(float(keys["compliant_items"])) != expected["compliant_items"]:
            return 0.0
        if keys["noncompliant_items"] is None or int(float(keys["noncompliant_items"])) != expected["noncompliant_items"]:
            return 0.0
        if keys["noncompliance_rate"] is None:
            return 0.0
        got_rate = float(keys["noncompliance_rate"])
        if round(got_rate, 2) != expected["noncompliance_rate"]:
            return 0.0
    except Exception:
        return 0.0

    idx = None
    for i, ln in enumerate(lines):
        if ln.lower() == "disclaimers" or ln.lower() == "disclaimers:":
            idx = i
            break
    if idx is None:
        return 0.0
    disclaimers_list = []
    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        if ln.startswith("- "):
            disclaimers_list.append(ln[2:].strip())
        elif ln == "":
            continue
        else:
            break
    required_disclaimers = {
        "Local means within 100 miles of pickup point.",
        "USDA Organic claims are based on supplier certifications listed in suppliers.json.",
    }
    if set(disclaimers_list) != required_disclaimers:
        return 0.0

    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "policy_local_radius_miles_100": 0.0,
        "policy_disclaimers_exact": 0.0,
        "policy_allowed_labels_unchanged": 0.0,
        "script_execution_and_outputs": 0.0,
        "noncompliance_items_csv_correct": 0.0,
        "supplier_summary_csv_correct": 0.0,
        "overall_summary_md_correct": 0.0,
    }

    policy_path = workspace / "config" / "policy.json"
    suppliers_path = workspace / "data" / "suppliers.json"
    items_path = workspace / "data" / "items.csv"
    script_path = workspace / "scripts" / "check_compliance.py"
    out_noncomp = workspace / "output" / "noncompliance_items.csv"
    out_supplier = workspace / "output" / "supplier_summary.csv"
    out_summary = workspace / "output" / "overall_summary.md"

    policy = _load_json(policy_path)
    disclaimers_ok = False
    lrm_ok = False
    if isinstance(policy, dict):
        lrm = policy.get("local_radius_miles")
        try:
            if lrm is not None and float(lrm) == 100.0:
                scores["policy_local_radius_miles_100"] = 1.0
                lrm_ok = True
        except Exception:
            lrm_ok = False

        disclaimers = policy.get("disclaimers", None)
        if isinstance(disclaimers, dict):
            expected_disclaimers = {
                "local_label": "Local means within 100 miles of pickup point.",
                "organic_label": "USDA Organic claims are based on supplier certifications listed in suppliers.json.",
            }
            if set(disclaimers.keys()) == set(expected_disclaimers.keys()):
                if all(disclaimers.get(k) == v for k, v in expected_disclaimers.items()):
                    scores["policy_disclaimers_exact"] = 1.0
                    disclaimers_ok = True

        allowed = policy.get("allowed_labels", None)
        # Gate awarding this point on the policy having been updated (radius and disclaimers correct)
        if lrm_ok and disclaimers_ok and isinstance(allowed, list) and allowed == ["LOCAL", "USDA_ORGANIC"]:
            scores["policy_allowed_labels_unchanged"] = 1.0

    ran = False
    if script_path.exists():
        ran = _run_script(script_path, workspace)

    if ran and out_noncomp.exists() and out_supplier.exists() and out_summary.exists():
        scores["script_execution_and_outputs"] = 1.0

    expected = _compute_expected(items_path, suppliers_path, policy_path)

    if expected is not None and out_noncomp.exists():
        parsed_rows, header_info = _parse_noncompliance_file(out_noncomp)
        if isinstance(parsed_rows, dict) and "__header_mismatch__" in parsed_rows:
            scores["noncompliance_items_csv_correct"] = 0.0
        elif parsed_rows is not None:
            exp_rows = expected["noncompliant"]
            if len(parsed_rows) == len(exp_rows):
                ok = True
                expected_order = [r["item_id"] for r in exp_rows]
                got_order = [r["item_id"] for r in parsed_rows]
                if expected_order != got_order:
                    ok = False
                else:
                    exp_map = {r["item_id"]: r for r in exp_rows}
                    for row in parsed_rows:
                        eid = row["item_id"]
                        e = exp_map.get(eid)
                        if e is None:
                            ok = False
                            break
                        if row["item_name"] != e["item_name"]:
                            ok = False
                            break
                        if row["supplier_id"] != e["supplier_id"]:
                            ok = False
                            break
                        if abs(float(row["distance_miles"]) - float(e["distance_miles"])) > 1e-9:
                            ok = False
                            break
                        if row["claimed_labels"] != e["claimed_labels"]:
                            ok = False
                            break
                        got_v = set(_split_tokens(row["violations"]))
                        exp_v = set(_split_tokens(e["violations"]))
                        if got_v != exp_v:
                            ok = False
                            break
                        if int(row["severity_score"]) != int(e["severity_score"]):
                            ok = False
                            break
                if ok:
                    scores["noncompliance_items_csv_correct"] = 1.0

    if expected is not None and out_supplier.exists():
        parsed_sup, sup_header = _parse_supplier_summary_file(out_supplier)
        if isinstance(parsed_sup, dict) and "__header_mismatch__" in parsed_sup:
            scores["supplier_summary_csv_correct"] = 0.0
        elif parsed_sup is not None:
            exp_sup = expected["supplier_summary"]
            if len(parsed_sup) == len(exp_sup):
                ok = True
                exp_order = [r["supplier_id"] for r in exp_sup]
                got_order = [r["supplier_id"] for r in parsed_sup]
                if exp_order != got_order:
                    ok = False
                else:
                    exp_map = {r["supplier_id"]: r for r in exp_sup}
                    for row in parsed_sup:
                        sid = row["supplier_id"]
                        e = exp_map.get(sid)
                        if e is None:
                            ok = False
                            break
                        if row["supplier_name"] != e["supplier_name"]:
                            ok = False
                            break
                        if int(row["total_items"]) != int(e["total_items"]):
                            ok = False
                            break
                        if int(row["noncompliant_items"]) != int(e["noncompliant_items"]):
                            ok = False
                            break
                        try:
                            got_rate = float(row["noncompliance_rate"])
                        except Exception:
                            ok = False
                            break
                        if round(got_rate, 2) != e["noncompliance_rate"]:
                            ok = False
                            break
                        if int(row["false_local_count"]) != int(e["false_local_count"]):
                            ok = False
                            break
                        if int(row["false_usda_organic_count"]) != int(e["false_usda_organic_count"]):
                            ok = False
                            break
                if ok:
                    scores["supplier_summary_csv_correct"] = 1.0

    if expected is not None and out_summary.exists():
        scores["overall_summary_md_correct"] = _check_overall_summary(out_summary, expected["overall"])

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()