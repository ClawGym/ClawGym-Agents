import re
from typing import List

# TODO: Implement the functions below. Your build script should import and use them.
# Keep extraction logic here; do not hardcode languages or regexes in the main script.

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Matches formats like (413) 555-1234 or 413-555-1234
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}")
_TRANSLATION_HINTS = [
    "translation", "translate", "interpreter", "interpretation",
    "language access", "multilingual", "language line", "bilingual"
]


def extract_page_title(html: str) -> str:
    """Return the contents of the <title> tag, stripped of whitespace. Return empty string if not found."""
    # TODO: Implement
    match = _TITLE_RE.search(html or "")
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_emails(html: str) -> List[str]:
    """Return a de-duplicated list of email addresses found in the HTML."""
    # TODO: Implement
    emails = set(_EMAIL_RE.findall(html or ""))
    return sorted(emails)


def extract_phones(html: str) -> List[str]:
    """Return a de-duplicated list of phone numbers found in the HTML, normalized to trim extra spaces."""
    # TODO: Implement
    phones = set(p.strip() for p in _PHONE_RE.findall(html or ""))
    return sorted(phones)


def detect_languages(html: str, languages: List[str]) -> List[str]:
    """Return a list of languages (from the provided list) that appear in the HTML text (case-insensitive)."""
    # TODO: Implement
    text = (html or "").lower()
    found = []
    for lang in languages or []:
        if lang and lang.lower() in text:
            found.append(lang)
    return sorted(set(found), key=lambda x: found.index(x))


def has_translation_info(html: str) -> bool:
    """Return True if the HTML contains common translation/interpretation cues."""
    # TODO: Implement
    text = (html or "").lower()
    return any(hint in text for hint in _TRANSLATION_HINTS)


def infer_org_name_from_url(url: str) -> str:
    """Best-effort short org name from a URL's domain (e.g., doe.mass.edu -> "Massachusetts DOE"). Keep simple and deterministic.
    You may implement a simple rule: take the registrable domain (two rightmost labels) and uppercase the main label, e.g., "mass.edu" -> "MASS.EDU".
    """
    # TODO: Implement
    if not url:
        return ""
    try:
        domain = url.split("//", 1)[-1].split("/", 1)[0]
        parts = [p for p in domain.split("") if p]
    except Exception:
        parts = []
    domain = url.split("//", 1)[-1].split("/", 1)[0]
    labels = domain.split(".")
    short = ".".join(labels[-2:]) if len(labels) >= 2 else domain
    return short.upper()
