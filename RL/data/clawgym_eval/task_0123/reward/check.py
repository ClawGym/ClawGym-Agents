import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Optional, Any


def _posix(p: Path) -> str:
    return p.as_posix()


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        # Validate that all rows have same fields as header
        if reader.fieldnames is None:
            return None
        for r in rows:
            if set(r.keys()) != set(reader.fieldnames):
                return None
        return rows
    except Exception:
        return None


def _count_csv_rows(p: Path) -> Optional[int]:
    rows = _safe_read_csv_dicts(p)
    if rows is None:
        return None
    return len(rows)


def _list_input_files_with_row_counts(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    results: List[Dict[str, Any]] = []
    for path in sorted(input_dir.rglob("*")):
        if path.is_file():
            rel = _posix(path.relative_to(workspace))
            if path.suffix.lower() == ".csv":
                rc = _count_csv_rows(path)
                if rc is None:
                    return None
                results.append({"file_path": rel, "row_count": rc})
            else:
                results.append({"file_path": rel, "row_count": None})
    return results


def _load_album_tracks(workspace: Path) -> Optional[Dict[str, Any]]:
    catalog_path = workspace / "input" / "catalog" / "most_successful_album.json"
    catalog = _safe_load_json(catalog_path)
    if not isinstance(catalog, dict):
        return None
    album_title = catalog.get("album_title")
    tracks_field = catalog.get("tracks")
    if not isinstance(album_title, str) or not isinstance(tracks_field, list):
        return None
    titles = []
    for t in tracks_field:
        if isinstance(t, dict) and isinstance(t.get("title"), str):
            titles.append(t["title"])
        else:
            return None
    return {"album_title": album_title, "titles": set(titles)}


def _aggregate_revenue(workspace: Path, titles: set) -> Optional[List[Dict[str, Any]]]:
    streaming_path = workspace / "input" / "statements" / "streaming_royalties_q1_2025.csv"
    download_path = workspace / "input" / "statements" / "download_sales_q1_2025.csv"
    streaming_rows = _safe_read_csv_dicts(streaming_path)
    download_rows = _safe_read_csv_dicts(download_path)
    if streaming_rows is None or download_rows is None:
        return None

    agg: Dict[tuple, Dict[str, Any]] = {}

    def add_rows(rows: List[Dict[str, str]], source: str) -> bool:
        for r in rows:
            tt = r.get("track_title")
            if tt not in titles:
                continue
            try:
                units = int(str(r.get("units", "")).strip())
                revenue = float(str(r.get("revenue_usd", "")).strip())
            except Exception:
                return False
            key = (tt, source)
            if key not in agg:
                agg[key] = {"track_title": tt, "source": source, "units_total": 0, "revenue_usd_total": 0.0}
            agg[key]["units_total"] += units
            agg[key]["revenue_usd_total"] += revenue
        return True

    ok1 = add_rows(streaming_rows, "streaming")
    ok2 = add_rows(download_rows, "download")
    if not (ok1 and ok2):
        return None

    rows_list = list(agg.values())
    rows_list.sort(key=lambda d: (d["track_title"], d["source"]))
    return rows_list


def _parse_royalty_rate(md_text: str) -> Optional[float]:
    m = re.search(r"Royalty\s*Rate\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", md_text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        pct = float(m.group(1))
        return pct / 100.0
    except Exception:
        return None


def _sum_recoupable_costs(workspace: Path) -> Optional[float]:
    p = workspace / "input" / "expenses" / "q1_2025_recoupable_costs.csv"
    rows = _safe_read_csv_dicts(p)
    if rows is None:
        return None
    total = 0.0
    for r in rows:
        flag = str(r.get("recoupable", "")).strip().lower()
        amt_str = str(r.get("amount_usd", "")).strip()
        try:
            amt = float(amt_str)
        except Exception:
            return None
        if flag == "yes":
            total += amt
        elif flag == "no":
            continue
        else:
            return None
    return total


def _load_agreement_text(workspace: Path) -> Optional[str]:
    p = workspace / "input" / "contracts" / "session_musician_agreement.md"
    return _safe_read_text(p)


def _read_album_revenue_output(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    p = workspace / "outputs" / "album_revenue_q1_2025.csv"
    rows = _safe_read_csv_dicts(p)
    if rows is None:
        return None
    return rows


def _normalize_revenue_rows(rows: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    norm = []
    expected_cols = ["track_title", "source", "units_total", "revenue_usd_total"]
    for r in rows:
        # Enforce exact set of columns, casting types
        if set(r.keys()) != set(expected_cols):
            return None
        try:
            tt = r["track_title"]
            src = r["source"]
            units = int(str(r["units_total"]).strip())
            rev = float(str(r["revenue_usd_total"]).strip())
        except Exception:
            return None
        if not isinstance(tt, str) or not isinstance(src, str):
            return None
        norm.append({"track_title": tt, "source": src, "units_total": units, "revenue_usd_total": rev})
    return norm


def _float_close(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def _load_net_summary(workspace: Path) -> Optional[Dict[str, Any]]:
    p = workspace / "outputs" / "summary" / "net_royalty_q1_2025.json"
    data = _safe_load_json(p)
    if not isinstance(data, dict):
        return None
    return data


def _find_subject_line(lines: List[str]) -> Optional[str]:
    for ln in lines:
        if ln.strip() == "":
            continue
        return ln
    return None


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "file_inventory_correct": 0.0,
        "album_revenue_csv_structure": 0.0,
        "album_revenue_values_correct": 0.0,
        "net_royalty_json_fields_correct": 0.0,
        "net_royalty_values_correct": 0.0,
        "net_royalty_data_sources_included": 0.0,
        "email_subject_prefix": 0.0,
        "email_mentions_album_and_credit": 0.0,
        "email_includes_royalty_amount_usd": 0.0,
        "email_final_attachment_lines": 0.0,
        "email_word_limit": 0.0,
    }

    # 1) File inventory check
    expected_inventory = _list_input_files_with_row_counts(workspace)
    inv_path = workspace / "outputs" / "file_inventory.json"
    inv_data = _safe_load_json(inv_path) if inv_path.exists() else None
    if expected_inventory is not None and inv_data is not None and isinstance(inv_data, list):
        try:
            inv_norm = []
            for item in inv_data:
                if not isinstance(item, dict):
                    inv_norm = None
                    break
                if "file_path" not in item or "row_count" not in item:
                    inv_norm = None
                    break
                fp = item.get("file_path")
                rc = item.get("row_count")
                if not isinstance(fp, str):
                    inv_norm = None
                    break
                if rc is not None and not isinstance(rc, int):
                    inv_norm = None
                    break
                inv_norm.append({"file_path": fp, "row_count": rc})
            if inv_norm is not None:
                inv_norm_sorted = sorted(inv_norm, key=lambda x: x["file_path"])
                exp_sorted = sorted(expected_inventory, key=lambda x: x["file_path"])
                if inv_norm_sorted == exp_sorted:
                    scores["file_inventory_correct"] = 1.0
        except Exception:
            pass

    # 2) Aggregate album revenues
    album_info = _load_album_tracks(workspace)
    expected_agg: Optional[List[Dict[str, Any]]] = None
    if album_info is not None:
        expected_agg = _aggregate_revenue(workspace, album_info["titles"])

    # Structure check for outputs/album_revenue_q1_2025.csv
    album_rev_file = workspace / "outputs" / "album_revenue_q1_2025.csv"
    out_rows_raw = _read_album_revenue_output(workspace)
    out_rows_norm = None
    header_ok = False
    # Check header order deterministically
    if album_rev_file.exists():
        try:
            with album_rev_file.open("r", encoding="utf-8") as f:
                hdr_line = f.readline()
            hdr = [h.strip() for h in hdr_line.strip().split(",")] if hdr_line else []
            header_ok = hdr == ["track_title", "source", "units_total", "revenue_usd_total"]
        except Exception:
            header_ok = False
    # Normalize values if possible
    if header_ok and out_rows_raw is not None:
        out_rows_norm = _normalize_revenue_rows(out_rows_raw)
    if header_ok:
        scores["album_revenue_csv_structure"] = 1.0

    # Values check
    if expected_agg is not None and out_rows_norm is not None:
        def rows_to_set(rows: List[Dict[str, Any]]) -> set:
            s = set()
            for r in rows:
                s.add((r["track_title"], r["source"], int(r["units_total"]), round(float(r["revenue_usd_total"]), 2)))
            return s

        if rows_to_set(out_rows_norm) == rows_to_set(expected_agg):
            scores["album_revenue_values_correct"] = 1.0

    # 3) Net receipts and royalty JSON
    gross_receipts = None
    recoupable_sum = None
    royalty_rate = None

    if expected_agg is not None:
        gross_receipts = sum(r["revenue_usd_total"] for r in expected_agg)
    elif album_info is not None:
        exp2 = _aggregate_revenue(workspace, album_info["titles"])
        if exp2 is not None:
            gross_receipts = sum(r["revenue_usd_total"] for r in exp2)

    recoupable_sum = _sum_recoupable_costs(workspace)
    agreement_text = _load_agreement_text(workspace)
    if agreement_text is not None:
        royalty_rate = _parse_royalty_rate(agreement_text)

    net_receipts = None
    musician_due = None
    if gross_receipts is not None and recoupable_sum is not None and royalty_rate is not None:
        net_receipts = max(0.0, gross_receipts - recoupable_sum)
        musician_due = net_receipts * royalty_rate

    net_json = _load_net_summary(workspace)
    # Fields presence/format check
    if isinstance(net_json, dict):
        required_keys = {
            "album_title",
            "period",
            "gross_album_receipts_usd",
            "recoupable_costs_usd",
            "net_receipts_usd",
            "musician_share_rate",
            "musician_royalty_due_usd",
            "data_sources",
        }
        if required_keys.issubset(set(net_json.keys())) and isinstance(net_json.get("data_sources"), list):
            types_ok = True
            types_ok &= isinstance(net_json.get("album_title"), str)
            types_ok &= isinstance(net_json.get("period"), str)
            try:
                float(net_json.get("gross_album_receipts_usd"))
                float(net_json.get("recoupable_costs_usd"))
                float(net_json.get("net_receipts_usd"))
                float(net_json.get("musician_share_rate"))
                float(net_json.get("musician_royalty_due_usd"))
            except Exception:
                types_ok = False
            if types_ok and net_json.get("period") == "2025 Q1":
                scores["net_royalty_json_fields_correct"] = 1.0

    # Values correctness check
    if (
        isinstance(net_json, dict)
        and gross_receipts is not None
        and recoupable_sum is not None
        and net_receipts is not None
        and royalty_rate is not None
        and musician_due is not None
        and album_info is not None
    ):
        try:
            album_title_ok = net_json.get("album_title") == album_info["album_title"]
            gross_ok = _float_close(float(net_json.get("gross_album_receipts_usd")), float(gross_receipts))
            recoup_ok = _float_close(float(net_json.get("recoupable_costs_usd")), float(recoupable_sum))
            net_ok = _float_close(float(net_json.get("net_receipts_usd")), float(net_receipts))
            rate_ok = _float_close(float(net_json.get("musician_share_rate")), float(royalty_rate), tol=1e-6)
            due_ok = _float_close(float(net_json.get("musician_royalty_due_usd")), float(musician_due))
            if album_title_ok and gross_ok and recoup_ok and net_ok and rate_ok and due_ok:
                scores["net_royalty_values_correct"] = 1.0
        except Exception:
            pass

    # Data sources inclusion check
    if isinstance(net_json, dict) and isinstance(net_json.get("data_sources"), list):
        ds = set([str(x) for x in net_json.get("data_sources")])
        required_sources = {
            "input/catalog/most_successful_album.json",
            "input/statements/streaming_royalties_q1_2025.csv",
            "input/statements/download_sales_q1_2025.csv",
            "input/expenses/q1_2025_recoupable_costs.csv",
            "input/contracts/session_musician_agreement.md",
        }
        if required_sources.issubset(ds):
            scores["net_royalty_data_sources_included"] = 1.0

    # 4) Email checks
    email_path = workspace / "outputs" / "email" / "session_musician_note.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        # Subject prefix check
        first_line = _find_subject_line(lines)
        if first_line is not None:
            subj_match = re.match(r"^\s*Subject\s*:\s*Q1 2025 Royalty –", first_line)
            if subj_match:
                scores["email_subject_prefix"] = 1.0

        # Word limit
        wc = _word_count(email_text)
        if wc <= 180:
            scores["email_word_limit"] = 1.0

        # Mentions album and credit
        body_lines = []
        saw_subject = False
        for ln in lines:
            if not saw_subject and ln.strip().lower().startswith("subject:"):
                saw_subject = True
                continue
            if saw_subject:
                body_lines.append(ln)
        body_text = "\n".join(body_lines) if body_lines else email_text
        body_low = body_text.lower()
        album_mentioned = "skyline echoes" in body_low
        credit_mentioned = ("credit" in body_low and "album" in body_low)
        if album_mentioned and credit_mentioned:
            scores["email_mentions_album_and_credit"] = 1.0

        # Includes royalty amount in USD
        amount_ok = False
        if isinstance(musician_due, (int, float)):
            formatted_plain = f"{musician_due:.2f}"
            formatted_group = f"{musician_due:,.2f}"
            patterns = [
                rf"(?i)\bUSD\s*{re.escape(formatted_plain)}\b",
                rf"(?i)\bUSD\s*{re.escape(formatted_group)}\b",
                rf"\$\s*{re.escape(formatted_plain)}\b",
                rf"\$\s*{re.escape(formatted_group)}\b",
            ]
            for pat in patterns:
                if re.search(pat, email_text):
                    amount_ok = True
                    break
        if amount_ok:
            scores["email_includes_royalty_amount_usd"] = 1.0

        # Final attachment lines
        non_empty_lines = [ln for ln in [l.rstrip("\n\r") for l in lines] if ln.strip() != ""]
        if len(non_empty_lines) >= 2:
            last_two = non_empty_lines[-2:]
            expected1 = "outputs/album_revenue_q1_2025.csv"
            expected2 = "outputs/summary/net_royalty_q1_2025.json"
            if (last_two[0].strip() == expected1) and (last_two[1].strip() == expected2):
                scores["email_final_attachment_lines"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()