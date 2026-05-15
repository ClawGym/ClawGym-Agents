import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _extract_first_number(text: str) -> Optional[float]:
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", text)
    if not m:
        return None
    val = m.group(0).replace(",", "")
    try:
        return float(val)
    except Exception:
        return None


def _parse_simple_yaml(yaml_text: str) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple mappings and nested mappings with scalar values.
    Supports:
    - Top-level mappings
    - Nested mappings indicated by indentation and trailing colon
    - Scalars: numbers, quoted or unquoted strings (no escape processing)
    """
    try:
        root: Dict[str, Any] = {}
        stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
        lines = yaml_text.splitlines()

        def to_scalar(v: str) -> Any:
            v = v.strip()
            if v == "":
                return ""
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                return v[1:-1]
            # Try int
            try:
                if re.match(r"^[+-]?\d+$", v):
                    return int(v)
            except Exception:
                pass
            # Try float
            try:
                if re.match(r"^[+-]?\d+\.\d+$", v):
                    return float(v)
            except Exception:
                pass
            # Booleans
            lv = v.lower()
            if lv in ("true", "false"):
                return lv == "true"
            return v

        for raw in lines:
            if not raw.strip():
                continue
            if raw.strip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            line = raw.strip()
            # Align stack to current indent
            while stack and indent < stack[-1][0]:
                stack.pop()
            current = stack[-1][1]
            if ":" in line:
                if line.endswith(":"):
                    key = line[:-1].strip()
                    new_map: Dict[str, Any] = {}
                    current[key] = new_map
                    stack.append((indent + 2, new_map))
                else:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val_scalar = to_scalar(val)
                    current[key] = val_scalar
            else:
                # unsupported line structure; fail parsing
                return None
        return root
    except Exception:
        return None


def _parse_contract_offer_md(md_text: str) -> Optional[Dict[str, Any]]:
    try:
        lines = md_text.splitlines()
        text = md_text
        # contract_version
        m_ver = re.search(r"^Offer Version:\s*(.+)$", text, re.MULTILINE)
        if not m_ver:
            return None
        contract_version = m_ver.group(1).strip()

        # advance_total
        m_adv = re.search(r"Advance:\s*\$?([\d,]+)", text)
        if not m_adv:
            return None
        advance_total = int(m_adv.group(1).replace(",", ""))

        # royalty_rate_initial
        m_rr = re.search(r"Royalty Rate:\s*([0-9]+)%", text)
        if not m_rr:
            return None
        royalty_rate_initial = int(m_rr.group(1)) / 100.0

        # escalated
        m_es = re.search(r"Royalty Escalator:\s*Increases to\s*([0-9]+)%\s*after cumulative\s*([\d,]+)\s*streams", text, re.IGNORECASE)
        if not m_es:
            return None
        royalty_rate_escalated = int(m_es.group(1)) / 100.0
        escalation_threshold_streams = int(m_es.group(2).replace(",", ""))

        # distribution fee
        m_df = re.search(r"Distributor Fee:\s*([0-9]+)%", text)
        if not m_df:
            return None
        distribution_fee_rate = int(m_df.group(1)) / 100.0

        # recoupment scope and cap
        m_rs = re.search(r"Recoupment Scope:\s*(.+)", text)
        if not m_rs:
            return None
        recoup_line = m_rs.group(1).strip()
        # Capture the whole sentence for scope up to first period if exists
        scope_sentence = recoup_line.split(".")[0].strip()
        recoupment_scope = scope_sentence
        m_cap = re.search(r"capped at\s*\$?([\d,]+)", recoup_line, re.IGNORECASE)
        if not m_cap:
            # Might appear later in same line or next; attempt across subsequent text
            after_idx = text.find(m_rs.group(0))
            trailing = text[after_idx: after_idx + 200]
            m_cap2 = re.search(r"capped at\s*\$?([\d,]+)", trailing, re.IGNORECASE)
            if not m_cap2:
                return None
            recoup_marketing_cap = int(m_cap2.group(1).replace(",", ""))
        else:
            recoup_marketing_cap = int(m_cap.group(1).replace(",", ""))

        # territory
        m_ter = re.search(r"Territory:\s*([A-Za-z\s\-]+)[\.\n]", text)
        if not m_ter:
            return None
        territory = m_ter.group(1).strip()

        # term albums and options
        m_term = re.search(r"Term:\s*One\s*\((\d+)\)\s*album,\s*plus\s*two\s*\((\d+)\)\s*option periods", text, re.IGNORECASE)
        if not m_term:
            # Fallback: generic numbers in parentheses
            m_term2 = re.search(r"Term:\s*.*\((\d+)\)\s*album.*\((\d+)\)\s*option", text, re.IGNORECASE)
            if not m_term2:
                return None
            term_albums = int(m_term2.group(1))
            option_periods = int(m_term2.group(2))
        else:
            term_albums = int(m_term.group(1))
            option_periods = int(m_term.group(2))

        # accounting period (first token or hyphenated phrase)
        m_acc = re.search(r"Accounting:\s*([^.]+)", text)
        if not m_acc:
            return None
        acc_phrase = m_acc.group(1).strip()
        # Normalize to first hyphenated word e.g., "Semi-annual"
        acc_match = re.match(r"([A-Za-z\-]+)", acc_phrase)
        accounting_period = acc_match.group(1) if acc_match else acc_phrase

        return {
            "advance_total": float(advance_total),
            "royalty_rate_initial": float(royalty_rate_initial),
            "royalty_rate_escalated": float(royalty_rate_escalated),
            "escalation_threshold_streams": int(escalation_threshold_streams),
            "recoup_marketing_cap": float(recoup_marketing_cap),
            "distribution_fee_rate": float(distribution_fee_rate),
            "term_albums": int(term_albums),
            "option_periods": int(option_periods),
            "accounting_period": accounting_period,
            "territory": territory,
            "recoupment_scope": recoupment_scope,
            "contract_version": contract_version,
        }
    except Exception:
        return None


def _compute_break_even(offer_terms: Dict[str, Any], assumptions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        advance_total = float(offer_terms["advance_total"])
        recoup_marketing_cap = float(offer_terms["recoup_marketing_cap"])
        royalty_rate_initial = float(offer_terms["royalty_rate_initial"])
        escalation_threshold_streams = int(offer_terms["escalation_threshold_streams"])
        per_stream_net_receipt = float(assumptions["per_stream_net_receipt"])
        base_monthly_streams = float(assumptions["base_monthly_streams"])
        monthly_growth_rate = float(assumptions["monthly_growth_rate"])
        marketing_spend_planned = float(assumptions["marketing_spend_planned"])

        recoupable_total_usd = advance_total + min(marketing_spend_planned, recoup_marketing_cap)
        artist_royalty_per_stream = royalty_rate_initial * per_stream_net_receipt
        if artist_royalty_per_stream <= 0:
            return None
        break_even_streams = int(math.ceil(recoupable_total_usd / artist_royalty_per_stream))
        escalation_applied = break_even_streams >= escalation_threshold_streams
        # months_to_recoup
        numerator = 1.0 + monthly_growth_rate * (break_even_streams / base_monthly_streams)
        if numerator <= 0 or (1.0 + monthly_growth_rate) <= 0:
            return None
        months_to_recoup = int(math.ceil(math.log(numerator) / math.log(1.0 + monthly_growth_rate)))

        return {
            "recoupable_total_usd": float(recoupable_total_usd),
            "artist_royalty_per_stream": float(artist_royalty_per_stream),
            "break_even_streams": int(break_even_streams),
            "escalation_applied": bool(escalation_applied),
            "months_to_recoup": int(months_to_recoup),
            "initial_royalty_rate": float(royalty_rate_initial),
            "per_stream_net_receipt": float(per_stream_net_receipt),
            "base_monthly_streams": float(base_monthly_streams),
            "monthly_growth_rate": float(monthly_growth_rate),
            "marketing_spend_planned": float(marketing_spend_planned),
            "contract_version": str(offer_terms.get("contract_version", "")),
        }
    except Exception:
        return None


def _find_section_lines(markdown_text: str, section_title: str, other_titles: List[str]) -> List[str]:
    lines = markdown_text.splitlines()
    found_idx = None
    # Case-insensitive search for section title line
    for i, ln in enumerate(lines):
        if re.search(rf"^\s*#*\s*{re.escape(section_title)}\s*[:\-]*\s*$", ln, re.IGNORECASE):
            found_idx = i
            break
    if found_idx is None:
        # try looser match
        for i, ln in enumerate(lines):
            if section_title.lower() in ln.lower():
                found_idx = i
                break
    if found_idx is None:
        return []
    # find end index: next occurrence of any other title
    end_idx = len(lines)
    for i in range(found_idx + 1, len(lines)):
        for t in other_titles:
            if re.search(rf"^\s*#*\s*{re.escape(t)}\s*[:\-]*\s*$", lines[i], re.IGNORECASE):
                end_idx = i
                break
        if end_idx != len(lines) and i >= end_idx:
            break
    section_lines = lines[found_idx + 1:end_idx]
    return section_lines


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        if re.match(r"^\s*([-*])\s+", ln):
            bullets.append(ln.strip())
    return bullets


def _contains_phrase(text: str, *words: str) -> bool:
    tl = text.lower()
    return all(w.lower() in tl for w in words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "offer_terms_file_exists_and_schema": 0.0,
        "offer_terms_values_match_contract": 0.0,
        "config_synced_values": 0.0,
        "config_status_ready": 0.0,
        "config_synced_version_match": 0.0,
        "break_even_file_exists_and_schema": 0.0,
        "break_even_values_correct": 0.0,
        "break_even_traceability_fields": 0.0,
        "summary_structure": 0.0,
        "summary_break_even_consistency": 0.0,
        "summary_open_questions_quality": 0.0,
        "manager_message_word_limit": 0.0,
        "manager_message_content_requirements": 0.0,
        "manager_message_financial_accuracy": 0.0,
    }

    # Load inputs
    contract_md_path = workspace / "input" / "contract_offer.md"
    assumptions_json_path = workspace / "input" / "assumptions.json"
    draft_message_path = workspace / "input" / "draft_message.txt"
    config_yaml_path = workspace / "config" / "financial_model.yaml"

    offer_terms_json_path = workspace / "outputs" / "offer_terms.json"
    break_even_json_path = workspace / "outputs" / "break_even_estimate.json"
    summary_md_path = workspace / "outputs" / "summary.md"
    manager_msg_path = workspace / "outputs" / "manager_message.txt"

    contract_md = _safe_read_text(contract_md_path) or ""
    parsed_contract = _parse_contract_offer_md(contract_md) if contract_md else None

    # Check offer_terms.json
    offer_terms = _safe_json_load(offer_terms_json_path)
    required_offer_fields = [
        "advance_total",
        "royalty_rate_initial",
        "royalty_rate_escalated",
        "escalation_threshold_streams",
        "recoup_marketing_cap",
        "distribution_fee_rate",
        "term_albums",
        "option_periods",
        "accounting_period",
        "territory",
        "recoupment_scope",
        "contract_version",
    ]
    if isinstance(offer_terms, dict):
        keys_ok = sorted(list(offer_terms.keys())) == sorted(required_offer_fields)
        types_ok = True
        try:
            # Type checks
            float(offer_terms["advance_total"])
            float(offer_terms["royalty_rate_initial"])
            float(offer_terms["royalty_rate_escalated"])
            int(offer_terms["escalation_threshold_streams"])
            float(offer_terms["recoup_marketing_cap"])
            float(offer_terms["distribution_fee_rate"])
            int(offer_terms["term_albums"])
            int(offer_terms["option_periods"])
            str(offer_terms["accounting_period"])
            str(offer_terms["territory"])
            str(offer_terms["recoupment_scope"])
            str(offer_terms["contract_version"])
        except Exception:
            types_ok = False
        if keys_ok and types_ok:
            scores["offer_terms_file_exists_and_schema"] = 1.0

    # Compare offer terms with contract parsing
    if parsed_contract and isinstance(offer_terms, dict):
        numeric_fields = [
            "advance_total",
            "royalty_rate_initial",
            "royalty_rate_escalated",
            "recoup_marketing_cap",
            "distribution_fee_rate",
        ]
        int_fields = ["escalation_threshold_streams", "term_albums", "option_periods"]
        numeric_match = all(_approx_equal(float(offer_terms.get(f)), float(parsed_contract.get(f))) for f in numeric_fields)
        int_match = all(int(offer_terms.get(f)) == int(parsed_contract.get(f)) for f in int_fields)
        # strings: accounting_period (case-insensitive), territory (case-insensitive)
        acc_match = str(offer_terms.get("accounting_period", "")).strip().lower() == str(parsed_contract.get("accounting_period", "")).strip().lower()
        terr_match = str(offer_terms.get("territory", "")).strip().lower() == str(parsed_contract.get("territory", "")).strip().lower()
        # recoupment scope: must contain "advances" and "approved marketing"
        rs = str(offer_terms.get("recoupment_scope", ""))
        recoup_scope_ok = ("advances" in rs.lower() and "approved" in rs.lower() and "marketing" in rs.lower())
        # contract version exact
        ver_match = str(offer_terms.get("contract_version", "")).strip() == str(parsed_contract.get("contract_version", "")).strip()

        if numeric_match and int_match and acc_match and terr_match and recoup_scope_ok and ver_match:
            scores["offer_terms_values_match_contract"] = 1.0

    # Check config YAML synced
    config_yaml_text = _safe_read_text(config_yaml_path) or ""
    config_data = _parse_simple_yaml(config_yaml_text) if config_yaml_text else None
    if isinstance(config_data, dict) and isinstance(offer_terms, dict):
        deal_terms = config_data.get("deal_terms")
        synced_ok = True
        if isinstance(deal_terms, dict):
            for f in required_offer_fields:
                if f in ("recoupment_scope", "contract_version"):
                    # These fields are not under deal_terms except recoupment_scope? The task states set deal_terms.* fields to match outputs/offer_terms.json values.
                    # All fields listed are in deal_terms.* in config except status and synced_from_contract_version.
                    # We'll map:
                    pass
            # Check each relevant numeric/string field under deal_terms
            checks = []
            for f in [
                "advance_total",
                "royalty_rate_initial",
                "royalty_rate_escalated",
                "escalation_threshold_streams",
                "recoup_marketing_cap",
                "distribution_fee_rate",
                "term_albums",
                "option_periods",
                "accounting_period",
                "territory",
                "recoupment_scope",
            ]:
                if f not in deal_terms:
                    synced_ok = False
                    break
                v_yaml = deal_terms.get(f)
                v_json = offer_terms.get(f)
                # normalize types for comparison
                if f in ("accounting_period", "territory", "recoupment_scope"):
                    if str(v_yaml).strip() != str(v_json).strip():
                        synced_ok = False
                        break
                elif f in ("escalation_threshold_streams", "term_albums", "option_periods"):
                    try:
                        if int(v_yaml) != int(v_json):
                            synced_ok = False
                            break
                    except Exception:
                        synced_ok = False
                        break
                else:
                    try:
                        if not _approx_equal(float(v_yaml), float(v_json)):
                            synced_ok = False
                            break
                    except Exception:
                        synced_ok = False
                        break
        else:
            synced_ok = False

        if synced_ok:
            scores["config_synced_values"] = 1.0

        # status ready
        status_val = config_data.get("status", "")
        if isinstance(status_val, str) and status_val.strip().lower() == "ready":
            scores["config_status_ready"] = 1.0

        # synced_from_contract_version
        if isinstance(offer_terms, dict):
            synced_version_val = config_data.get("synced_from_contract_version", "")
            if str(synced_version_val).strip() == str(offer_terms.get("contract_version", "")).strip():
                scores["config_synced_version_match"] = 1.0

    # Break-even JSON checks
    break_even = _safe_json_load(break_even_json_path)
    be_required_fields = [
        "recoupable_total_usd",
        "artist_royalty_per_stream",
        "break_even_streams",
        "escalation_applied",
        "months_to_recoup",
        "initial_royalty_rate",
        "per_stream_net_receipt",
        "base_monthly_streams",
        "monthly_growth_rate",
        "marketing_spend_planned",
        "contract_version",
    ]
    if isinstance(break_even, dict):
        schema_ok = sorted(list(break_even.keys())) == sorted(be_required_fields)
        types_ok = True
        try:
            float(break_even["recoupable_total_usd"])
            float(break_even["artist_royalty_per_stream"])
            int(break_even["break_even_streams"])
            isinstance(break_even["escalation_applied"], bool)
            int(break_even["months_to_recoup"])
            float(break_even["initial_royalty_rate"])
            float(break_even["per_stream_net_receipt"])
            float(break_even["base_monthly_streams"])
            float(break_even["monthly_growth_rate"])
            float(break_even["marketing_spend_planned"])
            str(break_even["contract_version"])
        except Exception:
            types_ok = False
        if schema_ok and types_ok:
            scores["break_even_file_exists_and_schema"] = 1.0

    # Break-even values correctness relative to inputs and offer_terms
    assumptions = _safe_json_load(assumptions_json_path) or {}
    if isinstance(offer_terms, dict) and isinstance(break_even, dict) and isinstance(assumptions, dict):
        computed = _compute_break_even(offer_terms, assumptions)
        if computed is not None:
            numeric_checks = [
                _approx_equal(float(break_even.get("recoupable_total_usd")), float(computed["recoupable_total_usd"]), tol=1e-6),
                _approx_equal(float(break_even.get("artist_royalty_per_stream")), float(computed["artist_royalty_per_stream"]), tol=1e-12),
                int(break_even.get("break_even_streams")) == int(computed["break_even_streams"]),
                int(break_even.get("months_to_recoup")) == int(computed["months_to_recoup"]),
            ]
            bool_check = bool(break_even.get("escalation_applied")) == bool(computed["escalation_applied"])
            if all(numeric_checks) and bool_check:
                scores["break_even_values_correct"] = 1.0
            # Traceability fields
            trace_checks = [
                _approx_equal(float(break_even.get("initial_royalty_rate")), float(offer_terms.get("royalty_rate_initial", 0.0))),
                _approx_equal(float(break_even.get("per_stream_net_receipt")), float(assumptions.get("per_stream_net_receipt", 0.0))),
                _approx_equal(float(break_even.get("base_monthly_streams")), float(assumptions.get("base_monthly_streams", 0.0))),
                _approx_equal(float(break_even.get("monthly_growth_rate")), float(assumptions.get("monthly_growth_rate", 0.0))),
                _approx_equal(float(break_even.get("marketing_spend_planned")), float(assumptions.get("marketing_spend_planned", 0.0))),
                str(break_even.get("contract_version", "")).strip() == str(offer_terms.get("contract_version", "")).strip(),
            ]
            if all(trace_checks):
                scores["break_even_traceability_fields"] = 1.0

    # Summary.md checks
    summary_md = _safe_read_text(summary_md_path) or ""
    if summary_md:
        # Structure: sections Key Terms, Break-even Estimate, Open Questions with bullets
        key_terms_lines = _find_section_lines(summary_md, "Key Terms", ["Break-even Estimate", "Open Questions"])
        break_even_lines = _find_section_lines(summary_md, "Break-even Estimate", ["Key Terms", "Open Questions"])
        open_q_lines = _find_section_lines(summary_md, "Open Questions", ["Key Terms", "Break-even Estimate"])
        key_terms_bullets = _extract_bullets(key_terms_lines)
        break_even_bullets = _extract_bullets(break_even_lines)
        open_q_bullets = _extract_bullets(open_q_lines)
        if key_terms_bullets and break_even_bullets and open_q_bullets:
            scores["summary_structure"] = 1.0

        # Break-even bullet values consistent with break_even JSON
        if isinstance(break_even, dict) and break_even_bullets:
            # We will look for bullets mentioning each key and extract numbers
            # recoupable_total_usd
            def find_bullet_value(bullets: List[str], keywords: List[str]) -> Optional[float]:
                for b in bullets:
                    if all(k.lower() in b.lower() for k in keywords):
                        num = _extract_first_number(b)
                        if num is not None:
                            return num
                return None

            be_expected_streams = int(break_even.get("break_even_streams")) if break_even else None
            be_expected_months = int(break_even.get("months_to_recoup")) if break_even else None
            be_expected_recoupable = float(break_even.get("recoupable_total_usd")) if break_even else None
            be_expected_royalty_per_stream = float(break_even.get("artist_royalty_per_stream")) if break_even else None
            be_expected_escalation = bool(break_even.get("escalation_applied")) if break_even else None

            val_recoupable = find_bullet_value(break_even_bullets, ["recoupable"])
            val_royalty_per_stream = find_bullet_value(break_even_bullets, ["royalty", "per", "stream"])
            val_streams = find_bullet_value(break_even_bullets, ["break-even", "streams"]) or find_bullet_value(break_even_bullets, ["break", "streams"])
            val_months = find_bullet_value(break_even_bullets, ["months"])
            # Escalation applied: look for true/false
            esc_line = None
            for b in break_even_bullets:
                if "escalat" in b.lower() or "threshold" in b.lower():
                    esc_line = b
                    break
            esc_ok = False
            if esc_line is not None:
                if be_expected_escalation:
                    esc_ok = ("true" in esc_line.lower() or "yes" in esc_line.lower() or "applies" in esc_line.lower())
                else:
                    esc_ok = ("false" in esc_line.lower() or "no" in esc_line.lower() or "does not apply" in esc_line.lower() or "not apply" in esc_line.lower())
            # Compare with tolerance for money and float
            comp_ok = True
            if val_recoupable is None or not _approx_equal(val_recoupable, be_expected_recoupable, tol=1e-2):
                comp_ok = False
            if val_royalty_per_stream is None or not _approx_equal(val_royalty_per_stream, be_expected_royalty_per_stream, tol=1e-6):
                comp_ok = False
            if val_streams is None or int(round(val_streams)) != be_expected_streams:
                comp_ok = False
            if val_months is None or int(round(val_months)) != be_expected_months:
                comp_ok = False
            if not esc_ok:
                comp_ok = False
            if comp_ok:
                scores["summary_break_even_consistency"] = 1.0

        # Open questions quality
        if open_q_bullets and len(open_q_bullets) >= 2:
            has_marketing_approval = any(_contains_phrase(b, "marketing") and ("approval" in b.lower() or "approve" in b.lower()) for b in open_q_bullets)
            has_escalator_or_accounting = any(("escalat" in b.lower() or "threshold" in b.lower() or "streams" in b.lower() or "accounting" in b.lower()) for b in open_q_bullets)
            if has_marketing_approval and has_escalator_or_accounting:
                scores["summary_open_questions_quality"] = 1.0

    # Manager message checks
    manager_text = _safe_read_text(manager_msg_path) or ""
    if manager_text:
        # Word count <= 150
        words = re.findall(r"\b\w+\b", manager_text)
        if len(words) <= 150:
            scores["manager_message_word_limit"] = 1.0

        # Content requirements: request a 20-minute call and note that a short internal summary is attached
        has_20_min = ("20-minute" in manager_text.lower()) or re.search(r"\b20\s*minute", manager_text.lower()) is not None
        has_call_request = has_20_min and ("call" in manager_text.lower() or "chat" in manager_text.lower() or "meet" in manager_text.lower())
        has_summary_attached = ("summary" in manager_text.lower() and ("attached" in manager_text.lower() or "enclosed" in manager_text.lower()))
        if has_call_request and has_summary_attached:
            scores["manager_message_content_requirements"] = 1.0

        # Financial accuracy and topics: mention advance, royalty rate, recoupment scope; marketing approval and accounting timing
        lower = manager_text.lower()
        mentions_advance = "advance" in lower and (re.search(r"\b75[, ]?000\b", lower) or "$75,000" in manager_text or "$75" in lower or "75k" in lower)
        mentions_royalty = "royalty" in lower and (("18%" in manager_text) or re.search(r"\b18\s*percent", lower) or re.search(r"\b0\.18\b", lower))
        mentions_recoupment = ("recoup" in lower)
        mentions_marketing_approval = ("marketing" in lower and ("approval" in lower or "approve" in lower))
        mentions_accounting = "accounting" in lower
        if mentions_advance and mentions_royalty and mentions_recoupment and mentions_marketing_approval and mentions_accounting:
            scores["manager_message_financial_accuracy"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()