import hashlib
from typing import Union
from pathlib import Path

def sha256_file(path: Union[str, Path], chunk_size: int = 131072) -> str:
    """Return the hex SHA-256 digest of a file's contents, read in chunks."""
    p = Path(path)
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()
