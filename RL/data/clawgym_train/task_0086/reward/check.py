import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _load_csv_dicts(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _build_glossaries(gloss_rows: List[Dict[str, str]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    exact = {}
    lower = {}
    for r in gloss_rows:
        fr = (r.get("fr") or "").strip()
        en = (r.get("en") or "").strip()
        if fr:
            exact[fr] = en
            lower[fr.lower()] = en
    return exact, lower


def _token_replace_glossary(text: str, lower_gloss: Dict[str, str]) -> str:
    if text is None:
        return ""
    # Split into word and non-word tokens to preserve punctuation and spacing
    parts = re.findall(r"\w+|\W+", text, flags=re.UNICODE)
    out = []
    for p in parts:
        if re.match(r"^\w+$", p, flags=re.UNICODE):
            en = lower_gloss.get(p.lower())
            out.append(en if en is not None else p)
        else:
            out.append(p)
    return "".join(out)


def _compute_expected_bilingual(orders: List[Dict[str, str]], exact_gloss: Dict[str, str], lower_gloss: Dict[str, str]) -> List[Dict[str, str]]:
    expected = []
    for r in orders:
        status = (r.get("status") or "").strip()
        if status != "open":
            continue
        gid = (r.get("id") or "").strip()
        client = (r.get("client_name") or "").strip()
        garment_fr = (r.get("garment_type_fr") or "").strip()
        fabric_fr = (r.get("fabric_fr") or "").strip()
        due = (r.get("due_date") or "").strip()
        cost = (r.get("cost_livres") or "").strip()
        notes_fr = r.get("notes_fr") or ""
        # Translate garment and fabric: exact first, then lower fallback
        garment_en = exact_gloss.get(garment_fr)
        if garment_en is None:
            garment_en = lower_gloss.get(garment_fr.lower(), garment_fr)
        fabric_en = exact_gloss.get(fabric_fr)
        if fabric_en is None:
            fabric_en = lower_gloss.get(fabric_fr.lower(), fabric_fr)
        # Notes replacement
        notes_en = _token_replace_glossary(notes_fr, lower_gloss)
        expected.append({
            "id": gid,
            "client_name": client,
            "garment_type_fr": garment_fr,
            "garment_type_en": garment_en,
            "fabric_fr": fabric_fr,
            "fabric_en": fabric_en,
            "due_date": due,
            "cost_livres": cost,
            "notes_fr": notes_fr,
            "notes_en": notes_en,
        })
    return expected


def _read_csv_rows_with_header(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data_rows = []
        for line in rows[1:]:
            row_dict = {header[i]: (line[i] if i < len(line) else "") for i in range(len(header))}
            data_rows.append(row_dict)
        return data_rows, header
    except Exception:
        return None


def _aggregate_top_clients(open_expected: List[Dict[str, str]]) -> List[Tuple[str, int, int, int]]:
    # returns list of tuples: (client_name, total, count, first_index)
    totals = {}
    order_indices = {}
    for idx, r in enumerate(open_expected):
        client = r["client_name"]
        cost = _parse_int(r["cost_livres"]) or 0
        totals.setdefault(client, 0)
        totals[client] += cost
        order_indices.setdefault(client, idx)
    agg = [(client, totals[client], sum(1 for _r in open_expected if _r["client_name"] == client), order_indices[client]) for client in totals]
    # sort by total desc, then by first occurrence index (stable)
    agg.sort(key=lambda x: (-x[1], x[3]))
    return agg


def _compute_priority_open(open_expected: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # sort by cost desc, tie by due_date asc, then by input order as last resort
    sortable = []
    for idx, r in enumerate(open_expected):
        cost = _parse_int(r["cost_livres"]) or 0
        due_dt = _parse_date(r["due_date"]) or datetime.max
        sortable.append((cost, due_dt, idx, r))
    sortable.sort(key=lambda x: (-x[0], x[1], x[2]))
    top = [entry[3] for entry in sortable[:5]]
    result = []
    for i, r in enumerate(top, start=1):
        result.append({
            "rank": str(i),
            "id": r["id"],
            "client_name": r["client_name"],
            "cost_livres": r["cost_livres"],
            "due_date": r["due_date"],
        })
    return result


def _safe_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def _find_line_with_both(text: str, a: str, b: str) -> bool:
    al = a.lower()
    bl = b.lower()
    for line in text.splitlines():
        l = line.lower()
        if al in l and bl in l:
            return True
    return False


def _contains_count_statement(report: str, label: str, count: int) -> bool:
    # Look for a line containing label and the number
    lbl = label.lower()
    num = str(count)
    for line in report.splitlines():
        l = line.lower()
        if lbl in l and num in l:
            return True
    return False


def _parse_cli_output(cli_text: str) -> Dict[str, any]:
    warnings = []
    errors = []
    warn_count = 0
    err_count = 0
    for line in cli_text.splitlines():
        if line.startswith("[WARNING]"):
            warn_count += 1
            # Example: [WARNING] Order ID 103: Unknown term "Basques"
            m = re.search(r"Order ID\s+(\d+):\s+Unknown term\s+\"([^\"]+)\"", line)
            if m:
                order_id = m.group(1)
                term = m.group(2)
                warnings.append({"order_id": order_id, "term": term})
        elif line.startswith("[ERROR]"):
            err_count += 1
            # Example: [ERROR] Row 8 (Order ID 108): ...
            m = re.search(r"Order ID\s+(\d+)", line)
            if m:
                order_id = m.group(1)
                errors.append({"order_id": order_id, "line": line})
            else:
                errors.append({"order_id": None, "line": line})
    return {"warnings": warnings, "errors": errors, "warning_count": warn_count, "error_count": err_count}


def _client_name_to_filename(client_name: str) -> str:
    # Replace spaces with underscores only
    return client_name.replace(" ", "_")


def _check_letters_headers(file_path: Path, order: Dict[str, str], lang: str, garment_en: str, fabric_en: str) -> bool:
    lines = _safe_lines(file_path)
    if lines is None or len(lines) < 7:
        return False
    expected_headers = [
        f"Client: {order['client_name']}",
        f"Order ID: {order['id']}",
        f"Due date: {order['due_date']}",
        f"Garment: {order['garment_type_fr']} ({garment_en})",
        f"Fabric: {order['fabric_fr']} ({fabric_en})",
        f"Estimated cost: {order['cost_livres']} livres",
    ]
    for i in range(6):
        if lines[i].rstrip("\n") != expected_headers[i]:
            return False
    # 7th line should be blank
    if lines[6] != "":
        return False
    # There should be at least one non-empty line after the blank
    body = lines[7:] if len(lines) > 7 else []
    has_non_empty = any(line.strip() != "" for line in body)
    if not has_non_empty:
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "orders_bilingual_exists_and_header": 0.0,
        "orders_bilingual_open_only_and_rowcount": 0.0,
        "orders_bilingual_field_translations": 0.0,
        "orders_bilingual_notes_en_replacement": 0.0,
        "top_clients_aggregation_correct": 0.0,
        "top_clients_sorting_desc": 0.0,
        "priority_open_orders_ranking": 0.0,
        "status_report_counts_correct": 0.0,
        "status_report_earliest_due_listed": 0.0,
        "status_report_top_clients_consistent": 0.0,
        "status_report_cli_analysis": 0.0,
        "status_report_error_open_affect_statement": 0.0,
        "status_report_remediation_paragraph": 0.0,
        "letters_files_present": 0.0,
        "letters_headers_correct": 0.0,
    }

    # Load inputs
    orders_path = workspace / "input" / "orders.csv"
    glossary_path = workspace / "input" / "glossary.csv"
    cli_output_path = workspace / "input" / "cli_output.txt"

    orders_loaded = _load_csv_dicts(orders_path)
    gloss_loaded = _load_csv_dicts(glossary_path)
    cli_text = _read_text(cli_output_path)

    if not orders_loaded or not gloss_loaded:
        # Cannot compute expected without inputs; leave scores at 0.0
        return scores

    orders_rows, orders_header = orders_loaded
    gloss_rows, gloss_header = gloss_loaded
    exact_gloss, lower_gloss = _build_glossaries(gloss_rows)

    # Compute expected open bilingual records
    expected_bilingual = _compute_expected_bilingual(orders_rows, exact_gloss, lower_gloss)
    expected_open_ids = [r["id"] for r in expected_bilingual]

    # 1) Validate out/orders_bilingual.csv
    out_bilingual_path = workspace / "out" / "orders_bilingual.csv"
    bilingual_loaded = _read_csv_rows_with_header(out_bilingual_path)
    expected_header_bilingual = ["id", "client_name", "garment_type_fr", "garment_type_en", "fabric_fr", "fabric_en", "due_date", "cost_livres", "notes_fr", "notes_en"]
    if bilingual_loaded:
        actual_rows, actual_header = bilingual_loaded
        # Header check
        if actual_header == expected_header_bilingual:
            scores["orders_bilingual_exists_and_header"] = 1.0
        # Row count and open-only IDs in correct order
        actual_ids = [row.get("id", "").strip() for row in actual_rows]
        if len(actual_rows) == len(expected_bilingual) and actual_ids == expected_open_ids:
            scores["orders_bilingual_open_only_and_rowcount"] = 1.0
        # Field translations (excluding notes_en)
        fields_ok = True
        if len(actual_rows) == len(expected_bilingual):
            for exp, act in zip(expected_bilingual, actual_rows):
                for key in ["id", "client_name", "garment_type_fr", "garment_type_en", "fabric_fr", "fabric_en", "due_date", "cost_livres", "notes_fr"]:
                    if (act.get(key) or "") != (exp.get(key) or ""):
                        fields_ok = False
                        break
                if not fields_ok:
                    break
        else:
            fields_ok = False
        if fields_ok:
            scores["orders_bilingual_field_translations"] = 1.0
        # Notes_en token replacement exact check
        notes_ok = True
        if len(actual_rows) == len(expected_bilingual):
            for exp, act in zip(expected_bilingual, actual_rows):
                if (act.get("notes_en") or "") != (exp.get("notes_en") or ""):
                    notes_ok = False
                    break
        else:
            notes_ok = False
        if notes_ok:
            scores["orders_bilingual_notes_en_replacement"] = 1.0

    # 2) Validate out/top_clients_by_spend.csv
    out_top_clients_path = workspace / "out" / "top_clients_by_spend.csv"
    top_loaded = _read_csv_rows_with_header(out_top_clients_path)
    if top_loaded:
        top_rows, top_header = top_loaded
        agg = _aggregate_top_clients(expected_bilingual)
        expected_top = [{"client_name": name, "total_cost_livres": str(total), "order_count": str(count)} for name, total, count, _idx in agg]
        # Aggregation correctness including header and exact rows
        if top_header == ["client_name", "total_cost_livres", "order_count"] and len(top_rows) == len(expected_top):
            content_ok = True
            for exp, act in zip(expected_top, top_rows):
                if (act.get("client_name") or "") != exp["client_name"]:
                    content_ok = False
                    break
                if str(_parse_int(act.get("total_cost_livres") or "")) != exp["total_cost_livres"]:
                    content_ok = False
                    break
                if str(_parse_int(act.get("order_count") or "")) != exp["order_count"]:
                    content_ok = False
                    break
            if content_ok:
                scores["top_clients_aggregation_correct"] = 1.0
        # Sorting descending by total
        if top_header and len(top_rows) > 0:
            # compute numeric totals list
            try:
                totals = [int(r.get("total_cost_livres", "0")) for r in top_rows]
                sorted_desc = all(totals[i] >= totals[i+1] for i in range(len(totals)-1))
                if sorted_desc:
                    scores["top_clients_sorting_desc"] = 1.0
            except Exception:
                pass

    # 3) Validate out/priority_open_orders.csv
    out_priority_path = workspace / "out" / "priority_open_orders.csv"
    priority_loaded = _read_csv_rows_with_header(out_priority_path)
    expected_priority = _compute_priority_open(expected_bilingual)
    if priority_loaded:
        pr_rows, pr_header = priority_loaded
        header_ok = pr_header == ["rank", "id", "client_name", "cost_livres", "due_date"]
        rows_ok = len(pr_rows) == len(expected_priority)
        all_ok = header_ok and rows_ok
        if all_ok:
            for exp, act in zip(expected_priority, pr_rows):
                for k in ["rank", "id", "client_name", "cost_livres", "due_date"]:
                    if (act.get(k) or "") != (exp.get(k) or ""):
                        all_ok = False
                        break
                if not all_ok:
                    break
        if all_ok:
            scores["priority_open_orders_ranking"] = 1.0

    # 4) Validate out/status_report.md
    out_status_path = workspace / "out" / "status_report.md"
    status_text = _read_text(out_status_path)
    if status_text is not None:
        # counts
        open_count = sum(1 for r in orders_rows if (r.get("status") or "").strip() == "open")
        completed_count = sum(1 for r in orders_rows if (r.get("status") or "").strip() == "completed")
        cancelled_count = sum(1 for r in orders_rows if (r.get("status") or "").strip() == "cancelled")
        counts_ok = (
            _contains_count_statement(status_text, "open", open_count) and
            _contains_count_statement(status_text, "completed", completed_count) and
            _contains_count_statement(status_text, "cancelled", cancelled_count)
        )
        if counts_ok:
            scores["status_report_counts_correct"] = 1.0

        # earliest due open orders (three)
        open_with_dates = []
        for r in orders_rows:
            if (r.get("status") or "").strip() != "open":
                continue
            dd = _parse_date(r.get("due_date") or "")
            if dd is None:
                continue
            open_with_dates.append((dd, r))
        open_with_dates.sort(key=lambda x: x[0])
        earliest_three = [r for _d, r in open_with_dates[:3]]
        earliest_ok = True
        for r in earliest_three:
            cid = (r.get("id") or "").strip()
            cname = (r.get("client_name") or "").strip()
            # Look for a line that has both id and client name
            if not _find_line_with_both(status_text, cid, cname):
                earliest_ok = False
                break
        if earliest_ok:
            scores["status_report_earliest_due_listed"] = 1.0

        # top three clients by spend from out/top_clients_by_spend.csv
        if top_loaded:
            top_rows, _ = top_loaded
            top3 = top_rows[:3]
            top_ok = True
            for r in top3:
                name = r.get("client_name") or ""
                total = str(_parse_int(r.get("total_cost_livres") or "0"))
                # Look for line containing both name and total
                if not _find_line_with_both(status_text, name, total):
                    top_ok = False
                    break
            if top_ok:
                scores["status_report_top_clients_consistent"] = 1.0

        # CLI analysis: counts and unknown terms
        if cli_text is not None:
            parsed = _parse_cli_output(cli_text)
            warn_num = parsed["warning_count"]
            err_num = parsed["error_count"]
            # Check counts mentioned
            counts_present = (_contains_count_statement(status_text, "warning", warn_num) and
                              _contains_count_statement(status_text, "error", err_num))
            # Check unknown terms and order IDs enumerated
            unknowns_ok = True
            for w in parsed["warnings"]:
                term = w["term"]
                oid = w["order_id"]
                found = False
                for line in status_text.splitlines():
                    if term in line and (oid in line):
                        found = True
                        break
                if not found:
                    unknowns_ok = False
                    break
            if counts_present and unknowns_ok:
                scores["status_report_cli_analysis"] = 1.0

            # Explicit statement whether any error affected an open order
            error_order_ids = [e["order_id"] for e in parsed["errors"] if e["order_id"] is not None]
            open_ids_set = set([r["id"] for r in expected_bilingual])
            any_error_on_open = any(oid in open_ids_set for oid in error_order_ids)
            # Look for a line that mentions error and open and says yes or no
            statement_ok = False
            for line in status_text.splitlines():
                l = line.lower()
                if "error" in l and "open" in l:
                    if "yes" in l and any_error_on_open:
                        statement_ok = True
                        break
                    if "no" in l and not any_error_on_open:
                        statement_ok = True
                        break
                    if "none" in l and not any_error_on_open:
                        statement_ok = True
                        break
            if statement_ok:
                scores["status_report_error_open_affect_statement"] = 1.0

        # Remediation paragraph proposing how to address unknown terms
        remediation_ok = ("glossary" in status_text.lower()) or ("spelling" in status_text.lower()) or ("confirm" in status_text.lower())
        if remediation_ok:
            scores["status_report_remediation_paragraph"] = 1.0

    # 5) Validate letters
    letters_dir = workspace / "out" / "letters"
    expected_letters = []
    for r in expected_bilingual:
        client = r["client_name"]
        idv = r["id"]
        client_fn = _client_name_to_filename(client)
        fr_file = letters_dir / f"{idv}_{client_fn}_fr.txt"
        en_file = letters_dir / f"{idv}_{client_fn}_en.txt"
        expected_letters.append((fr_file, en_file, r))
    # Check presence
    if len(expected_letters) == 0:
        # No open orders -> trivially satisfied
        scores["letters_files_present"] = 1.0
        scores["letters_headers_correct"] = 1.0
    else:
        all_present = all(fr.exists() and en.exists() for fr, en, _ in expected_letters)
        if all_present:
            scores["letters_files_present"] = 1.0
        # Check headers correctness if present
        headers_all_ok = True
        if all_present:
            for fr, en, r in expected_letters:
                garment_en = r["garment_type_en"]
                fabric_en = r["fabric_en"]
                if not _check_letters_headers(fr, r, "fr", garment_en, fabric_en):
                    headers_all_ok = False
                    break
                if not _check_letters_headers(en, r, "en", garment_en, fabric_en):
                    headers_all_ok = False
                    break
        else:
            headers_all_ok = False
        if headers_all_ok:
            scores["letters_headers_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()