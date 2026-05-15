import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from datetime import datetime
import importlib.util


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        txt = read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def parse_scope_yaml(path: Path) -> Dict[str, Any]:
    """
    Minimal YAML parser for keys: state, district, languages (inline or block),
    topics (block list or inline), must_include_sources (block list or inline).
    Returns dict with keys: state, district, languages(list), topics(list), must_include_sources(list).
    """
    result = {
        "state": None,
        "district": None,
        "languages": [],
        "topics": [],
        "must_include_sources": [],
    }
    txt = read_text(path)
    if txt is None:
        return result

    lines = txt.splitlines()
    current_section = None
    list_mode_sections = {"languages", "topics", "must_include_sources"}
    expecting_list = None

    def parse_value(val: str) -> str:
        v = val.strip()
        if v.startswith("#") or v == "":
            return ""
        if " #" in v:
            v = v.split(" #", 1)[0]
        if v.startswith('"') and v.endswith('"') and len(v) >= 2:
            return v[1:-1]
        if v.startswith("'") and v.endswith("'") and len(v) >= 2:
            return v[1:-1]
        return v

    def parse_inline_list(s: str) -> List[str]:
        items = []
        inside = s.strip()
        if inside.startswith("[") and inside.endswith("]"):
            inside = inside[1:-1]
        for m in re.finditer(r'"([^"]+)"|\'([^\']+)\'', inside):
            item = m.group(1) if m.group(1) is not None else m.group(2)
            if item is not None:
                items.append(item.strip())
        if not items:
            parts = [p.strip() for p in inside.split(",") if p.strip()]
            items.extend(parts)
        clean = []
        for it in items:
            it2 = it
            if it2.startswith('"') and it2.endswith('"'):
                it2 = it2[1:-1]
            if it2.startswith("'") and it2.endswith("'"):
                it2 = it2[1:-1]
            clean.append(it2.strip())
        return [c for c in clean if c != ""]

    temp_lists: Dict[str, List[str]] = {k: [] for k in list_mode_sections}

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        striped = line.strip()
        if striped.startswith("#") or striped == "":
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            rest = m.group(2)
            current_section = key
            expecting_list = False
            if key in ("state", "district"):
                val = parse_value(rest)
                result[key] = val
            elif key in list_mode_sections:
                if rest is not None and rest.strip().startswith("["):
                    items = parse_inline_list(rest.strip())
                    temp_lists[key] = items
                    result[key] = items
                    expecting_list = False
                else:
                    expecting_list = True
                    temp_lists[key] = []
                    result[key] = temp_lists[key]
            else:
                pass
            continue

        if current_section in list_mode_sections and expecting_list:
            li_match = re.match(r"^\s*-\s*(.*)$", line)
            if li_match:
                item_raw = li_match.group(1).strip()
                item = parse_value(item_raw)
                if item != "":
                    temp_lists[current_section].append(item)
                continue
            else:
                expecting_list = False
                current_section = None
                continue

    for k in list_mode_sections:
        result[k] = temp_lists.get(k, result.get(k, [])) or []

    result["languages"] = [l for l in [s.strip() for s in result.get("languages", [])] if l]
    return result


def list_snapshot_files(workspace: Path) -> Dict[str, List[Path]]:
    snaps_dir = workspace / "outputs" / "snapshots"
    state = []
    district = []
    try:
        if snaps_dir.exists():
            for p in snaps_dir.glob("*.html"):
                name = p.name.lower()
                if name.startswith("state_"):
                    state.append(p)
                elif name.startswith("district_"):
                    district.append(p)
    except Exception:
        pass
    return {"state": sorted(state), "district": sorted(district)}


