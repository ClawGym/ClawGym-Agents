import sys
import hashlib
from pathlib import Path

# Ensure src/ is importable
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))

from hash_util import sha256_file, sha256_bytes  # noqa: E402


def test_sha256_file_matches_hashlib_sample1():
    p = BASE / 'input' / 'data' / 'sample1.txt'
    expected = hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha256_file(p) == expected


def test_sha256_file_matches_hashlib_sample2():
    p = BASE / 'input' / 'data' / 'sample2.txt'
    expected = hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha256_file(p) == expected


def test_sha256_bytes_matches_hashlib():
    data = b'case-data-001'
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_bytes(data) == expected
