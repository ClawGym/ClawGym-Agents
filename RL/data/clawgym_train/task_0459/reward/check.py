import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _compute_nonempty_counts(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not rows:
        return counts
    fields = list(rows[0].keys())
    for field in fields:
        c = 0
        for r in rows:
            v = r.get(field, "")
            if v is None:
                v = ""
            if str(v).strip() != "":
                c += 1
        counts[field] = c
    return counts


def _safe_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, (int, float)):
            return int(s)
        s_str = str(s).strip()
        if s_str == "":
            return None
        if re.fullmatch(r"-?\d+(\.0+)?", s_str):
            return int(float(s_str))
        return int(s_str)
    except Exception:
        return None


def _contains_url(s: str) -> bool:
    s_l = s.lower()
    return ("http://" in s_l) or ("https://" in s_l) or ("www." in s_l) or ("://" in s_l)


def _extract_all_strings(obj: Any) -> List[str]:
    strs: List[str] = []
    if isinstance(obj, str):
        strs.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            strs.extend(_extract_all_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            strs.extend(_extract_all_strings(v))
    return strs


def _list_input_files(workspace: Path) -> List[str]:
    input_dir = workspace / "input"
    files: List[str] = []
    if not input_dir.exists():
        return files
    for p in input_dir.rglob("*"):
        if p.is_file():
            try:
                rel = p.relative_to(workspace).as_posix()
            except Exception:
                rel = p.as_posix()
            files.append(rel)
    files.sort()
    return files


def _read_csv_headers(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames or []
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "data_inventory_has_required_columns": 0.0,
        "data_inventory_online_feature_complete": 0.0,
        "data_inventory_online_notes_included": 0.0,
        "data_inventory_pos_fields_presence": 0.0,
        "data_inventory_pos_frequency_correct": 0.0,
        "risk_register_has_required_columns": 0.0,
        "risk_register_sorted_and_min_rows": 0.0,
        "risk_register_categories_covered": 0.0,
        "risk_register_score_calculation_correct": 0.0,
        "risk_register_impact_policy_gap_consistent": 0.0,
        "risk_register_policy_gap_expected_categories": 0.0,
        "risk_register_citations_crossref": 0.0,
        "risk_register_controls_present": 0.0,
        "compliance_sources_valid_structure": 0.0,
        "compliance_sources_official_bodies_included": 0.0,
        "compliance_sources_no_urls": 0.0,
        "summary_exists": 0.0,
        "summary_lists_input_tree": 0.0,
        "summary_mentions_top5_risks": 0.0,
        "summary_describes_method_and_formula": 0.0,
        "summary_mentions_search_and_bodies": 0.0,
    }

    # Paths
    data_inventory_path = workspace / "output" / "data_inventory.csv"
    risk_register_path = workspace / "output" / "risk_register.csv"
    compliance_sources_path = workspace / "output" / "compliance_sources.json"
    summary_path = workspace / "output" / "summary.md"

    pos_csv_path = workspace / "input" / "orders" / "sample_pos_export.csv"
    schema_json_path = workspace / "input" / "proposed_feature" / "data_schema.json"
    policy_txt_path = workspace / "input" / "current_policies" / "privacy_policy.txt"

    # Load inputs
    pos_rows = _load_csv(pos_csv_path) or []
    pos_counts = _compute_nonempty_counts(pos_rows)
    schema_json = _load_json(schema_json_path)
    policy_text = _read_text(policy_txt_path) or ""

    # Load outputs
    data_inventory_rows = _load_csv(data_inventory_path)
    risk_register_rows = _load_csv(risk_register_path)
    compliance_sources = _load_json(compliance_sources_path)
    summary_text = _read_text(summary_path) or ""

    # 1) data_inventory.csv structure
    required_inventory_cols = {"source", "field_name", "category", "pii", "frequency_estimate", "notes"}
    if data_inventory_rows is not None:
        headers = _read_csv_headers(data_inventory_path) or []
        if required_inventory_cols.issubset(set(headers)):
            # Also check pii values are 'true'/'false' strings for all rows
            pii_ok = True
            src_ok = True
            for r in data_inventory_rows:
                pii_val = str(r.get("pii", "")).strip().lower()
                if pii_val not in {"true", "false"}:
                    pii_ok = False
                    break
                src_val = str(r.get("source", "")).strip()
                if src_val not in {"pos_export", "online_feature"}:
                    src_ok = False
                    break
            if pii_ok and src_ok:
                scores["data_inventory_has_required_columns"] = 1.0

    # 2) data_inventory online_feature completeness and notes
    online_complete_ok = False
    online_notes_ok = False
    if (data_inventory_rows is not None) and isinstance(schema_json, dict):
        # Collect expected schema fields
        schema_fields: List[Tuple[str, str, bool, Optional[str]]] = []
        cps = schema_json.get("collection_points") or []
        if isinstance(cps, list):
            for cp in cps:
                fields = (cp or {}).get("fields") or []
                if isinstance(fields, list):
                    for f in fields:
                        field_name = (f or {}).get("field")
                        category = (f or {}).get("category")
                        pii = (f or {}).get("pii")
                        notes = (f or {}).get("notes")
                        if field_name is not None and category is not None and isinstance(pii, bool):
                            schema_fields.append((str(field_name), str(category), pii, notes if isinstance(notes, str) else None))
        # Filter inventory for online_feature
        online_rows = [r for r in data_inventory_rows if str(r.get("source", "")).strip() == "online_feature"]
        # Build a lookup for online rows by field_name
        online_by_field = {}
        for r in online_rows:
            online_by_field.setdefault(str(r.get("field_name", "")).strip(), []).append(r)
        # Check each schema field exists exactly once with matching category, pii, frequency_estimate=N/A
        all_match = True
        notes_ok = True
        for (fname, cat, pii_bool, notes) in schema_fields:
            rows_for_field = online_by_field.get(fname, [])
            if len(rows_for_field) < 1:
                all_match = False
                break
            # Find a matching row with correct category and pii and freq N/A
            match_found = False
            for r in rows_for_field:
                r_cat = str(r.get("category", "")).strip()
                r_pii = str(r.get("pii", "")).strip().lower()
                r_freq = str(r.get("frequency_estimate", "")).strip()
                if (r_cat == cat) and (r_pii == ("true" if pii_bool else "false")) and (r_freq == "N/A"):
                    match_found = True
                    # if schema has notes, inventory should have non-empty notes
                    notes_cell = str(r.get("notes", "")).strip()
                    if notes is not None and notes_cell == "":
                        notes_ok = False
                    break
            if not match_found:
                all_match = False
                break
        # Also check that count of online rows equals number of schema fields
        if all_match and len(online_rows) == len(schema_fields) and len(schema_fields) > 0:
            online_complete_ok = True
        online_notes_ok = notes_ok and len(schema_fields) > 0
    scores["data_inventory_online_feature_complete"] = 1.0 if online_complete_ok else 0.0
    scores["data_inventory_online_notes_included"] = 1.0 if online_notes_ok else 0.0

    # 3) data_inventory POS fields presence and frequency correctness
    pos_presence_ok = False
    pos_freq_ok = False
    if data_inventory_rows is not None and pos_counts:
        target_pos_fields = ["customer_name", "email", "phone", "billing_address", "city", "state", "zip", "card_last4"]
        pos_rows = [r for r in data_inventory_rows if str(r.get("source", "")).strip() == "pos_export"]
        pos_fields_present = {}
        pii_all_true = True
        for r in pos_rows:
            fname = str(r.get("field_name", "")).strip()
            if fname in target_pos_fields:
                pos_fields_present[fname] = r
                if str(r.get("pii", "")).strip().lower() != "true":
                    pii_all_true = False
        if len(pos_fields_present) >= 5 and pii_all_true:
            pos_presence_ok = True

        # Frequency correctness for those present and in pos_counts
        freq_mismatch = False
        checked = 0
        for fname, r in pos_fields_present.items():
            if fname in pos_counts:
                inv_freq = _safe_int(r.get("frequency_estimate"))
                if inv_freq is None or inv_freq != pos_counts.get(fname, -1):
                    freq_mismatch = True
                    break
                checked += 1
        if checked >= 3 and not freq_mismatch:
            pos_freq_ok = True

    scores["data_inventory_pos_fields_presence"] = 1.0 if pos_presence_ok else 0.0
    scores["data_inventory_pos_frequency_correct"] = 1.0 if pos_freq_ok else 0.0

    # 4) risk_register structure and content
    required_risk_cols = {
        "risk_id",
        "risk_title",
        "category",
        "likelihood",
        "impact",
        "risk_score",
        "affected_fields",
        "policy_gap",
        "current_controls",
        "recommended_controls",
        "citation_ids",
    }
    risk_has_cols = False
    risk_sorted_count_ok = False
    risk_categories_ok = False
    risk_score_formula_ok = False
    risk_impact_policy_gap_ok = False
    risk_policy_gap_expected_ok = False
    risk_citations_crossref_ok = False
    risk_controls_present_ok = False

    # Compliance sources structure
    compliance_structure_ok = False
    compliance_bodies_ok = False
    compliance_no_urls_ok = False
    compliance_ids: List[str] = []

    # Validate compliance_sources first (used downstream)
    if isinstance(compliance_sources, list):
        # length between 3 and 5
        length_ok = 3 <= len(compliance_sources) <= 5
        objects_ok = True
        ids_set = set()
        bodies_present: List[str] = []
        any_strings = []
        for item in compliance_sources:
            if not isinstance(item, dict):
                objects_ok = False
                break
            keys_ok = {"id", "document_title", "issuing_body", "publication_year", "tags"}.issubset(item.keys())
            if not keys_ok:
                objects_ok = False
                break
            id_val = str(item.get("id", "")).strip()
            if not re.fullmatch(r"[a-z0-9_\-]+", id_val):
                objects_ok = False
                break
            ids_set.add(id_val)
            bodies_present.append(str(item.get("issuing_body", "")))
            # check tags non-empty
            tags_val = item.get("tags")
            if isinstance(tags_val, list):
                if not tags_val:
                    objects_ok = False
                    break
                for t in tags_val:
                    if not isinstance(t, str) or t.strip() == "":
                        objects_ok = False
                        break
            elif isinstance(tags_val, str):
                if tags_val.strip() == "":
                    objects_ok = False
                    break
            else:
                objects_ok = False
                break
            # publication_year digits check
            pub = item.get("publication_year")
            if isinstance(pub, int):
                pass
            elif isinstance(pub, str) and pub.strip().isdigit():
                pass
            else:
                objects_ok = False
                break
            any_strings.extend(_extract_all_strings(item))
        compliance_ids = sorted(list(ids_set))
        # official bodies check: at least one recognized body present
        recognized_bodies = [
            "pci security standards council",
            "federal trade commission",
            "ftc",
            "nist",
            "national institute of standards and technology",
            "california attorney general",
            "california department of justice",
        ]
        bodies_text = " ".join([b.lower() for b in bodies_present])
        bodies_ok = any(rb in bodies_text for rb in recognized_bodies)
        no_urls = True
        for s in any_strings:
            if _contains_url(s):
                no_urls = False
                break
        compliance_structure_ok = length_ok and objects_ok
        compliance_bodies_ok = bodies_ok
        compliance_no_urls_ok = no_urls

    scores["compliance_sources_valid_structure"] = 1.0 if compliance_structure_ok else 0.0
    scores["compliance_sources_official_bodies_included"] = 1.0 if compliance_bodies_ok else 0.0
    scores["compliance_sources_no_urls"] = 1.0 if compliance_no_urls_ok else 0.0

    # Validate risk register
    if risk_register_rows is not None:
        headers = _read_csv_headers(risk_register_path) or []
        if required_risk_cols.issubset(set(headers)):
            risk_has_cols = True

            # Sorted descending by risk_score and at least 10 rows
            scores_list: List[Tuple[int, Dict[str, str]]] = []
            sortable_ok = True
            for r in risk_register_rows:
                rs = _safe_int(r.get("risk_score"))
                if rs is None:
                    sortable_ok = False
                    break
                scores_list.append((rs, r))
            if sortable_ok and len(scores_list) >= 10:
                # check sorted desc (non-increasing)
                risk_scores_only = [rs for rs, _ in scores_list]
                # Compute actual order from file
                extracted_scores_in_order: List[Optional[int]] = []
                for r in risk_register_rows:
                    rs = _safe_int(r.get("risk_score"))
                    extracted_scores_in_order.append(rs)
                if None not in extracted_scores_in_order:
                    is_desc = all(
                        extracted_scores_in_order[i] >= extracted_scores_in_order[i + 1]
                        for i in range(len(extracted_scores_in_order) - 1)
                    )
                    if is_desc:
                        risk_sorted_count_ok = True

            # Categories covered
            categories_present = {str(r.get("category", "")).strip() for r in risk_register_rows}
            required_categories = {"Image", "Financial (payment)", "PII", "Metadata"}
            if required_categories.issubset(categories_present):
                risk_categories_ok = True

            # Score formula correct: risk_score == impact * likelihood for every row
            formula_ok = True
            for r in risk_register_rows:
                lik = _safe_int(r.get("likelihood"))
                imp = _safe_int(r.get("impact"))
                rs = _safe_int(r.get("risk_score"))
                if lik is None or imp is None or rs is None:
                    formula_ok = False
                    break
                if rs != (lik * imp):
                    formula_ok = False
                    break
            risk_score_formula_ok = formula_ok

            # Impact consistent with policy_gap and base impact per category
            impact_map = {
                "Image": 5,
                "Financial (payment)": 5,
                "PII": 4,
                "Metadata": 4,
                "Financial (non-payment)": 3,
                "Preference": 2,
                "Consent": 1,
            }
            impact_consistent = True
            checked_rows = 0
            for r in risk_register_rows:
                category = str(r.get("category", "")).strip()
                if category in impact_map:
                    base = impact_map[category]
                    pg = str(r.get("policy_gap", "")).strip().lower()
                    imp = _safe_int(r.get("impact"))
                    if imp is None:
                        impact_consistent = False
                        break
                    expected = base + 1 if pg == "true" else base
                    if expected > 5:
                        expected = 5
                    if imp != expected:
                        impact_consistent = False
                        break
                    checked_rows += 1
            if impact_consistent and checked_rows > 0:
                risk_impact_policy_gap_ok = True

            # Expected categories should have policy_gap true for at least one row
            policy_gap_needed_cats = {"Image", "Metadata", "Financial (payment)"}
            need_ok = True
            for cat in policy_gap_needed_cats:
                any_true = False
                for r in risk_register_rows:
                    if str(r.get("category", "")).strip() == cat and str(r.get("policy_gap", "")).strip().lower() == "true":
                        any_true = True
                        break
                if not any_true:
                    need_ok = False
                    break
            risk_policy_gap_expected_ok = need_ok

            # Citations cross-ref and controls presence
            citations_ok = True
            controls_ok = True
            if compliance_ids:
                valid_ids = set(compliance_ids)
                for r in risk_register_rows:
                    # controls non-empty
                    if str(r.get("current_controls", "")).strip() == "" or str(r.get("recommended_controls", "")).strip() == "":
                        controls_ok = False
                        break
                    cids = str(r.get("citation_ids", "")).strip()
                    if cids == "":
                        citations_ok = False
                        break
                    split_ids = [cid.strip() for cid in cids.split(";") if cid.strip() != ""]
                    if not split_ids:
                        citations_ok = False
                        break
                    for cid in split_ids:
                        if cid not in valid_ids:
                            citations_ok = False
                            break
                    if not citations_ok:
                        break
            else:
                citations_ok = False
                # controls should still be checked even if compliance missing
                for r in risk_register_rows:
                    if str(r.get("current_controls", "")).strip() == "" or str(r.get("recommended_controls", "")).strip() == "":
                        controls_ok = False
                        break

            risk_citations_crossref_ok = citations_ok
            risk_controls_present_ok = controls_ok

    scores["risk_register_has_required_columns"] = 1.0 if risk_has_cols else 0.0
    scores["risk_register_sorted_and_min_rows"] = 1.0 if risk_sorted_count_ok else 0.0
    scores["risk_register_categories_covered"] = 1.0 if risk_categories_ok else 0.0
    scores["risk_register_score_calculation_correct"] = 1.0 if risk_score_formula_ok else 0.0
    scores["risk_register_impact_policy_gap_consistent"] = 1.0 if risk_impact_policy_gap_ok else 0.0
    scores["risk_register_policy_gap_expected_categories"] = 1.0 if risk_policy_gap_expected_ok else 0.0
    scores["risk_register_citations_crossref"] = 1.0 if risk_citations_crossref_ok else 0.0
    scores["risk_register_controls_present"] = 1.0 if risk_controls_present_ok else 0.0

    # 5) summary.md checks
    summary_exists_ok = summary_text.strip() != ""
    scores["summary_exists"] = 1.0 if summary_exists_ok else 0.0

    # Summary lists input tree files
    input_files = _list_input_files(workspace)
    list_ok = False
    if summary_exists_ok and input_files:
        # Require that all observed input files are listed in the summary text
        # i.e., the text contains each path substring
        all_present = all((p in summary_text) for p in input_files)
        list_ok = all_present
    scores["summary_lists_input_tree"] = 1.0 if list_ok else 0.0

    # Summary mentions top 5 risks (risk_id at least)
    top5_ok = False
    if summary_exists_ok and risk_register_rows is not None and len(risk_register_rows) >= 5:
        # Determine top 5 per sorted file (already required to be sorted desc)
        top5 = risk_register_rows[:5]
        # Check each risk_id is mentioned in summary
        all_ids_present = True
        for r in top5:
            rid = str(r.get("risk_id", "")).strip()
            if rid == "" or rid not in summary_text:
                all_ids_present = False
                break
        top5_ok = all_ids_present
    scores["summary_mentions_top5_risks"] = 1.0 if top5_ok else 0.0

    # Summary describes method and formula (mentions Impact and Likelihood)
    method_ok = False
    if summary_exists_ok:
        s_lower = summary_text.lower()
        method_ok = ("method" in s_lower) and ("impact" in s_lower) and ("likelihood" in s_lower) and ("risk" in s_lower)
    scores["summary_describes_method_and_formula"] = 1.0 if method_ok else 0.0

    # Summary mentions search queries and issuing bodies (and no URLs)
    search_ok = False
    if summary_exists_ok and isinstance(compliance_sources, list) and compliance_sources:
        bodies = [str(item.get("issuing_body", "")).strip() for item in compliance_sources if isinstance(item, dict)]
        bodies = [b for b in bodies if b]
        bodies_ok = all((b in summary_text) for b in bodies) if bodies else False
        search_word = ("search" in summary_text.lower()) or ("queries" in summary_text.lower())
        no_urls_in_summary = not _contains_url(summary_text)
        search_ok = bodies_ok and search_word and no_urls_in_summary
    scores["summary_mentions_search_and_bodies"] = 1.0 if search_ok else 0.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()