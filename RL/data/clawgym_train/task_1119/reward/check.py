import json
import os
import re
import sys
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_skip_spans(text: str, start_marker: str = "[SKIP_START]", end_marker: str = "[SKIP_END]") -> List[Tuple[int, int]]:
    spans = []
    i = 0
    L = len(text)
    while i < L:
        s = text.find(start_marker, i)
        if s == -1:
            break
        e = text.find(end_marker, s + len(start_marker))
        if e == -1:
            e = L - len(end_marker)
        # span includes markers fully
        span_end = e + len(end_marker)
        spans.append((s, span_end))
        i = span_end
    return spans

def span_overlaps(span: Tuple[int, int], spans: List[Tuple[int, int]]) -> bool:
    a, b = span
    for s, e in spans:
        if a < e and b > s:
            return True
    return False

def detect_allowed_domains(spec: dict) -> List[str]:
    # Try common locations
    candidates: List[str] = []
    for key in ["allowed_email_domains", "allowedDomains"]:
        v = spec.get(key)
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            candidates.extend(v)
    email_obj = spec.get("email") or spec.get("emails") or {}
    for key in ["allowed_domains", "whitelist", "domains"]:
        v = email_obj.get(key)
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            candidates.extend(v)
    # Fallback: recursive scan for keys containing 'domain'
    def rec(obj):
        nonlocal candidates
        if isinstance(obj, dict):
            for k, v in obj.items():
                if "domain" in k.lower() and isinstance(v, list) and all(isinstance(x, str) for x in v):
                    candidates.extend(v)
                rec(v)
        elif isinstance(obj, list):
            for it in obj:
                rec(it)
    rec(spec)
    # Normalize unique lower-cased
    norm = []
    seen = set()
    for d in candidates:
        dl = d.strip().lower()
        if dl and dl not in seen:
            seen.add(dl)
            norm.append(dl)
    return norm

def build_expected_emails(text: str, skip_spans: List[Tuple[int, int]], allowed_domains: List[str]) -> List[Dict[str, Any]]:
    # Build pattern using allowed domains as alternatives if provided
    if allowed_domains:
        domain_alt = "|".join(re.escape(d) for d in sorted(allowed_domains, key=len, reverse=True))
        pattern = re.compile(rf'\b(?P<user>[A-Za-z0-9._%+\-]+)@(?P<domain>(?:{domain_alt}))\b', re.IGNORECASE | re.MULTILINE)
    else:
        pattern = re.compile(r'\b(?P<user>[A-Za-z0-9._%+\-]+)@(?P<domain>[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b', re.IGNORECASE | re.MULTILINE)
    results = []
    seen = set()
    for m in pattern.finditer(text):
        span = (m.start(), m.end())
        if span_overlaps(span, skip_spans):
            continue
        user = m.group("user")
        domain = m.group("domain")
        domain_l = domain.lower()
        if allowed_domains and domain_l not in [d.lower() for d in allowed_domains]:
            continue
        item = {
            "match": m.group(0),
            "index": m.start(),
            "namedGroups": {"user": user, "domain": domain}
        }
        key = (item["match"], item["index"])
        if key not in seen:
            seen.add(key)
            results.append(item)
    results.sort(key=lambda x: x["index"])
    return results

def build_expected_urls(text: str, skip_spans: List[Tuple[int, int]]) -> List[Dict[str, Any]]:
    # https URLs only. Capture host and optional path beginning with /
    # Avoid trailing punctuation by stopping at whitespace or certain delimiters
    url_re = re.compile(
        r'(?i)\bhttps://(?P<host>[A-Za-z0-9.-]+)(?P<path>/[^\s<>\)\]\}\"\']*)?',
        re.MULTILINE
    )
    results = []
    seen = set()
    for m in url_re.finditer(text):
        span = (m.start(), m.end())
        if span_overlaps(span, skip_spans):
            continue
        host = m.group("host")
        path = m.group("path")
        item = {
            "match": m.group(0),
            "index": m.start(),
            "namedGroups": {"host": host, "path": path if path is not None else None}
        }
        key = (item["match"], item["index"])
        if key not in seen:
            seen.add(key)
            results.append(item)
    results.sort(key=lambda x: x["index"])
    return results

def valid_date_parts(year: str, month: str, day: str) -> bool:
    try:
        y = int(year)
        m = int(month)
        d = int(day)
        datetime(y, m, d)
        return True
    except Exception:
        return False

