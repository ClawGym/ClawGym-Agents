import csv
import json
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_csv_header_and_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            header = [h.strip() for h in header]
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _load_domains(domains_csv: Path):
    header, rows = _load_csv_header_and_rows(domains_csv)
    if header is None or rows is None:
        return None
    # Expect a 'domain' column (case-sensitive per task)
    # Allow minor whitespace differences in header names
    try:
        idx = [h.strip() for h in header].index("domain")
    except ValueError:
        return None
    domains = []
    for r in rows:
        if idx < len(r):
            d = r[idx].strip()
            if d:
                domains.append(d)
    return domains


def _parse_robots(content: str):
    disallow_count = 0
    disallow_press_or_news_count = 0
    discovered_sitemaps = []
    if content is None:
        return disallow_count, disallow_press_or_news_count, discovered_sitemaps
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strictly match lines that start with "Disallow:" and "Sitemap:" as per task wording
        if line.startswith("Disallow:"):
            disallow_count += 1
            path = line[len("Disallow:"):].strip()
            lower = path.lower()
            if any(k in lower for k in ("press", "news", "media")):
                disallow_press_or_news_count += 1
        elif line.startswith("Sitemap:"):
            loc = line[len("Sitemap:"):].strip()
            if loc:
                discovered_sitemaps.append(loc)
    return disallow_count, disallow_press_or_news_count, discovered_sitemaps


def _list_files_under(root: Path):
    files = []
    if not root.exists():
        return files
    for p in root.rglob("*"):
        if p.is_file():
            files.append(p)
    return files


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _count_xml_sitemaps_for_domain(web_domain_dir: Path) -> int:
    if not web_domain_dir.exists():
        return 0
    count = 0
    for p in _list_files_under(web_domain_dir):
        if p.suffix.lower() == ".xml":
            count += 1
    return count


def _parse_press_like_urls_csv(path: Path):
    # Returns tuple: (valid_header: bool, rows: list of dict(url, source_sitemap))
    header, rows_raw = _load_csv_header_and_rows(path)
    if header is None or rows_raw is None:
        return False, []
    # Normalize header by stripping whitespace
    norm_header = [h.strip() for h in header]
    expected_header = ["url", "source_sitemap"]
    if norm_header != expected_header:
        return False, []
    # Build row dicts
    rows = []
    for r in rows_raw:
        if len(r) < 2:
            # malformed row
            return False, []
        url = r[0].strip()
        source = r[1].strip()
        rows.append({"url": url, "source_sitemap": source})
    return True, rows


def _load_robots_summary(path: Path):
    # Returns (ok, header, rows_dict_by_domain) with numeric fields parsed when possible
    header, rows_raw = _load_csv_header_and_rows(path)
    if header is None or rows_raw is None:
        return False, None, {}
    norm_header = [h.strip() for h in header]
    expected_header = [
        "domain",
        "robots_status",
        "disallow_count",
        "disallow_press_or_news_count",
        "sitemaps_discovered_count",
        "sitemaps_fetched_xml_count",
        "press_like_urls_found_count",
    ]
    if norm_header != expected_header:
        return False, norm_header, {}
    idx = {name: i for i, name in enumerate(norm_header)}
    rows = {}
    for r in rows_raw:
        if len(r) < len(expected_header):
            return False, norm_header, {}
        domain = r[idx["domain"]].strip()
        if not domain or domain in rows:
            return False, norm_header, {}
        rows[domain] = {
            "robots_status": r[idx["robots_status"]].strip(),
            "disallow_count": r[idx["disallow_count"]].strip(),
            "disallow_press_or_news_count": r[idx["disallow_press_or_news_count"]].strip(),
            "sitemaps_discovered_count": r[idx["sitemaps_discovered_count"]].strip(),
            "sitemaps_fetched_xml_count": r[idx["sitemaps_fetched_xml_count"]].strip(),
            "press_like_urls_found_count": r[idx["press_like_urls_found_count"]].strip(),
        }
    return True, norm_header, rows


