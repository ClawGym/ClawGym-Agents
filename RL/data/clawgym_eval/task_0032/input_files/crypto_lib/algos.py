import base64
import hashlib
import hmac
from typing import Dict, Tuple, Callable, List

# NOTE: This module intentionally includes a legacy RC4 implementation for demonstration/testing.
# The presence of RC4 should be detected by compliance tooling when FIPS mode is enabled.


def _hmac_tag(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def aes_256_gcm_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> str:
    """
    Simulated AES-256-GCM: returns token as base64(plaintext) + "." + HMAC-SHA256 tag over (plaintext||aad).
    This is NOT real AES, for validation-only in local dev.
    """
    pt_b64 = base64.b64encode(plaintext).decode("ascii")
    tag = _hmac_tag(key, plaintext + aad)
    return f"{pt_b64}.{tag}"


def aes_256_gcm_decrypt(key: bytes, token: str, aad: bytes = b"") -> bytes:
    try:
        pt_b64, tag_hex = token.split(".", 1)
    except ValueError:
        raise ValueError("Malformed token")
    plaintext = base64.b64decode(pt_b64.encode("ascii"))
    expected = _hmac_tag(key, plaintext + aad)
    if not hmac.compare_digest(tag_hex, expected):
        raise ValueError("Authentication failed")
    return plaintext


def rc4_encrypt(key: bytes, plaintext: bytes) -> str:
    """
    Toy RC4-like XOR stream (NOT secure). Returned as hex string.
    """
    keystream = (key * (len(plaintext) // len(key) + 1))[: len(plaintext)]
    ct = bytes([p ^ k for p, k in zip(plaintext, keystream)])
    return ct.hex()


def rc4_decrypt(key: bytes, ciphertext_hex: str) -> bytes:
    ct = bytes.fromhex(ciphertext_hex)
    keystream = (key * (len(ct) // len(key) + 1))[: len(ct)]
    pt = bytes([c ^ k for c, k in zip(ct, keystream)])
    return pt

# Map algorithm names to (encrypt, decrypt) callables
ALGO_IMPLS: Dict[str, Tuple[Callable[..., str], Callable[..., bytes]]] = {
    "AES-256-GCM": (lambda key, msg: aes_256_gcm_encrypt(key, msg, b""),
                     lambda key, token: aes_256_gcm_decrypt(key, token, b"")),
    "RC4": (lambda key, msg: rc4_encrypt(key, msg),
             lambda key, token: rc4_decrypt(key, token)),
}


def list_algorithms() -> List[str]:
    """Return the list of algorithm names supported by this package."""
    return sorted(ALGO_IMPLS.keys())


def encrypt(algorithm: str, key: str, message: str) -> str:
    if algorithm not in ALGO_IMPLS:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    enc_fn, _ = ALGO_IMPLS[algorithm]
    return enc_fn(key.encode("utf-8"), message.encode("utf-8"))


def decrypt(algorithm: str, key: str, token: str) -> str:
    if algorithm not in ALGO_IMPLS:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    _, dec_fn = ALGO_IMPLS[algorithm]
    out = dec_fn(key.encode("utf-8"), token)
    return out.decode("utf-8")
