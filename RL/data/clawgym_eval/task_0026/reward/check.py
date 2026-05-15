import csv
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from html import unescape
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            return list(rdr)
    except Exception:
        return None


def _parse_decimal(val: str) -> Optional[Decimal]:
    if val is None:
        return None
    s = str(val).strip()
    # remove $ and % and commas
    s = s.replace("$", "").replace(",", "").strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    if s == "":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        try:
            return Decimal(str(float(s)))
        except Exception:
            return None


def _quantize_2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_promos_html(path: Path) -> Optional[Dict[str, Decimal]]:
    html = _read_text(path)
    if html is None:
        return None
    # Find table with id="promos"
    m = re.search(r'<table[^>]*\bid=["\']promos["\'][^>]*>(.*?)</table>', html, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    tbl = m.group(1)
    # Find all rows in tbody or in table
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, flags=re.DOTALL | re.IGNORECASE)
    promos: Dict[str, Decimal] = {}
    for row in rows:
        # extract cells
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.DOTALL | re.IGNORECASE)
        if len(cells) >= 2:
            vendor_raw = re.sub(r"<.*?>", "", cells[0], flags=re.DOTALL)
            disc_raw = re.sub(r"<.*?>", "", cells[1], flags=re.DOTALL)
            vendor = unescape(vendor_raw).strip()
            disc_s = unescape(disc_raw).strip()
            dval = _parse_decimal(disc_s)
            if vendor and dval is not None:
                promos[vendor] = dval
    return promos if promos else None