def build_expected_order_ids(text: str, skip_spans: List[Tuple[int, int]]) -> List[Dict[str, Any]]:
    # Format: ORD-YYYYMMDD-CODE where CODE is 4+ uppercase alnum
    # Enforce valid dates
    oid_re = re.compile(r'\bORD\-(?P<year>\d{4})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12][0-9]|3[01])\-(?P<code>[A-Z0-9]{4,})\b')
    results = []
    seen = set()
    for m in oid_re.finditer(text):
        span = (m.start(), m.end())
        if span_overlaps(span, skip_spans):
            continue
        yr = m.group("year")
        mo = m.group("month")
        dy = m.group("day")
        code = m.group("code")
        if not valid_date_parts(yr, mo, dy):
            continue
        item = {
            "match": m.group(0),
            "index": m.start(),
            "namedGroups": {"year": yr, "month": mo, "day": dy, "code": code}
        }
        key = (item["match"], item["index"])
        if key not in seen:
            seen.add(key)
            results.append(item)
    results.sort(key=lambda x: x["index"])
    return results

def is_public_ipv4(a: int, b: int, c: int, d: int) -> bool:
    # Basic public rules: exclude private, loopback, link-local, multicast, all-zeros, broadcast
    if a == 10:
        return False
    if a == 127:
        return False
    if a == 0:
        return False
    if a == 192 and b == 168:
        return False
    if a == 172 and (16 <= b <= 31):
        return False
    if a == 169 and b == 254:
        return False
    if a >= 224:
        return False
    if a == 255 and b == 255 and c == 255 and d == 255:
        return False
    return True

def build_expected_ipv4(text: str, skip_spans: List[Tuple[int, int]]) -> List[Dict[str, Any]]:
    ip_re = re.compile(r'(?<!\d)(?P<a>\d{1,3})\.(?P<b>\d{1,3})\.(?P<c>\d{1,3})\.(?P<d>\d{1,3})(?!\d)')
    results = []
    seen = set()
    for m in ip_re.finditer(text):
        span = (m.start(), m.end())
        if span_overlaps(span, skip_spans):
            continue
        try:
            a = int(m.group("a")); b = int(m.group("b")); c = int(m.group("c")); d = int(m.group("d"))
        except Exception:
            continue
        if not (0 <= a <= 255 and 0 <= b <= 255 and 0 <= c <= 255 and 0 <= d <= 255):
            continue
        if not is_public_ipv4(a, b, c, d):
            continue
        item = {
            "match": m.group(0),
            "index": m.start(),
            "namedGroups": {"a": str(a), "b": str(b), "c": str(c), "d": str(d)}
        }
        key = (item["match"], item["index"])
        if key not in seen:
            seen.add(key)
            results.append(item)
    results.sort(key=lambda x: x["index"])
    return results

def normalize_phones_outside_skips(text: str, skip_spans: List[Tuple[int, int]]) -> str:
    # Build segments: outside and inside skips
    segments: List[Tuple[str, bool]] = []
    last = 0
    for s, e in sorted(skip_spans):
        if last < s:
            segments.append((text[last:s], True))   # outside, eligible for normalization
        segments.append((text[s:e], False))          # inside skip, keep as is
        last = e
    if last < len(text):
        segments.append((text[last:], True))

    # Phone regex: optional country code, various separators, capture 3-3-4
    phone_re = re.compile(
        r'(?<!\d)(?:\+?1[\s\-\.]?)?\(?\s*(?P<a>\d{3})\s*\)?[\s\-\.]?(?P<b>\d{3})[\s\-\.]?(?P<c>\d{4})(?!\d)'
    )

    out_parts: List[str] = []
    for seg, normalize in segments:
        if not normalize:
            out_parts.append(seg)
        else:
            def repl(m: re.Match) -> str:
                a = m.group("a")
                b = m.group("b")
                c = m.group("c")
                return f"+1-{a}-{b}-{c}"
            out_parts.append(phone_re.sub(repl, seg))
    return "".join(out_parts)

def load_matches_json(path: str) -> Optional[dict]:
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    required_keys = ["emails", "urls", "order_ids", "ipv4_public"]
    for k in required_keys:
        if k not in data or not isinstance(data[k], list):
            return None
        # Validate each entry structure
        for item in data[k]:
            if not isinstance(item, dict):
                return None
            if "match" not in item or "index" not in item or "namedGroups" not in item:
                return None
            if not isinstance(item["match"], str):
                return None
            if not isinstance(item["index"], int):
                return None
            if not isinstance(item["namedGroups"], dict):
                return None
    return data

def compare_matches(expected: dict, actual: dict) -> bool:
    # Exact equality by arrays content and order
    for key in ["emails", "urls", "order_ids", "ipv4_public"]:
        exp_list = expected.get(key, [])
        act_list = actual.get(key, [])
        if len(exp_list) != len(act_list):
            return False
        for e_item, a_item in zip(exp_list, act_list):
            if e_item != a_item:
                return False
    return True