def _parse_int_safe(val: str):
    try:
        return int(val)
    except Exception:
        return None


def _is_valid_status_code_str(s: str) -> bool:
    if not s or not s.isdigit():
        return False
    try:
        v = int(s)
        return 100 <= v <= 599
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "robots_summary_exists_structure": 0.0,
        "robots_status_values_valid": 0.0,
        "disallow_count_match": 0.0,
        "disallow_press_or_news_count_match": 0.0,
        "sitemaps_discovered_count_match": 0.0,
        "sitemaps_fetched_xml_count_match": 0.0,
        "press_like_urls_csvs_exist_and_header": 0.0,
        "press_like_urls_found_count_match": 0.0,
        "press_like_urls_values_valid": 0.0,
        "manifest_json_valid": 0.0,
    }

    # Load expected domains
    domains_csv = workspace / "input" / "domains.csv"
    domains = _load_domains(domains_csv)
    if not domains:
        # Cannot proceed with domain-dependent checks
        return scores

    # Load robots summary
    robots_summary_path = workspace / "output" / "robots_summary.csv"
    summary_ok, _, summary_rows = _load_robots_summary(robots_summary_path)
    # Check structure and domain coverage
    if summary_ok and set(summary_rows.keys()) == set(domains):
        scores["robots_summary_exists_structure"] = 1.0

    # Compute per-domain expected values and compare to summary where applicable
    all_status_ok = True
    all_disallow_ok = True
    all_disallow_press_ok = True
    all_sitemaps_discovered_ok = True
    all_sitemaps_fetched_count_ok = True
    all_press_count_match_ok = True

    # Track press_like_urls CSV header existence and validity
    press_csv_headers_ok = True
    press_values_all_ok = True

    for domain in domains:
        web_dir = workspace / "web" / domain
        robots_file = web_dir / "robots.txt"
        robots_content = _read_text(robots_file) if robots_file.exists() else None

        disallow_count, disallow_press_count, discovered_sitemaps = _parse_robots(robots_content)
        xml_count = _count_xml_sitemaps_for_domain(web_dir)

        # Validate press_like_urls CSV exists and header
        press_csv_path = workspace / "output" / "press_like_urls" / f"{domain}.csv"
        if not press_csv_path.exists():
            press_csv_headers_ok = False
            press_rows = []
            press_header_valid = False
        else:
            press_header_valid, press_rows = _parse_press_like_urls_csv(press_csv_path)
            if not press_header_valid:
                press_csv_headers_ok = False

        # Compare press_like_urls_found_count to rows length (if summary available)
        if summary_ok and domain in summary_rows:
            val = _parse_int_safe(summary_rows[domain]["press_like_urls_found_count"])
            if val is None or val != len(press_rows):
                all_press_count_match_ok = False
        else:
            all_press_count_match_ok = False

        # Validate robots_status based on robots.txt presence
        if summary_ok and domain in summary_rows:
            status_val = summary_rows[domain]["robots_status"]
            if robots_content is None:
                if status_val != "unavailable":
                    all_status_ok = False
            else:
                if not _is_valid_status_code_str(status_val):
                    all_status_ok = False
        else:
            all_status_ok = False

        # Compare numeric fields in summary to computed values
        if summary_ok and domain in summary_rows:
            # disallow_count
            dc = _parse_int_safe(summary_rows[domain]["disallow_count"])
            if dc is None or dc != disallow_count:
                all_disallow_ok = False
            # disallow_press_or_news_count
            dpc = _parse_int_safe(summary_rows[domain]["disallow_press_or_news_count"])
            if dpc is None or dpc != disallow_press_count:
                all_disallow_press_ok = False
            # sitemaps_discovered_count
            sdc = _parse_int_safe(summary_rows[domain]["sitemaps_discovered_count"])
            if sdc is None or sdc != len(discovered_sitemaps):
                all_sitemaps_discovered_ok = False
            # sitemaps_fetched_xml_count
            sfc = _parse_int_safe(summary_rows[domain]["sitemaps_fetched_xml_count"])
            if sfc is None or sfc != xml_count:
                all_sitemaps_fetched_count_ok = False
        else:
            all_disallow_ok = False
            all_disallow_press_ok = False
            all_sitemaps_discovered_ok = False
            all_sitemaps_fetched_count_ok = False

        # Validate press_like_urls values: up to 20, unique URLs, URLs contain press/news/media in path,
        # and source_sitemap is basename of an XML file in web/<domain>.
        if press_header_valid:
            # Limit and uniqueness
            urls = [row["url"] for row in press_rows]
            if len(press_rows) > 20:
                press_values_all_ok = False
            if len(set(urls)) != len(urls):
                press_values_all_ok = False
            # Validate each row
            # Build allowed source sitemap basenames from .xml files in web/<domain>
            xml_basenames = set()
            for p in _list_files_under(web_dir):
                if p.suffix.lower() == ".xml":
                    xml_basenames.add(p.name)
            for row in press_rows:
                u = row["url"]
                src = row["source_sitemap"]
                # Check source_sitemap is one of the basenames we have
                if src not in xml_basenames:
                    press_values_all_ok = False
                    break
                # Check URL path contains press/news/media (case-insensitive)
                parsed = urlparse(u)
                path_to_check = parsed.path or u
                lower = path_to_check.lower()
                if not any(k in lower for k in ("press", "news", "media")):
                    press_values_all_ok = False
                    break
        else:
            press_values_all_ok = False

    # Set scores based on aggregated checks
    if all_status_ok:
        scores["robots_status_values_valid"] = 1.0
    if all_disallow_ok:
        scores["disallow_count_match"] = 1.0
    if all_disallow_press_ok:
        scores["disallow_press_or_news_count_match"] = 1.0
    if all_sitemaps_discovered_ok:
        scores["sitemaps_discovered_count_match"] = 1.0
    if all_sitemaps_fetched_count_ok:
        scores["sitemaps_fetched_xml_count_match"] = 1.0
    if press_csv_headers_ok:
        scores["press_like_urls_csvs_exist_and_header"] = 1.0
    if all_press_count_match_ok:
        scores["press_like_urls_found_count_match"] = 1.0
    if press_values_all_ok:
        scores["press_like_urls_values_valid"] = 1.0

    # Validate manifest.json
    manifest_path = workspace / "output" / "manifest.json"
    web_root = workspace / "web"
    manifest_ok = False
    try:
        if manifest_path.exists():
            raw = manifest_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                # Build expected set of files under web/
                expected_files = _list_files_under(web_root)
                expected_rel = set()
                for p in expected_files:
                    rel = p.relative_to(web_root)
                    expected_rel.add(rel.as_posix())
                # Build set from manifest and validate entries
                manifest_rel = set()
                details_ok = True
                for item in data:
                    if not isinstance(item, dict):
                        details_ok = False
                        break
                    if "path" not in item or "size_bytes" not in item or "sha256" not in item:
                        details_ok = False
                        break
                    p = item["path"]
                    size = item["size_bytes"]
                    sha = item["sha256"]
                    if not isinstance(p, str) or not isinstance(size, int) or not isinstance(sha, str):
                        details_ok = False
                        break
                    # Validate hex digest length for sha256
                    if len(sha) != 64:
                        details_ok = False
                        break
                    # Path must refer to a file under web_root
                    file_path = web_root / p
                    if not file_path.exists() or not file_path.is_file():
                        details_ok = False
                        break
                    # Validate size and sha256
                    actual_size = file_path.stat().st_size
                    actual_sha = _sha256_file(file_path)
                    if actual_sha is None or actual_size != size or actual_sha.lower() != sha.lower():
                        details_ok = False
                        break
                    manifest_rel.add(Path(p).as_posix())
                # Require exact match between manifest paths and actual web files
                if details_ok and manifest_rel == expected_rel:
                    manifest_ok = True
    except Exception:
        manifest_ok = False

    if manifest_ok:
        scores["manifest_json_valid"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()