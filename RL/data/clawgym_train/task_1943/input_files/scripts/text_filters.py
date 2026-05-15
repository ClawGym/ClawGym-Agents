# Text pre-processing helpers for keyword matching
import re

def clean_text(s: str) -> str:
    """
    Lowercase, remove punctuation to spaces, and collapse whitespace.
    """
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s: str):
    """
    Tokenize on single spaces after cleaning.
    """
    return s.split(" ")