def _compute_expected_from_inputs(workspace: Path) -> Optional[dict]:
    rooms_json = _load_json(workspace / "input" / "rooms.json")
    selections = _read_csv_rows(workspace / "input" / "selections.csv")
    promos = _parse_promos_html(workspace / "input" / "vendor_promos.html")
    if rooms_json is None or selections is None or promos is None:
        return None
    # Build room budgets
    room_budgets: Dict[str, Decimal] = {}
    try:
        for r in rooms_json.get("rooms", []):
            name = r["name"]
            budget = Decimal(str(r["budget"]))
            room_budgets[name] = _quantize_2(budget)
    except Exception:
        return None
    # Compute expected normalized rows
    expected_rows: List[dict] = []
    for row in selections:
        try:
            item_id = row["item_id"].strip()
            room = row["room"].strip()
            category = row["category"].strip()
            vendor = row["vendor"].strip()
            unit_price = _parse_decimal(row["unit_price"])
            qty = _parse_decimal(row["qty"])
            if None in (unit_price, qty):
                return None
            discount_percent = promos.get(vendor, Decimal("0"))
            line_before = _quantize_2(unit_price * qty)
            discount_amount = _quantize_2(line_before * (discount_percent / Decimal("100")))
            line_after = _quantize_2(line_before - discount_amount)
            expected_rows.append({
                "item_id": item_id,
                "room": room,
                "category": category,
                "vendor": vendor,
                "qty": int(qty),
                "unit_price": _quantize_2(unit_price),
                "discount_percent": discount_percent,
                "line_total_before_discount": line_before,
                "discount_amount": discount_amount,
                "line_total_after_discount": line_after,
            })
        except Exception:
            return None
    # Aggregate per room
    per_room: Dict[str, dict] = {}
    for room, budget in room_budgets.items():
        per_room[room] = {
            "room": room,
            "budget": _quantize_2(budget),
            "pre_discount_total": Decimal("0.00"),
            "total_discounts": Decimal("0.00"),
            "post_discount_total": Decimal("0.00"),
            "remaining": Decimal("0.00"),
        }
    for r in expected_rows:
        rm = r["room"]
        if rm not in per_room:
            per_room[rm] = {
                "room": rm,
                "budget": Decimal("0.00"),
                "pre_discount_total": Decimal("0.00"),
                "total_discounts": Decimal("0.00"),
                "post_discount_total": Decimal("0.00"),
                "remaining": Decimal("0.00"),
            }
        per_room[rm]["pre_discount_total"] += r["line_total_before_discount"]
        per_room[rm]["total_discounts"] += r["discount_amount"]
        per_room[rm]["post_discount_total"] += r["line_total_after_discount"]
    for rm, agg in per_room.items():
        agg["pre_discount_total"] = _quantize_2(agg["pre_discount_total"])
        agg["total_discounts"] = _quantize_2(agg["total_discounts"])
        agg["post_discount_total"] = _quantize_2(agg["post_discount_total"])
        agg["remaining"] = _quantize_2(agg["budget"] - agg["post_discount_total"])
    # overall
    overall = {
        "budget": _quantize_2(sum((v["budget"] for v in per_room.values()), Decimal("0.00"))),
        "pre_discount_total": _quantize_2(sum((v["pre_discount_total"] for v in per_room.values()), Decimal("0.00"))),
        "total_discounts": _quantize_2(sum((v["total_discounts"] for v in per_room.values()), Decimal("0.00"))),
        "post_discount_total": _quantize_2(sum((v["post_discount_total"] for v in per_room.values()), Decimal("0.00"))),
    }
    overall["remaining"] = _quantize_2(overall["budget"] - overall["post_discount_total"])
    # savings by vendor
    savings_by_vendor: Dict[str, Decimal] = {}
    for r in expected_rows:
        vendor = r["vendor"]
        savings_by_vendor[vendor] = savings_by_vendor.get(vendor, Decimal("0.00")) + r["discount_amount"]
    top_vendors = sorted(savings_by_vendor.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    result = {
        "expected_rows": expected_rows,
        "per_room": per_room,
        "overall": overall,
        "savings_by_vendor": savings_by_vendor,
        "top_vendors": top_vendors[:2],
    }
    return result


def _parse_normalized_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    rows = _read_csv_rows(path)
    if rows is None:
        return None
    # reconstruct header order as in file
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            header = next(csv.reader(f))
    except Exception:
        header = list(rows[0].keys()) if rows else []
    return header, rows


def _has_two_decimals_str(s: str) -> bool:
    s = s.strip()
    s = s.replace(",", "")
    if s.startswith("$"):
        s = s[1:]
    m = re.match(r"^-?\d+(?:\.\d{2})$", s)
    return m is not None


def _numbers_in_text(text: str) -> List[Decimal]:
    nums: List[Decimal] = []
    # capture optional $ and commas
    for m in re.finditer(r'(?<!\w)\$?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|(?<!\w)\$?-?\d+(?:\.\d+)?', text):
        token = m.group(0)
        token = token.replace("$", "").replace(",", "")
        try:
            d = Decimal(token)
            nums.append(d)
        except Exception:
            continue
    return nums


def _contains_number(text: str, target: Decimal, tol: Decimal = Decimal("0.01")) -> bool:
    nums = _numbers_in_text(text)
    for n in nums:
        if abs(n - target) <= tol:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "normalized_items_csv_structure": 0.0,
        "normalized_items_row_count_and_order": 0.0,
        "normalized_items_discounts_and_calculations": 0.0,
        "budget_status_json_structure": 0.0,
        "budget_status_json_values_and_rounding": 0.0,
        "cross_file_consistency_json_vs_csv": 0.0,
        "status_report_room_coverage_and_word_count": 0.0,
        "status_report_numbers_match": 0.0,
        "client_email_basic_requirements": 0.0,
        "client_email_numbers_and_vendors": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    # Check normalized_items.csv
    norm_path = workspace / "output" / "normalized_items.csv"
    if norm_path.exists():
        parsed = _parse_normalized_csv(norm_path)
        if parsed is not None:
            header, rows = parsed
            expected_header = [
                "item_id",
                "room",
                "category",
                "vendor",
                "qty",
                "unit_price",
                "discount_percent",
                "line_total_before_discount",
                "discount_amount",
                "line_total_after_discount",
            ]
            if header == expected_header:
                scores["normalized_items_csv_structure"] = 1.0
            # Row count and order check
            if expected is not None and rows is not None:
                exp_rows = expected["expected_rows"]
                if len(rows) == len(exp_rows):
                    order_ok = True
                    for i, (out_row, exp_row) in enumerate(zip(rows, exp_rows)):
                        if (out_row.get("item_id") or "").strip() != exp_row["item_id"]:
                            order_ok = False
                            break
                    if order_ok:
                        scores["normalized_items_row_count_and_order"] = 1.0
            # Discounts and calculations validation
            if expected is not None and rows is not None and len(rows) == len(expected["expected_rows"]):
                calc_ok = True
                for out_row, exp_row in zip(rows, expected["expected_rows"]):
                    # Check basic fields
                    if (out_row.get("room") or "").strip() != exp_row["room"]:
                        calc_ok = False
                        break
                    if (out_row.get("category") or "").strip() != exp_row["category"]:
                        calc_ok = False
                        break
                    if (out_row.get("vendor") or "").strip() != exp_row["vendor"]:
                        calc_ok = False
                        break
                    # qty equality
                    qty_val = _parse_decimal(out_row.get("qty", ""))
                    if qty_val is None or int(qty_val) != int(exp_row["qty"]):
                        calc_ok = False
                        break
                    # unit price equality (allow numeric equivalence)
                    up_val = _parse_decimal(out_row.get("unit_price", ""))
                    if up_val is None or _quantize_2(up_val) != _quantize_2(exp_row["unit_price"]):
                        calc_ok = False
                        break
                    # discount percent equality (allow % sign and decimals)
                    dp_val = _parse_decimal(out_row.get("discount_percent", ""))
                    if dp_val is None or _quantize_2(dp_val) != _quantize_2(exp_row["discount_percent"]):
                        calc_ok = False
                        break
                    # monetary fields must have exactly two decimals and equal
                    for key in ["line_total_before_discount", "discount_amount", "line_total_after_discount"]:
                        sval = out_row.get(key, "")
                        if not isinstance(sval, str) or not _has_two_decimals_str(sval):
                            calc_ok = False
                            break
                        mval = _parse_decimal(sval)
                        if mval is None or _quantize_2(mval) != _quantize_2(exp_row[key]):
                            calc_ok = False
                            break
                    if not calc_ok:
                        break
                if calc_ok:
                    scores["normalized_items_discounts_and_calculations"] = 1.0

    # budget_status.json checks
    budget_path = workspace / "output" / "budget_status.json"
    budget_obj = _load_json(budget_path) if budget_path.exists() else None
    rooms_list: List[dict] = []
    overall_obj: Optional[dict] = None
    if isinstance(budget_obj, dict):
        # preferred: has "rooms" list and "overall"
        if "rooms" in budget_obj and isinstance(budget_obj["rooms"], list):
            rooms_list = budget_obj["rooms"]
        # attempt to extract overall
        if "overall" in budget_obj and isinstance(budget_obj["overall"], dict):
            overall_obj = budget_obj["overall"]
        # If rooms not present but there are other objects with "room" field, collect them
        if not rooms_list:
            collected = []
            for v in budget_obj.values():
                if isinstance(v, dict) and set(["room", "budget", "pre_discount_total", "total_discounts", "post_discount_total", "remaining"]).issubset(v.keys()):
                    collected.append(v)
            if collected:
                rooms_list = collected
    # Structure check: required fields
    structure_ok = True
    if not rooms_list or overall_obj is None:
        structure_ok = False
    else:
        req_fields = ["room", "budget", "pre_discount_total", "total_discounts", "post_discount_total", "remaining"]
        for r in rooms_list:
            if not all(k in r for k in req_fields):
                structure_ok = False
                break
            # numeric types
            for k in req_fields:
                if k == "room":
                    continue
                if not isinstance(r[k], (int, float)):
                    structure_ok = False
                    break
            if not structure_ok:
                break
        for k in ["budget", "pre_discount_total", "total_discounts", "post_discount_total", "remaining"]:
            if k not in overall_obj or not isinstance(overall_obj[k], (int, float)):
                structure_ok = False
                break
    if structure_ok:
        scores["budget_status_json_structure"] = 1.0

    # Values and rounding check for budget_status.json
    if expected is not None and structure_ok:
        values_ok = True
        # Map rooms by name
        room_map = {r["room"]: r for r in rooms_list if isinstance(r, dict) and "room" in r}
        # Each input room must be present and values match rounded to 2 decimals
        for room_name, exp in expected["per_room"].items():
            if room_name not in room_map:
                values_ok = False
                break
            got = room_map[room_name]
            for k in ["budget", "pre_discount_total", "total_discounts", "post_discount_total", "remaining"]:
                try:
                    gval = Decimal(str(got[k]))
                except Exception:
                    values_ok = False
                    break
                if _quantize_2(gval) != _quantize_2(Decimal(str(exp[k]))):
                    values_ok = False
                    break
            if not values_ok:
                break
        # overall values
        if values_ok:
            for k in ["budget", "pre_discount_total", "total_discounts", "post_discount_total", "remaining"]:
                try:
                    gval = Decimal(str(overall_obj[k]))
                except Exception:
                    values_ok = False
                    break
                if _quantize_2(gval) != _quantize_2(Decimal(str(expected["overall"][k]))):
                    values_ok = False
                    break
        if values_ok:
            scores["budget_status_json_values_and_rounding"] = 1.0

    # Cross-file consistency: sums in JSON vs CSV
    if scores["normalized_items_discounts_and_calculations"] == 1.0 and structure_ok:
        # aggregate from normalized CSV
        parsed2 = _parse_normalized_csv(norm_path)
        if parsed2 is not None:
            _, rows2 = parsed2
        else:
            rows2 = None
        agg_by_room: Dict[str, Dict[str, Decimal]] = {}
        try:
            if rows2 is None:
                raise ValueError("no rows")
            for row in rows2:
                rm = row["room"].strip()
                pre = _parse_decimal(row["line_total_before_discount"])
                disc = _parse_decimal(row["discount_amount"])
                post = _parse_decimal(row["line_total_after_discount"])
                if None in (pre, disc, post):
                    raise ValueError("malformed numeric")
                s = agg_by_room.setdefault(rm, {"pre": Decimal("0.00"), "disc": Decimal("0.00"), "post": Decimal("0.00")})
                s["pre"] += pre
                s["disc"] += disc
                s["post"] += post
            for rm in agg_by_room:
                agg_by_room[rm]["pre"] = _quantize_2(agg_by_room[rm]["pre"])
                agg_by_room[rm]["disc"] = _quantize_2(agg_by_room[rm]["disc"])
                agg_by_room[rm]["post"] = _quantize_2(agg_by_room[rm]["post"])
        except Exception:
            agg_by_room = {}
        consistency_ok = True
        if agg_by_room and isinstance(budget_obj, dict):
            # compare with JSON room entries
            room_map = {r["room"]: r for r in rooms_list if isinstance(r, dict) and "room" in r}
            for rm, sums in agg_by_room.items():
                if rm not in room_map:
                    consistency_ok = False
                    break
                rj = room_map[rm]
                if _quantize_2(Decimal(str(rj["pre_discount_total"]))) != sums["pre"]:
                    consistency_ok = False
                    break
                if _quantize_2(Decimal(str(rj["total_discounts"]))) != sums["disc"]:
                    consistency_ok = False
                    break
                if _quantize_2(Decimal(str(rj["post_discount_total"]))) != sums["post"]:
                    consistency_ok = False
                    break
            # overall consistency
            if consistency_ok and overall_obj is not None:
                total_pre = _quantize_2(sum((v["pre"] for v in agg_by_room.values()), Decimal("0.00")))
                total_disc = _quantize_2(sum((v["disc"] for v in agg_by_room.values()), Decimal("0.00")))
                total_post = _quantize_2(sum((v["post"] for v in agg_by_room.values()), Decimal("0.00")))
                if _quantize_2(Decimal(str(overall_obj["pre_discount_total"]))) != total_pre:
                    consistency_ok = False
                if _quantize_2(Decimal(str(overall_obj["total_discounts"]))) != total_disc:
                    consistency_ok = False
                if _quantize_2(Decimal(str(overall_obj["post_discount_total"]))) != total_post:
                    consistency_ok = False
        else:
            consistency_ok = False
        if consistency_ok:
            scores["cross_file_consistency_json_vs_csv"] = 1.0

    # status_report.md checks
    status_path = workspace / "output" / "status_report.md"
    status_text = _read_text(status_path) if status_path.exists() else None
    if status_text is not None and expected is not None and structure_ok:
        # word count 200-400
        words = re.findall(r"\b\w+\b", status_text)
        word_count_ok = 200 <= len(words) <= 400
        # rooms listed (names present)
        rooms_present = all(rn in status_text for rn in expected["per_room"].keys())
        # If any room over budget, check "over budget" phrase present
        any_over = any(v["remaining"] < Decimal("0.00") for v in expected["per_room"].values())
        over_phrase_ok = True
        if any_over:
            over_phrase_ok = re.search(r"over budget", status_text, flags=re.IGNORECASE) is not None
        if word_count_ok and rooms_present and over_phrase_ok:
            scores["status_report_room_coverage_and_word_count"] = 1.0
        # numbers must match computed values: for each room include budget, pre, discounts, post, remaining
        nums_ok = True
        for room_name, vals in expected["per_room"].items():
            for k in ["budget", "pre_discount_total", "total_discounts", "post_discount_total", "remaining"]:
                if not _contains_number(status_text, Decimal(str(vals[k]))):
                    nums_ok = False
                    break
            if not nums_ok:
                break
        # overall totals and total savings
        if nums_ok:
            for k in ["pre_discount_total", "total_discounts", "post_discount_total", "remaining", "budget"]:
                if not _contains_number(status_text, Decimal(str(expected["overall"][k]))):
                    nums_ok = False
                    break
        if nums_ok:
            scores["status_report_numbers_match"] = 1.0

    # client_email.txt checks
    email_path = workspace / "output" / "client_email.txt"
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None and expected is not None and structure_ok:
        # <= 200 words
        words = re.findall(r"\b\w+\b", email_text)
        word_count_ok = len(words) <= 200
        # greeting to Avery: presence of "Avery" near beginning (first 50 words)
        first_part = " ".join(words[:50])
        greeting_ok = "Avery" in first_part
        # if any room over budget -> list them; else note none are over budget
        any_over = any(v["remaining"] < Decimal("0.00") for v in expected["per_room"].values())
        over_ok = True
        if any_over:
            over_ok = re.search(r"over budget", email_text, flags=re.IGNORECASE) is not None
        else:
            over_ok = re.search(r"(no|none|not)\s+(?:rooms\s+)?(?:are\s+)?over budget", email_text, flags=re.IGNORECASE) is not None
        if word_count_ok and greeting_ok and over_ok:
            scores["client_email_basic_requirements"] = 1.0
        # numbers and top 2 vendors by savings
        nums_ok = True
        # overall post-discount spend and total savings
        if not _contains_number(email_text, Decimal(str(expected["overall"]["post_discount_total"]))):
            nums_ok = False
        if nums_ok and not _contains_number(email_text, Decimal(str(expected["overall"]["total_discounts"]))):
            nums_ok = False
        # top 2 vendors by total savings with amounts
        if nums_ok:
            top2 = expected["top_vendors"]
            if len(top2) >= 2:
                for vendor, amt in top2:
                    if vendor not in email_text:
                        nums_ok = False
                        break
                    if not _contains_number(email_text, _quantize_2(amt)):
                        nums_ok = False
                        break
            else:
                nums_ok = False
        if nums_ok:
            scores["client_email_numbers_and_vendors"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()