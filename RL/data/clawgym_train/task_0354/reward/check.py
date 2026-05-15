import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        if not path.exists():
            return None, "missing"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, f"error: {e}"


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists():
            return None, "missing"
        return path.read_text(encoding="utf-8", errors="ignore"), None
    except Exception as e:
        return None, f"error: {e}"


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists():
            return None, "missing"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows, None
    except Exception as e:
        return None, f"error: {e}"


def _load_target_schools(workspace: Path) -> List[str]:
    target_csv = workspace / "input" / "target_programs.csv"
    rows, err = _read_csv_dicts(target_csv)
    if rows is None:
        return []
    schools = []
    for r in rows:
        name = r.get("school", "").strip()
        if name:
            schools.append(name)
    return schools


def _load_player_profile(workspace: Path) -> Dict[str, Any]:
    profile_path = workspace / "input" / "player_profile.json"
    data, _ = _read_json(profile_path)
    return data if isinstance(data, dict) else {}


def _expected_files_for_school(school: str, workspace: Path) -> Dict[str, Path]:
    base_raw = workspace / "output" / "webpages" / "raw"
    base_txt = workspace / "output" / "webpages" / "text"
    raw_staff = base_raw / f"{school}_staff.html"
    raw_recruit = base_raw / f"{school}_recruiting.html"
    txt_staff = base_txt / f"{school}_staff.txt"
    txt_recruit = base_txt / f"{school}_recruiting.txt"
    draft = workspace / "output" / "email_drafts" / f"{school}.txt"
    return {
        "raw_staff": raw_staff,
        "raw_recruit": raw_recruit,
        "txt_staff": txt_staff,
        "txt_recruit": txt_recruit,
        "draft": draft,
    }


