import csv
import json
import hashlib
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlsplit


ALLOWED_HOUSES = {"christies.com", "sothebys.com", "bonhams.com", "ha.com"}
REQUIRED_COMPS_COLUMNS = [
    "house",
    "source_url",
    "local_html_path",
    "page_sha256",
    "artist",
    "item_type",
    "lot_title",
    "sale_date_iso",
    "realized_price_value",
    "realized_price_currency",
    "image_path",
    "matched_keywords",
    "extracted_at_utc",
]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _compute_sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_valid_iso_date(date_str: str) -> bool:
    if not date_str:
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _normalize_host(netloc: str) -> str:
    host = netloc.split("@")[-1]  # remove userinfo if any
    host = host.split(":")[0]  # remove port
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _url_matches_house(url: str, house: str) -> bool:
    try:
        parts = urlsplit(url)
        host = _normalize_host(parts.netloc)
        return host.endswith(house)
    except Exception:
        return False


def _is_valid_image_ext(path: str) -> bool:
    p = path.lower()
    return any(p.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"])


def _is_iso8601_utc(ts: str) -> bool:
    if not ts or not isinstance(ts, str):
        return False
    s = ts.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return False
        # Check UTC offset zero
        offset = dt.utcoffset()
        return offset == timedelta(0)
    except Exception:
        return False


def _parse_wanted(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    # Normalize keys in case of spaces, but here we expect exact columns: artist,item_type,era_keywords
    # We'll just pass through rows as-is.
    return rows


def _split_keywords(s: str) -> List[str]:
    if not s:
        return []
    return [tok.strip() for tok in s.split("|") if tok.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "comps_csv_exists_and_columns": 0.0,
        "comps_row_count_min": 0.0,
        "comps_per_artist_coverage": 0.0,
        "houses_distinct_at_least_two": 0.0,
        "house_domain_validity": 0.0,
        "source_url_domain_matches_house": 0.0,
        "local_html_path_structure": 0.0,
        "html_snapshots_exist_and_sha256_match": 0.0,
        "item_type_constant": 0.0,
        "lot_title_present": 0.0,
        "sale_date_format_and_presence": 0.0,
        "realized_price_fields_validity": 0.0,
        "image_paths_exist_and_extension": 0.0,
        "matched_keywords_subset_valid": 0.0,
        "extracted_at_utc_iso_utc": 0.0,
        "provenance_json_exists_and_fields": 0.0,
        "provenance_alignment_with_comps": 0.0,
        "logs_search_log_exists": 0.0,
        "logs_urls_recorded": 0.0,
        "logs_queries_cover_provenance": 0.0,
    }

    # Load input/wanted_items.csv
    wanted_path = workspace / "input" / "wanted_items.csv"
    wanted_rows = _parse_wanted(wanted_path)
    wanted_artists: List[str] = []
    artist_keywords_map: Dict[str, List[str]] = {}
    if wanted_rows:
        for r in wanted_rows:
            artist = (r.get("artist") or "").strip()
            if artist:
                wanted_artists.append(artist)
                era_keywords = _split_keywords(r.get("era_keywords") or "")
                artist_keywords_map[artist] = era_keywords

    # Load comps.csv
    comps_path = workspace / "data" / "comps.csv"
    comps_rows = _load_csv_dicts(comps_path)

    # Check comps existence and columns
    if comps_rows is not None:
        fieldnames = []
        try:
            with comps_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                fieldnames = next(reader, [])
        except Exception:
            fieldnames = list(comps_rows[0].keys()) if comps_rows else []
        # Verify required columns are present
        if set(REQUIRED_COMPS_COLUMNS).issubset(set(fieldnames)):
            scores["comps_csv_exists_and_columns"] = 1.0
        else:
            scores["comps_csv_exists_and_columns"] = 0.0

        total_rows = len(comps_rows)
        if total_rows >= 5:
            scores["comps_row_count_min"] = 1.0
        else:
            # Provide proportional score up to 5 rows
            scores["comps_row_count_min"] = max(0.0, min(1.0, total_rows / 5.0))

        # Coverage per artist
        covered = 0
        if wanted_artists:
            for a in wanted_artists:
                if any((row.get("artist") or "").strip() == a for row in comps_rows):
                    covered += 1
            scores["comps_per_artist_coverage"] = covered / len(wanted_artists)
        else:
            scores["comps_per_artist_coverage"] = 0.0

        # Distinct houses check
        houses = set((row.get("house") or "").strip() for row in comps_rows if (row.get("house") or "").strip())
        if len(houses & ALLOWED_HOUSES) >= 2:
            scores["houses_distinct_at_least_two"] = 1.0
        else:
            scores["houses_distinct_at_least_two"] = 0.0

        # Row-wise validations
        def row_iter():
            for row in comps_rows:
                yield row

        # house_domain_validity: house field is one of allowed
        hov = 0
        # source_url_domain_matches_house
        sudm = 0
        # local_html_path_structure
        lhps = 0
        # html_snapshots_exist_and_sha256_match
        hssha = 0
        # item_type_constant
        itc = 0
        # lot_title_present
        ltp = 0
        # sale_date
        sdf = 0
        # realized price validity
        rpfv = 0
        # image paths validity
        ipve = 0
        # matched_keywords subset
        mkv = 0
        # extracted_at_utc validity
        eauc = 0

        for row in row_iter():
            house = (row.get("house") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            local_html_path = (row.get("local_html_path") or "").strip()
            page_sha256 = (row.get("page_sha256") or "").strip()
            artist = (row.get("artist") or "").strip()
            item_type = (row.get("item_type") or "").strip()
            lot_title = (row.get("lot_title") or "").strip()
            sale_date_iso = (row.get("sale_date_iso") or "").strip()
            realized_val = (row.get("realized_price_value") or "").strip()
            realized_cur = (row.get("realized_price_currency") or "").strip()
            image_path = (row.get("image_path") or "").strip()
            matched_keywords = (row.get("matched_keywords") or "").strip()
            extracted_at_utc = (row.get("extracted_at_utc") or "").strip()

            # house validity
            if house in ALLOWED_HOUSES:
                hov += 1

            # source_url_domain_matches_house
            if source_url and house and _url_matches_house(source_url, house):
                sudm += 1

            # local_html_path_structure
            # must be data/raw/<house>/<id>.html
            lh_ok = False
            if local_html_path and house:
                p = Path(local_html_path)
                # path must be relative, start with data/raw/<house> and end with .html
                if not p.is_absolute() and str(p).startswith(f"data/raw/{house}/") and str(p).endswith(".html"):
                    # ensure the file part does not include path separators beyond the house dir (allow nested? Spec implies single file name)
                    # We accept any nested as long as path exists and ends with .html, but spec suggests <id>.html directly under house.
                    rel_parts = p.parts
                    try:
                        idx = rel_parts.index("raw")
                        # After "raw", next should be house, and last should be a file with .html
                        if idx + 1 < len(rel_parts) and rel_parts[idx + 1] == house and str(p.name).endswith(".html"):
                            lh_ok = True
                    except ValueError:
                        lh_ok = False
            if lh_ok:
                lhps += 1

            # html_snapshots_exist_and_sha256_match
            sha_ok = False
            if lh_ok:
                full_html_path = workspace / local_html_path
                if full_html_path.exists() and full_html_path.is_file():
                    computed = _compute_sha256_file(full_html_path)
                    if computed and page_sha256 and len(page_sha256) == 64:
                        if computed.lower() == page_sha256.lower():
                            sha_ok = True
            if sha_ok:
                hssha += 1

            # item_type_constant
            if item_type == "concert poster":
                itc += 1

            # lot_title_present
            if lot_title:
                ltp += 1

            # sale_date format and presence (strictly require non-empty and valid date)
            if _is_valid_iso_date(sale_date_iso):
                sdf += 1

            # realized_price_fields_validity
            rp_ok = False
            if realized_val == "":
                # currency must be empty too
                rp_ok = (realized_cur == "")
            else:
                # realized_val must be numeric (digits with optional decimal point), and currency non-empty
                if re.fullmatch(r"\d+(\.\d+)?", realized_val) and realized_cur != "":
                    rp_ok = True
            if rp_ok:
                rpfv += 1

            # image_paths_exist_and_extension
            img_ok = False
            if image_path == "":
                img_ok = True  # empty is allowed
            else:
                img_p = Path(image_path)
                if (str(img_p).startswith(f"images/{house}/")
                        and _is_valid_image_ext(str(img_p))
                        and (workspace / img_p).exists()):
                    img_ok = True
            if img_ok:
                ipve += 1

            # matched_keywords_subset_valid
            mk_ok = False
            if matched_keywords == "":
                mk_ok = True
            else:
                # ensure tokens are subset of wanted era keywords for this artist
                toks = [t.strip() for t in matched_keywords.split("|") if t.strip()]
                allowed = [k.lower() for k in artist_keywords_map.get(artist, [])]
                mk_ok = all(t.lower() in allowed for t in toks)
            if mk_ok:
                mkv += 1

            # extracted_at_utc_iso_utc
            if _is_iso8601_utc(extracted_at_utc):
                eauc += 1

        denom = len(comps_rows) if comps_rows is not None else 0
        if denom > 0:
            scores["house_domain_validity"] = hov / denom
            scores["source_url_domain_matches_house"] = sudm / denom
            scores["local_html_path_structure"] = lhps / denom
            scores["html_snapshots_exist_and_sha256_match"] = hssha / denom
            scores["item_type_constant"] = itc / denom
            scores["lot_title_present"] = ltp / denom
            scores["sale_date_format_and_presence"] = sdf / denom
            scores["realized_price_fields_validity"] = rpfv / denom
            scores["image_paths_exist_and_extension"] = ipve / denom
            scores["matched_keywords_subset_valid"] = mkv / denom
            scores["extracted_at_utc_iso_utc"] = eauc / denom

    else:
        # comps missing; keep defaults (0.0)
        pass

    # Provenance checks
    prov_path = workspace / "data" / "provenance.json"
    provenance = _load_json(prov_path)
    prov_ok_fields = 0.0
    prov_items: List[Dict[str, Any]] = []
    if isinstance(provenance, list):
        valid_field_items = 0
        for obj in provenance:
            if isinstance(obj, dict):
                has_fields = all(k in obj for k in ["source_url", "local_html_path", "house", "artist", "search_query_used"])
                if has_fields and (obj.get("house") in ALLOWED_HOUSES):
                    valid_field_items += 1
                    prov_items.append(obj)
        if len(provenance) > 0:
            prov_ok_fields = valid_field_items / len(provenance)
        else:
            prov_ok_fields = 0.0
    else:
        prov_ok_fields = 0.0
    scores["provenance_json_exists_and_fields"] = prov_ok_fields

    # Align provenance with comps
    if comps_rows is not None and isinstance(prov_items, list) and prov_items:
        # Build index on provenance with (source_url, local_html_path, house, artist)
        index = {}
        for p in prov_items:
            key = (p.get("source_url", ""), p.get("local_html_path", ""), p.get("house", ""), p.get("artist", ""))
            index.setdefault(key, []).append(p)
        aligned = 0
        total = len(comps_rows)
        for row in comps_rows:
            key = ((row.get("source_url") or "").strip(),
                   (row.get("local_html_path") or "").strip(),
                   (row.get("house") or "").strip(),
                   (row.get("artist") or "").strip())
            matches = index.get(key, [])
            ok = False
            if len(matches) == 1:
                p = matches[0]
                img_row = (row.get("image_path") or "").strip()
                if img_row:
                    # if image was saved, provenance must include it and match
                    img_prov = (p.get("image_path") or "").strip()
                    if img_prov == img_row:
                        ok = True
                else:
                    ok = True
            elif len(matches) >= 2:
                # ambiguous but consider not aligned
                ok = False
            else:
                ok = False
            if ok:
                aligned += 1
        scores["provenance_alignment_with_comps"] = (aligned / total) if total > 0 else 0.0
    else:
        scores["provenance_alignment_with_comps"] = 0.0

    # Logs checks
    logs_path = workspace / "logs" / "search_log.txt"
    log_text = _read_text(logs_path)
    if log_text is not None:
        scores["logs_search_log_exists"] = 1.0
    else:
        scores["logs_search_log_exists"] = 0.0

    # logs_urls_recorded: every comps source_url should be present in logs
    if log_text is not None and comps_rows is not None:
        urls_present = 0
        for row in comps_rows:
            url = (row.get("source_url") or "").strip()
            if url and (url in log_text):
                urls_present += 1
        total = len(comps_rows)
        scores["logs_urls_recorded"] = (urls_present / total) if total > 0 else 0.0
    else:
        scores["logs_urls_recorded"] = 0.0

    # logs_queries_cover_provenance: every provenance search_query_used appears in logs and includes artist, "concert poster", and site:<house>
    if log_text is not None and isinstance(provenance, list) and provenance:
        prov_queries_ok = 0
        count = 0
        for p in provenance:
            if not isinstance(p, dict):
                continue
            sq = (p.get("search_query_used") or "").strip()
            artist = (p.get("artist") or "").strip()
            house = (p.get("house") or "").strip()
            if not sq:
                continue
            count += 1
            sq_l = sq.lower()
            ok = True
            # Must include in logs
            if sq not in log_text:
                ok = False
            # Must include "concert poster"
            if "concert poster" not in sq_l:
                ok = False
            # Must include artist substring
            if artist and artist.lower() not in sq_l:
                ok = False
            # Must include site:<house>
            if house and f"site:{house}".lower() not in sq_l:
                ok = False
            if ok:
                prov_queries_ok += 1
        if count > 0:
            scores["logs_queries_cover_provenance"] = prov_queries_ok / count
        else:
            scores["logs_queries_cover_provenance"] = 0.0
    else:
        scores["logs_queries_cover_provenance"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()