def get_netloc(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""


def registrable_domain(netloc: str) -> str:
    parts = [p for p in netloc.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return netloc


def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    val = s.strip()
    try:
        if val.endswith("Z"):
            datetime.fromisoformat(val.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(val)
        return True
    except Exception:
        return False


def import_parse_utils(workspace: Path):
    mod_path = workspace / "scripts" / "parse_utils.py"
    if not mod_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("parse_utils", str(mod_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(mod)  # type: ignore
        return mod
    except Exception:
        return None


def test_parse_utils(mod) -> Dict[str, float]:
    scores = {
        "parse_utils_title": 0.0,
        "parse_utils_emails": 0.0,
        "parse_utils_phones": 0.0,
        "parse_utils_languages": 0.0,
        "parse_utils_translation_hint": 0.0,
        "parse_utils_infer_org_name": 0.0,
    }
    try:
        sample_html = """
        <html><head><title>
            Welcome to Enrollment & Language Access
        </title></head>
        <body>
            Contact us: enroll@doe.mass.edu, support@springfieldpublicschools.com
            Or call (413) 555-1234 or 413-555-5678. Translation and interpretation services available.
            Spanish, Portuguese, and HAITIAN CREOLE support provided. Email enroll@doe.mass.edu for more info.
        </body></html>
        """
        title = mod.extract_page_title(sample_html)
        expected_title = "Welcome to Enrollment & Language Access"
        scores["parse_utils_title"] = 1.0 if title == expected_title else 0.0
        emails = mod.extract_emails(sample_html)
        expected_emails = sorted(["enroll@doe.mass.edu", "support@springfieldpublicschools.com"])
        scores["parse_utils_emails"] = 1.0 if emails == expected_emails else 0.0
        phones = mod.extract_phones(sample_html)
        expected_phones = sorted(["(413) 555-1234", "413-555-5678"])
        scores["parse_utils_phones"] = 1.0 if phones == expected_phones else 0.0
        langs = mod.detect_languages(sample_html, ["Spanish", "Portuguese", "Haitian Creole"])
        expected_langs = ["Spanish", "Portuguese", "Haitian Creole"]
        scores["parse_utils_languages"] = 1.0 if langs == expected_langs else 0.0
        hint = mod.has_translation_info(sample_html)
        scores["parse_utils_translation_hint"] = 1.0 if hint is True else 0.0
        oname = mod.infer_org_name_from_url("https://www.doe.mass.edu/ell/")
        scores["parse_utils_infer_org_name"] = 1.0 if oname == "MASS.EDU" else 0.0
    except Exception:
        pass
    return scores


def load_resources_json(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = safe_load_json(path)
    if isinstance(data, list):
        if all(isinstance(x, dict) for x in data):
            return data
    return None


def check_resources_fields(obj: Dict[str, Any]) -> bool:
    required_keys = {
        "source_type",
        "url",
        "source_file",
        "org_name",
        "page_title",
        "has_translation_info",
        "contacts",
        "languages_mentioned",
        "last_retrieved",
    }
    if set(obj.keys()) != required_keys:
        return False
    if obj.get("source_type") not in ("state", "district"):
        return False
    if not isinstance(obj.get("url"), str):
        return False
    if not isinstance(obj.get("source_file"), str):
        return False
    if not isinstance(obj.get("org_name"), str):
        return False
    if not isinstance(obj.get("page_title"), str):
        return False
    if not isinstance(obj.get("has_translation_info"), bool):
        return False
    contacts = obj.get("contacts")
    if not isinstance(contacts, dict):
        return False
    if not isinstance(contacts.get("emails"), list):
        return False
    if not isinstance(contacts.get("phones"), list):
        return False
    if not isinstance(obj.get("languages_mentioned"), list):
        return False
    if not isinstance(obj.get("last_retrieved"), str) or not is_iso8601(obj.get("last_retrieved")):
        return False
    return True


def derive_expected_from_html(mod, html: str, languages: List[str]) -> Tuple[str, List[str], List[str], bool, List[str]]:
    page_title = mod.extract_page_title(html)
    emails = mod.extract_emails(html)
    phones = mod.extract_phones(html)
    has_trans = mod.has_translation_info(html)
    langs = mod.detect_languages(html, languages)
    return page_title, emails, phones, has_trans, langs


def normalize_email_list_str(s: str) -> List[str]:
    if not isinstance(s, str):
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "scope_yaml_state": 0.0,
        "scope_yaml_district": 0.0,
        "scope_yaml_languages": 0.0,
        "scope_yaml_topics_preserved": 0.0,
        "scope_yaml_must_include_sources_preserved": 0.0,
        "snapshots_state_and_district_present": 0.0,
        "search_log_exists_and_schema": 0.0,
        "search_log_saved_files_exist": 0.0,
        "state_log_domain_official": 0.0,
        "district_log_domain_official": 0.0,
        "parse_utils_title": 0.0,
        "parse_utils_emails": 0.0,
        "parse_utils_phones": 0.0,
        "parse_utils_languages": 0.0,
        "parse_utils_translation_hint": 0.0,
        "parse_utils_infer_org_name": 0.0,
        "resources_json_exists": 0.0,
        "resources_cover_snapshots": 0.0,
        "resources_fields_complete": 0.0,
        "resources_contacts_from_html": 0.0,
        "resources_languages_from_html": 0.0,
        "resources_has_translation_info": 0.0,
        "resources_page_title_match": 0.0,
        "resources_org_name_match": 0.0,
        "assignments_exists_and_columns": 0.0,
        "assignments_rows_for_languages": 0.0,
        "assignments_contacts_valid_from_roster": 0.0,
        "assignments_prefer_roles": 0.0,
        "assignments_rationale_present": 0.0,
        "readme_exists_and_mentions": 0.0,
    }

    # Parse scope.yaml
    scope_path = workspace / "input" / "scope.yaml"
    scope = parse_scope_yaml(scope_path)
    expected_state = "Massachusetts"
    expected_district = "Springfield Public Schools"
    expected_languages = ["Spanish", "Portuguese", "Haitian Creole"]
    state_ok = scope.get("state") == expected_state
    district_ok = scope.get("district") == expected_district
    languages_ok = scope.get("languages") == expected_languages
    if state_ok:
        scores["scope_yaml_state"] = 1.0
    if district_ok:
        scores["scope_yaml_district"] = 1.0
    if languages_ok:
        scores["scope_yaml_languages"] = 1.0
    expected_topics = [
        "English Learner (EL/ELL) program policy",
        "Enrollment for newcomer students",
        "Family interpretation and translation services",
    ]
    topics = scope.get("topics") or []
    # Only award preservation points if the core config is correctly updated
    if topics == expected_topics and state_ok and district_ok and languages_ok:
        scores["scope_yaml_topics_preserved"] = 1.0
    expected_sources = [
        "Official state Department of Education site",
        "Official public school district site",
    ]
    mis = scope.get("must_include_sources") or []
    if mis == expected_sources and state_ok and district_ok and languages_ok:
        scores["scope_yaml_must_include_sources_preserved"] = 1.0

    # Snapshots presence
    snaps = list_snapshot_files(workspace)
    state_snaps = snaps["state"]
    district_snaps = snaps["district"]
    state1 = workspace / "outputs" / "snapshots" / "state_1.html"
    district1 = workspace / "outputs" / "snapshots" / "district_1.html"
    have_state1 = state1.exists()
    have_district1 = district1.exists()
    if have_state1 and have_district1:
        scores["snapshots_state_and_district_present"] = 1.0
    elif have_state1 or have_district1:
        scores["snapshots_state_and_district_present"] = 0.5
    else:
        scores["snapshots_state_and_district_present"] = 0.0

    # Import parse_utils and test only if snapshots exist to avoid awarding points on scaffold
    mod = None
    if have_state1 or have_district1:
        mod = import_parse_utils(workspace)
        if mod is not None:
            test_scores = test_parse_utils(mod)
            for k in ["parse_utils_title", "parse_utils_emails", "parse_utils_phones", "parse_utils_languages", "parse_utils_translation_hint", "parse_utils_infer_org_name"]:
                scores[k] = test_scores.get(k, 0.0)

    # search_log.json validation
    search_log_path = workspace / "outputs" / "search_log.json"
    search_log = safe_load_json(search_log_path)
    schema_ok = False
    files_ok = False
    state_domain_ok = False
    district_domain_ok = False
    if isinstance(search_log, list) and len(search_log) > 0:
        required_fields = {"query", "chosen_result_title", "chosen_result_domain", "url", "saved_file"}
        schema_ok = all(isinstance(entry, dict) and required_fields.issubset(entry.keys()) for entry in search_log)
        if schema_ok:
            all_exist = True
            for entry in search_log:
                saved_file = entry.get("saved_file", "")
                p = workspace / saved_file
                if not p.exists():
                    all_exist = False
                    break
                if not str(p).startswith(str(workspace / "outputs" / "snapshots")):
                    all_exist = False
                    break
            files_ok = all_exist

            def check_state_official(entry) -> bool:
                url = entry.get("url", "")
                host = get_netloc(url).lower()
                # Official MA state education pages are commonly on mass.gov or doe.mass.edu domains
                if host.endswith("mass.gov"):
                    return True
                if host.endswith("mass.edu") and ("doe" in host or "edu" in host):
                    return True
                return False

            def check_district_official(entry) -> bool:
                url = entry.get("url", "")
                host = get_netloc(url).lower()
                # Simple heuristic for Springfield Public Schools domains
                if "springfield" in host and ("k12" in host or "school" in host or "public" in host or "edu" in host):
                    return True
                return False

            def find_entry_for(fname: str) -> Optional[Dict[str, Any]]:
                for e in search_log:
                    if (e.get("saved_file") or "").replace("\\", "/").endswith(f"/{fname}"):
                        return e
                return None

            e_state = find_entry_for("state_1.html")
            e_district = find_entry_for("district_1.html")
            if e_state:
                state_domain_ok = check_state_official(e_state)
            if e_district:
                district_domain_ok = check_district_official(e_district)
    scores["search_log_exists_and_schema"] = 1.0 if schema_ok else 0.0
    scores["search_log_saved_files_exist"] = 1.0 if files_ok else 0.0
    scores["state_log_domain_official"] = 1.0 if state_domain_ok else 0.0
    scores["district_log_domain_official"] = 1.0 if district_domain_ok else 0.0

    # resources.json checks
    resources_path = workspace / "outputs" / "resources.json"
    resources = load_resources_json(resources_path)
    if resources is not None:
        scores["resources_json_exists"] = 1.0
        res_files = set()
        fields_ok = True
        for obj in resources:
            if not check_resources_fields(obj):
                fields_ok = False
            else:
                res_files.add(obj.get("source_file"))
        scores["resources_fields_complete"] = 1.0 if fields_ok else 0.0

        required_snaps_rel = []
        for p in state_snaps + district_snaps:
            try:
                rel = str(p.relative_to(workspace)).replace("\\", "/")
            except Exception:
                rel = str(p).replace("\\", "/")
            required_snaps_rel.append(rel)
        covered = all(rel in res_files for rel in required_snaps_rel) if required_snaps_rel else False
        scores["resources_cover_snapshots"] = 1.0 if covered else 0.0

        emails_match_all = True
        phones_match_all = True
        langs_match_all = True
        trans_match_all = True
        title_match_all = True
        org_name_match_all = True
        # Only perform deep comparison if parse_utils is available and languages configured
        if mod is None:
            mod = import_parse_utils(workspace)
        if mod is not None and (parse_scope_yaml(workspace / "input" / "scope.yaml").get("languages")):
            for obj in resources:
                source_file_rel = obj.get("source_file", "")
                source_abs = workspace / source_file_rel
                html = read_text(source_abs) or ""
                exp_title, exp_emails, exp_phones, exp_has_trans, exp_langs = derive_expected_from_html(
                    mod, html, scope.get("languages", [])
                )
                if obj.get("page_title", "") != exp_title:
                    title_match_all = False
                emails = obj.get("contacts", {}).get("emails", [])
                phones = obj.get("contacts", {}).get("phones", [])
                if sorted(emails) != sorted(exp_emails):
                    emails_match_all = False
                if sorted(phones) != sorted(exp_phones):
                    phones_match_all = False
                if bool(obj.get("has_translation_info")) != bool(exp_has_trans):
                    trans_match_all = False
                langs = obj.get("languages_mentioned", [])
                if langs != exp_langs:
                    langs_match_all = False
                url = obj.get("url", "")
                exp_org = mod.infer_org_name_from_url(url)
                if obj.get("org_name", "") != exp_org:
                    org_name_match_all = False
            scores["resources_contacts_from_html"] = 1.0 if (emails_match_all and phones_match_all) else 0.0
            scores["resources_languages_from_html"] = 1.0 if langs_match_all else 0.0
            scores["resources_has_translation_info"] = 1.0 if trans_match_all else 0.0
            scores["resources_page_title_match"] = 1.0 if title_match_all else 0.0
            scores["resources_org_name_match"] = 1.0 if org_name_match_all else 0.0
        else:
            scores["resources_contacts_from_html"] = 0.0
            scores["resources_languages_from_html"] = 0.0
            scores["resources_has_translation_info"] = 0.0
            scores["resources_page_title_match"] = 0.0
            scores["resources_org_name_match"] = 0.0
    else:
        scores["resources_json_exists"] = 0.0

    # assignments.csv checks
    assignments_path = workspace / "outputs" / "assignments.csv"
    roster_path = workspace / "input" / "team_roster.csv"
    assignments = safe_read_csv(assignments_path)
    roster = safe_read_csv(roster_path)

    if assignments is not None:
        expected_columns = ["language", "recommended_contacts", "rationale"]
        header_ok = False
        try:
            with assignments_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                first_line = f.readline()
                header = [h.strip() for h in first_line.strip().split(",")]
                header_ok = header == expected_columns
        except Exception:
            header_ok = False
        scores["assignments_exists_and_columns"] = 1.0 if header_ok else 0.0

        langs = scope.get("languages") or []
        if langs:
            present_ok = True
            lang_to_rows: Dict[str, List[Dict[str, str]]] = {l: [] for l in langs}
            for row in assignments:
                lval = (row.get("language") or "").strip()
                if lval in lang_to_rows:
                    lang_to_rows[lval].append(row)
            for l in langs:
                if len(lang_to_rows.get(l, [])) < 1:
                    present_ok = False
                    break
            scores["assignments_rows_for_languages"] = 1.0 if present_ok else 0.0

            roster_by_email: Dict[str, Dict[str, str]] = {}
            if roster is not None:
                for r in roster:
                    email = (r.get("email") or "").strip()
                    if email:
                        roster_by_email[email] = r
            contacts_valid = True
            prefer_roles_ok = True
            rationale_ok = True
            for l in langs:
                rows = lang_to_rows.get(l, [])
                preferred_roles = {"Family Liaison", "ESL Teacher"}
                roster_preferred = []
                for r in roster or []:
                    lang_field = (r.get("languages") or "")
                    rlangs = [x.strip().lower() for x in lang_field.split(";")]
                    if l.lower() in rlangs and (r.get("role") or "").strip() in preferred_roles:
                        roster_preferred.append(r)
                has_preferred_included = False
                for row in rows:
                    rec = row.get("recommended_contacts") or ""
                    rec_emails = normalize_email_list_str(rec)
                    if len(rec_emails) == 0:
                        contacts_valid = False
                    for e in rec_emails:
                        r = roster_by_email.get(e)
                        if r is None:
                            contacts_valid = False
                        else:
                            langs_for_r = [x.strip().lower() for x in (r.get("languages") or "").split(";")]
                            if l.lower() not in langs_for_r:
                                contacts_valid = False
                            if (r.get("role") or "").strip() in preferred_roles:
                                has_preferred_included = True
                    rationale = (row.get("rationale") or "").strip()
                    if len(rationale) < 8:
                        rationale_ok = False
                if roster_preferred and not has_preferred_included:
                    prefer_roles_ok = False
            scores["assignments_contacts_valid_from_roster"] = 1.0 if contacts_valid else 0.0
            scores["assignments_prefer_roles"] = 1.0 if prefer_roles_ok else 0.0
            scores["assignments_rationale_present"] = 1.0 if rationale_ok else 0.0
        else:
            scores["assignments_rows_for_languages"] = 0.0
            scores["assignments_contacts_valid_from_roster"] = 0.0
            scores["assignments_prefer_roles"] = 0.0
            scores["assignments_rationale_present"] = 0.0
    else:
        scores["assignments_exists_and_columns"] = 0.0
        scores["assignments_rows_for_languages"] = 0.0
        scores["assignments_contacts_valid_from_roster"] = 0.0
        scores["assignments_prefer_roles"] = 0.0
        scores["assignments_rationale_present"] = 0.0

    # README checks
    readme_path = workspace / "outputs" / "README.md"
    readme_txt = read_text(readme_path) or ""
    if readme_txt:
        has_scope = "scope.yaml" in readme_txt or "input/scope.yaml" in readme_txt
        has_outputs = "outputs" in readme_txt
        has_parse_utils = "parse_utils" in readme_txt or "scripts/parse_utils.py" in readme_txt
        if has_scope and has_outputs and has_parse_utils:
            scores["readme_exists_and_mentions"] = 1.0
        elif has_scope and has_outputs:
            scores["readme_exists_and_mentions"] = 0.5
        else:
            scores["readme_exists_and_mentions"] = 0.0
    else:
        scores["readme_exists_and_mentions"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()