def _domain_ok_for_school(school: str, url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    # Disallowed aggregator domains
    disallowed = [
        "ncsasports.org",
        "coachesdatabase.com",
        "wikipedia.org",
        "espn.com",
        "rivals.com",
        "247sports.com",
        "on3.com",
        "yahoo.com",
        "sports-reference.com",
        "maxpreps.com",
        "hudl.com",
        "hudl.com",
        "verbalcommits.com",
    ]
    for d in disallowed:
        if host == d or host.endswith("." + d):
            return False
    # Allowed by .edu generally
    if host.endswith(".edu"):
        return True
    # School-specific athletics domains
    allowed_map = {
        "University of North Carolina": ["goheels.com", "unc.edu"],
        "Duke University": ["goduke.com", "duke.edu"],
        "University of Kansas": ["kuathletics.com", "ku.edu"],
        "Gonzaga University": ["gozags.com", "gonzaga.edu"],
        "University of Kentucky": ["ukathletics.com", "uky.edu"],
    }
    allowed_list = allowed_map.get(school, [])
    for d in allowed_list:
        if host == d or host.endswith("." + d):
            return True
    # If not matched, consider unknown domain not clearly official
    return False


def _count_sentences(text: str) -> int:
    # Basic sentence splitting on ., ?, ! followed by whitespace/newline
    # Remove signature lines like contact info to avoid inflating count
    # We'll use a simple regex that splits on punctuation sequences.
    cleaned = text.strip()
    # Collapse multiple newlines/spaces
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return 0
    parts = re.split(r"[.!?]+(?:\s|$)", cleaned)
    count = sum(1 for p in parts if p.strip())
    return count


def _extract_header_and_body(draft_text: str) -> Tuple[Optional[str], Optional[str], str]:
    # Expect first lines include To: and Subject:
    lines = draft_text.splitlines()
    to_val = None
    subject_val = None
    body_lines: List[str] = []
    for i, line in enumerate(lines):
        if to_val is None and line.strip().lower().startswith("to:"):
            to_val = line.split(":", 1)[1].strip()
            continue
        if subject_val is None and line.strip().lower().startswith("subject:"):
            subject_val = line.split(":", 1)[1].strip()
            # Body starts after subject line; include following lines
            body_lines = lines[i + 1 :]
            break
    body = "\n".join(body_lines).strip() if body_lines else ""
    return to_val, subject_val, body


def _find_first_contact_email_for_school(contacts: List[Dict[str, str]], school: str) -> Optional[str]:
    for r in contacts:
        if r.get("school", "").strip() == school:
            email = r.get("email", "").strip()
            if email:
                return email
    return None


def _emails_in_school_files(workspace: Path, school: str) -> Tuple[List[Path], Dict[str, bool]]:
    expected = _expected_files_for_school(school, workspace)
    files = [
        expected["raw_staff"],
        expected["raw_recruit"],
        expected["txt_staff"],
        expected["txt_recruit"],
    ]
    present_files = [p for p in files if p.exists()]
    contents = {}
    for p in present_files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        contents[str(p)] = text
    return present_files, contents


def _recompute_email_match(workspace: Path, school: str, email: str) -> Tuple[bool, Optional[str]]:
    files, contents = _emails_in_school_files(workspace, school)
    for p in files:
        txt = contents.get(str(p), "")
        if not txt:
            continue
        if email.lower() in txt.lower():
            return True, str(p)
    return False, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "sources_json_structure": 0.0,
        "sources_json_has_all_schools": 0.0,
        "sources_urls_official_domain": 0.0,
        "raw_html_files_present": 0.0,
        "text_files_present_nonempty": 0.0,
        "fetch_log_structure": 0.0,
        "fetch_log_coverage_by_school": 0.0,
        "contacts_csv_structure": 0.0,
        "contacts_per_school_limit": 0.0,
        "contacts_source_files_exist_and_match": 0.0,
        "crosscheck_report_structure": 0.0,
        "crosscheck_correctness_vs_recomputation": 0.0,
        "email_drafts_present": 0.0,
        "email_subject_format": 0.0,
        "email_to_matches_contacts": 0.0,
        "email_body_includes_required_elements": 0.0,
        "email_unknown_questionnaire_logic": 0.0,
    }

    schools = _load_target_schools(workspace)
    profile = _load_player_profile(workspace)
    # Prepare expected subject components
    player_name = profile.get("name", "Jordan Miles")
    grad_year = profile.get("grad_year", 2026)
    gpa = profile.get("gpa_unweighted", 4.0)
    # Use SF per instruction
    subject_suffix = f"Men's Basketball — {player_name} ({grad_year} SF, {gpa:.1f} GPA)"

    # 1) sources.json checks
    sources_path = workspace / "output" / "sources.json"
    sources, sources_err = _read_json(sources_path)
    if isinstance(sources, dict):
        valid_shape = True
        # Expect keys = school names, values dict with staff, recruiting, each with search_query and url
        for sch in sources:
            entry = sources.get(sch)
            if not isinstance(entry, dict):
                valid_shape = False
                break
            for typ in ("staff", "recruiting"):
                inner = entry.get(typ)
                if not isinstance(inner, dict):
                    valid_shape = False
                    break
                if not isinstance(inner.get("search_query", ""), str) or not inner.get("search_query"):
                    valid_shape = False
                    break
                if not isinstance(inner.get("url", ""), str) or not inner.get("url"):
                    valid_shape = False
                    break
            if not valid_shape:
                break
        scores["sources_json_structure"] = 1.0 if valid_shape else 0.0

        # Must contain all schools
        if schools:
            has_all = all(
                (sch in sources)
                and isinstance(sources.get(sch), dict)
                and all(
                    isinstance(sources[sch].get(t, {}), dict)
                    and isinstance(sources[sch][t].get("url", ""), str)
                    and sources[sch][t].get("url", "").strip() != ""
                    and isinstance(sources[sch][t].get("search_query", ""), str)
                    and sources[sch][t].get("search_query", "").strip() != ""
                    for t in ("staff", "recruiting")
                )
                for sch in schools
            )
            scores["sources_json_has_all_schools"] = 1.0 if has_all else 0.0
        else:
            scores["sources_json_has_all_schools"] = 0.0
        # Official domain check
        if schools and scores["sources_json_structure"] == 1.0:
            total = 0
            ok_count = 0
            for sch in schools:
                entry = sources.get(sch, {})
                for t in ("staff", "recruiting"):
                    url = ""
                    if isinstance(entry, dict) and isinstance(entry.get(t), dict):
                        url = entry[t].get("url", "")
                    if url:
                        total += 1
                        if _domain_ok_for_school(sch, url):
                            ok_count += 1
            if total > 0:
                scores["sources_urls_official_domain"] = ok_count / total
            else:
                # if no urls present, fail
                scores["sources_urls_official_domain"] = 0.0
        else:
            scores["sources_urls_official_domain"] = 0.0
    else:
        scores["sources_json_structure"] = 0.0
        scores["sources_json_has_all_schools"] = 0.0
        scores["sources_urls_official_domain"] = 0.0

    # 2) webpages raw and text presence
    if schools:
        expected_raw = []
        expected_txt = []
        for sch in schools:
            pf = _expected_files_for_school(sch, workspace)
            expected_raw.extend([pf["raw_staff"], pf["raw_recruit"]])
            expected_txt.extend([pf["txt_staff"], pf["txt_recruit"]])
        if expected_raw:
            exist_count = sum(1 for p in expected_raw if p.exists())
            scores["raw_html_files_present"] = exist_count / len(expected_raw)
        if expected_txt:
            nonempty = 0
            for p in expected_txt:
                if p.exists():
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        content = ""
                    if content.strip():
                        nonempty += 1
            scores["text_files_present_nonempty"] = nonempty / len(expected_txt)
    # 2b) fetch_log.json validation
    fetch_log_path = workspace / "output" / "fetch_log.json"
    fetch_log, fetch_err = _read_json(fetch_log_path)
    if isinstance(fetch_log, list):
        # Structure validation for each record
        def _valid_entry(e: Any) -> bool:
            if not isinstance(e, dict):
                return False
            req_keys = ["school", "page_type", "url", "http_status", "ok", "error_message"]
            for k in req_keys:
                if k not in e:
                    return False
            if not isinstance(e["school"], str) or not e["school"].strip():
                return False
            if e["page_type"] not in ("staff", "recruiting"):
                return False
            if not isinstance(e["url"], str) or not e["url"]:
                return False
            if not isinstance(e["http_status"], int):
                return False
            if not isinstance(e["ok"], bool):
                return False
            if not isinstance(e["error_message"], str):
                return False
            # Consistency: if ok true, status < 400; if status >=400 then ok false
            if e["ok"] and e["http_status"] >= 400:
                return False
            if (not e["ok"]) and e["http_status"] < 400:
                # allow e.g., 0 or <100? We'll accept 0 as failure.
                if e["http_status"] >= 100:
                    return False
            return True

        if len(fetch_log) == 0:
            scores["fetch_log_structure"] = 0.0
        else:
            valid_count = sum(1 for e in fetch_log if _valid_entry(e))
            scores["fetch_log_structure"] = valid_count / len(fetch_log)

        # Coverage: at least one entry per (school, page_type)
        if schools:
            covered = 0
            for sch in schools:
                have_staff = any(isinstance(e, dict) and e.get("school") == sch and e.get("page_type") == "staff" for e in fetch_log)
                have_recruit = any(isinstance(e, dict) and e.get("school") == sch and e.get("page_type") == "recruiting" for e in fetch_log)
                if have_staff and have_recruit:
                    covered += 1
            scores["fetch_log_coverage_by_school"] = covered / len(schools)
    else:
        scores["fetch_log_structure"] = 0.0
        scores["fetch_log_coverage_by_school"] = 0.0

    # 3) contacts.csv
    contacts_path = workspace / "output" / "contacts.csv"
    contacts_rows, contacts_err = _read_csv_dicts(contacts_path)
    contacts_rows = contacts_rows or []
    if contacts_err is None and contacts_rows is not None:
        # Validate columns
        required_cols = ["school", "contact_name", "role", "email", "source_page_type", "source_file"]
        # Determine header from first row keys if available
        cols_ok = False
        try:
            with contacts_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                header_lower = [h.strip().lower() for h in header]
                cols_ok = all(c in header_lower for c in required_cols)
        except Exception:
            cols_ok = False
        # Validate rows
        rows_valid = True
        allowed_roles = {"head coach", "assistant", "recruiting", "unknown"}
        allowed_page_types = {"staff", "recruiting"}
        for r in contacts_rows:
            if not all(k in r for k in required_cols):
                rows_valid = False
                break
            if r.get("school", "").strip() not in schools:
                rows_valid = False
                break
            if r.get("role", "").strip().lower() not in allowed_roles:
                rows_valid = False
                break
            if r.get("source_page_type", "").strip() not in allowed_page_types:
                rows_valid = False
                break
            email = r.get("email", "").strip()
            if email and "@" not in email:
                rows_valid = False
                break
            sf = r.get("source_file", "").strip()
            if not sf:
                rows_valid = False
                break
        scores["contacts_csv_structure"] = 1.0 if (cols_ok and rows_valid) else 0.0

        # Per-school limit <= 3
        if schools:
            ok_count = 0
            for sch in schools:
                count = sum(1 for r in contacts_rows if r.get("school", "").strip() == sch)
                if count <= 3:
                    ok_count += 1
            scores["contacts_per_school_limit"] = ok_count / len(schools)
        else:
            scores["contacts_per_school_limit"] = 0.0

        # Source files exist and email appears in the referenced text file
        if contacts_rows:
            valid_refs = 0
            total_refs = 0
            for r in contacts_rows:
                sf_rel = r.get("source_file", "").strip()
                sp_type = r.get("source_page_type", "").strip()
                sch = r.get("school", "").strip()
                email = r.get("email", "").strip()
                total_refs += 1
                # Relative path check
                sf_path = Path(sf_rel)
                if sf_path.is_absolute():
                    continue
                sf_abs = (workspace / sf_path).resolve()
                # Must exist
                if not sf_abs.exists():
                    continue
                # Must be under output/webpages/text
                try:
                    if "output" not in sf_abs.parts or "webpages" not in sf_abs.parts:
                        continue
                except Exception:
                    continue
                # Must end with correct suffix
                if sp_type == "staff" and not sf_abs.name.endswith("_staff.txt"):
                    continue
                if sp_type == "recruiting" and not sf_abs.name.endswith("_recruiting.txt"):
                    continue
                # Must belong to the same school filename prefix
                if not sf_abs.name.startswith(f"{sch}_"):
                    continue
                # Check that the email appears in the referenced text file (case-insensitive)
                content, _ = _read_text(sf_abs)
                if content is None:
                    continue
                if email and (email.lower() not in content.lower()):
                    continue
                valid_refs += 1
            if total_refs > 0:
                scores["contacts_source_files_exist_and_match"] = valid_refs / total_refs
            else:
                # Allow zero contacts; in that case, consider this check neutral -> 1.0 if no contacts to validate?
                scores["contacts_source_files_exist_and_match"] = 1.0
        else:
            scores["contacts_source_files_exist_and_match"] = 1.0
    else:
        scores["contacts_csv_structure"] = 0.0
        scores["contacts_per_school_limit"] = 0.0
        scores["contacts_source_files_exist_and_match"] = 0.0

    # 4) crosscheck_report.json
    cross_path = workspace / "output" / "crosscheck_report.json"
    cross_data, cross_err = _read_json(cross_path)
    if isinstance(cross_data, list):
        struct_ok = True
        for item in cross_data:
            if not isinstance(item, dict):
                struct_ok = False
                break
            if "school" not in item or "email" not in item or "matched" not in item or "matched_file" not in item:
                struct_ok = False
                break
            if not isinstance(item["school"], str) or not isinstance(item["email"], str):
                struct_ok = False
                break
            if not isinstance(item["matched"], bool):
                struct_ok = False
                break
            if not isinstance(item["matched_file"], str):
                struct_ok = False
                break
        scores["crosscheck_report_structure"] = 1.0 if struct_ok else 0.0

        # Correctness vs recomputation for each contact entry
        contacts = contacts_rows if contacts_rows is not None else []
        if contacts:
            correct = 0
            total = 0
            # Build fast lookup for crosscheck entries by (school, email)
            index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            for item in cross_data:
                sch = item.get("school", "")
                em = item.get("email", "")
                key = (sch, em)
                index.setdefault(key, []).append(item)
            for r in contacts:
                sch = r.get("school", "").strip()
                em = r.get("email", "").strip()
                if not sch or not em:
                    continue
                total += 1
                recomputed_match, matched_file = _recompute_email_match(workspace, sch, em)
                # Find at least one record for (sch, em)
                items = index.get((sch, em), [])
                if not items:
                    # Missing crosscheck entry
                    continue
                # Consider it correct if any entry matches recomputed result and file path consistency
                found_correct = False
                for item in items:
                    if bool(item.get("matched")) != recomputed_match:
                        continue
                    if recomputed_match:
                        mf = item.get("matched_file", "")
                        if not mf:
                            continue
                        mf_path = Path(mf)
                        if not mf_path.is_absolute():
                            mf_path = (workspace / mf_path).resolve()
                        if not mf_path.exists():
                            continue
                        # Ensure the matched file actually contains the email
                        content, _ = _read_text(mf_path)
                        if content and (em.lower() in content.lower()):
                            found_correct = True
                            break
                    else:
                        # matched False; matched_file should be empty or non-existent
                        mf = item.get("matched_file", "")
                        if mf:
                            # If provided, ensure it does not exist
                            mf_path = Path(mf)
                            if mf_path.is_absolute():
                                # absolute provided; if exists then inconsistent
                                if mf_path.exists():
                                    continue
                            else:
                                if (workspace / mf_path).exists():
                                    continue
                        found_correct = True
                        break
                if found_correct:
                    correct += 1
            scores["crosscheck_correctness_vs_recomputation"] = (correct / total) if total > 0 else 1.0
        else:
            # No contacts -> nothing to crosscheck; consider correct
            scores["crosscheck_correctness_vs_recomputation"] = 1.0
    else:
        scores["crosscheck_report_structure"] = 0.0
        scores["crosscheck_correctness_vs_recomputation"] = 0.0

    # 5) email drafts checks
    if schools:
        present_count = 0
        subject_ok = 0
        to_matches = 0
        body_ok = 0
        unknown_questionnaire_ok = 0
        # Cache contacts for ordering: first occurrence per school
        contacts_for_first: Dict[str, str] = {}
        for sch in schools:
            email = _find_first_contact_email_for_school(contacts_rows or [], sch)
            if email:
                contacts_for_first[sch] = email
        # Determine if recruiting link found per school to enforce questionnaire sentence when UNKNOWN
        recruiting_url_present: Dict[str, bool] = {}
        if isinstance(sources, dict):
            for sch in schools:
                try:
                    rec = sources.get(sch, {}).get("recruiting", {})
                except Exception:
                    rec = {}
                url = rec.get("url", "") if isinstance(rec, dict) else ""
                recruiting_url_present[sch] = bool(url)
        else:
            for sch in schools:
                recruiting_url_present[sch] = False

        highlights_link = ""
        try:
            highlights_link = profile.get("highlights", {}).get("hudl_link", "")
        except Exception:
            highlights_link = ""

        visit_windows = []
        try:
            visit_windows = list(profile.get("visit_windows", []))
        except Exception:
            visit_windows = []
        visit_substrings = []
        for w in visit_windows:
            if isinstance(w, str) and w:
                # We will accept either exact window string or any date part within
                visit_substrings.append(w)
                # Add start date as additional check
                parts = w.split(" to ")
                if parts:
                    visit_substrings.append(parts[0])

        for sch in schools:
            exp = _expected_files_for_school(sch, workspace)
            draft_path = exp["draft"]
            draft_text, err = _read_text(draft_path)
            if draft_text is None or not draft_text.strip():
                continue
            present_count += 1
            to_val, subject_val, body = _extract_header_and_body(draft_text)

            # Subject check
            expected_subject = f"[{sch}] {subject_suffix}"
            if subject_val == expected_subject:
                subject_ok += 1

            # To matches first contact or UNKNOWN
            first_email = contacts_for_first.get(sch)
            if first_email:
                if to_val == first_email:
                    to_matches += 1
            else:
                if to_val == "UNKNOWN":
                    to_matches += 1

            # Body checks: 5–8 sentences, contains highlights link, at least two stats,
            # mentions staff/recruit info, asks three specific questions with keywords, contains visit window, includes contact info.
            body_checks_pass = True
            # Sentence count
            sentences = _count_sentences(body)
            if not (5 <= sentences <= 8):
                body_checks_pass = False
            # Highlights link
            if highlights_link and (highlights_link not in body):
                body_checks_pass = False
            # Stats: look for at least two tokens or numeric values
            stats_tokens = {"ppg", "rpg", "apg", "spg", "fg", "3pt", "ft"}
            body_lower = body.lower()
            token_hits = sum(1 for t in stats_tokens if t in body_lower)
            # numeric values from profile
            numeric_values = []
            try:
                s25 = profile.get("stats_2025", {})
                if isinstance(s25, dict):
                    for k in ["ppg", "rpg", "apg", "spg", "fg_pct", "3pt_pct", "ft_pct"]:
                        v = s25.get(k, None)
                        if isinstance(v, float) or isinstance(v, int):
                            # include as plain, and with leading 0 removed for fractions
                            numeric_values.append(f"{v:.2f}".rstrip("0").rstrip("."))
                            numeric_values.append(str(v))
            except Exception:
                pass
            numeric_hits = 0
            for nv in set(numeric_values):
                if nv and nv in body:
                    numeric_hits += 1
            if (token_hits + numeric_hits) < 2:
                body_checks_pass = False
            # References staff/recruiting info
            if ("staff" not in body_lower) and ("recruit" not in body_lower):
                body_checks_pass = False
            # Questions: at least three question marks and keywords
            qmarks = body.count("?")
            if qmarks < 3:
                body_checks_pass = False
            if ("offer" not in body_lower) or (("role" not in body_lower) and ("fit" not in body_lower)):
                body_checks_pass = False
            # Visit window mention
            if visit_substrings:
                if not any(sub in body for sub in visit_substrings):
                    body_checks_pass = False
            # Contact info: player's email and phone
            contact_email = ""
            contact_phone = ""
            try:
                contact_email = profile.get("contact", {}).get("email", "")
                contact_phone = profile.get("contact", {}).get("phone", "")
            except Exception:
                pass
            if contact_email and (contact_email not in body):
                body_checks_pass = False
            if contact_phone and (contact_phone not in body):
                body_checks_pass = False

            if body_checks_pass:
                body_ok += 1

            # UNKNOWN questionnaire logic
            # If To is UNKNOWN and recruiting URL exists, body should include 'questionnaire' and 'submit'
            if to_val == "UNKNOWN" and recruiting_url_present.get(sch, False):
                if ("questionnaire" in body_lower) and ("submit" in body_lower or "submitted" in body_lower):
                    unknown_questionnaire_ok += 1
            elif to_val != "UNKNOWN":
                # Not applicable, count as pass for this school
                unknown_questionnaire_ok += 1
            else:
                # To UNKNOWN but no recruiting URL found -> still count as pass (requirement applies only if found such a link)
                unknown_questionnaire_ok += 1

        total_drafts_expected = len(schools)
        scores["email_drafts_present"] = (present_count / total_drafts_expected) if total_drafts_expected > 0 else 0.0
        scores["email_subject_format"] = (subject_ok / total_drafts_expected) if total_drafts_expected > 0 else 0.0
        scores["email_to_matches_contacts"] = (to_matches / total_drafts_expected) if total_drafts_expected > 0 else 0.0
        scores["email_body_includes_required_elements"] = (body_ok / total_drafts_expected) if total_drafts_expected > 0 else 0.0
        scores["email_unknown_questionnaire_logic"] = (unknown_questionnaire_ok / total_drafts_expected) if total_drafts_expected > 0 else 0.0
    else:
        scores["email_drafts_present"] = 0.0
        scores["email_subject_format"] = 0.0
        scores["email_to_matches_contacts"] = 0.0
        scores["email_body_includes_required_elements"] = 0.0
        scores["email_unknown_questionnaire_logic"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()