def validate_patterns_used(path: str) -> Tuple[bool, Dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, dict):
        return (False, {})
    required_top = ["email", "url", "order_id", "ipv4_public", "phone_normalize"]
    for key in required_top:
        if key not in data or not isinstance(data[key], dict):
            return (False, {})
    def has_pattern_and_flags(obj: dict) -> bool:
        return isinstance(obj.get("pattern"), str) and isinstance(obj.get("flags"), str)
    if not (has_pattern_and_flags(data["email"]) and
            has_pattern_and_flags(data["url"]) and
            has_pattern_and_flags(data["order_id"]) and
            has_pattern_and_flags(data["ipv4_public"])):
        return (False, {})
    pn = data["phone_normalize"]
    if not (isinstance(pn.get("pattern"), str) and isinstance(pn.get("flags"), str) and isinstance(pn.get("replacement"), str)):
        return (False, {})
    # Light sanity: order_id pattern mentions named groups year, month, day, code
    p = data["order_id"].get("pattern", "")
    group_names_present = any(tok in p for tok in ["?<year", "?P<year"]) and any(tok in p for tok in ["?<month", "?P<month"]) and any(tok in p for tok in ["?<day", "?P<day"]) and any(tok in p for tok in ["?<code", "?P<code"])
    return (group_names_present, data)

def validate_order_id_explained(path: str) -> bool:
    txt = read_text(path)
    if txt is None:
        return False
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if len(lines) < 10:
        return False
    must_have = ["ORD-", "year", "month", "day", "code"]
    for token in must_have:
        if token not in txt:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {
        "has_output_dir": False,
        "matches_json_valid": False,
        "matches_equal_expected": False,
        "normalized_txt_valid": False,
        "normalized_txt_exact": False,
        "patterns_used_valid": False,
        "order_id_explained_ok": False
    }

    # Verify output dir exists
    if os.path.isdir(output_dir):
        checks["has_output_dir"] = True

    specs_path = os.path.join(input_dir, "specs.json")
    records_path = os.path.join(input_dir, "records.txt")
    specs = read_json(specs_path) or {}
    records = read_text(records_path) or ""

    # Determine skip markers
    skip_cfg = {}
    if isinstance(specs.get("skip_markers"), dict):
        skip_cfg = specs.get("skip_markers") or {}
    skip_start = skip_cfg.get("start", "[SKIP_START]")
    skip_end = skip_cfg.get("end", "[SKIP_END]")

    skip_spans = find_skip_spans(records, skip_start, skip_end)
    allowed_domains = detect_allowed_domains(specs)

    # Build expected matches
    expected = {
        "emails": build_expected_emails(records, skip_spans, allowed_domains),
        "urls": build_expected_urls(records, skip_spans),
        "order_ids": build_expected_order_ids(records, skip_spans),
        "ipv4_public": build_expected_ipv4(records, skip_spans),
    }

    # Validate matches.json
    matches_path = os.path.join(output_dir, "matches.json")
    actual_matches = load_matches_json(matches_path)
    if actual_matches is not None:
        checks["matches_json_valid"] = True
        if compare_matches(expected, actual_matches):
            checks["matches_equal_expected"] = True

    # Validate normalized.txt
    normalized_path = os.path.join(output_dir, "normalized.txt")
    actual_normalized = read_text(normalized_path)
    if actual_normalized is not None:
        checks["normalized_txt_valid"] = True
        expected_normalized = normalize_phones_outside_skips(records, skip_spans)
        if actual_normalized == expected_normalized:
            checks["normalized_txt_exact"] = True

    # Validate patterns_used.json
    patterns_path = os.path.join(output_dir, "patterns_used.json")
    patterns_ok, _ = validate_patterns_used(patterns_path)
    if patterns_ok:
        checks["patterns_used_valid"] = True

    # Validate order_id_regex_explained.md
    explained_path = os.path.join(output_dir, "order_id_regex_explained.md")
    if validate_order_id_explained(explained_path):
        checks["order_id_explained_ok"] = True

    # Compute reward: no-op baseline -> 0.0 if missing outputs
    reward = 0.0
    # Weights
    w_extract = 0.5
    w_normalize = 0.3
    w_patterns = 0.1
    w_explain = 0.1

    if checks["matches_json_valid"] and checks["matches_equal_expected"]:
        reward += w_extract
    if checks["normalized_txt_valid"] and checks["normalized_txt_exact"]:
        reward += w_normalize
    if checks["patterns_used_valid"]:
        reward += w_patterns
    if checks["order_id_explained_ok"]:
        reward += w_explain

    # If output dir missing or nothing produced, keep reward at 0.0
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()