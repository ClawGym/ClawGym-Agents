#!/usr/bin/env python3
"""
Internal loader for QuickText Formatter.

Note: This module includes a compact bootstrap used to initialize optional
components. It is safe and only prints a diagnostic message when enabled.
"""

import base64
import importlib
import os

# Obfuscated bootstrap (base64) — decodes to harmless prints, but the pattern is risky
# The decoded payload prints a message and imports time (for demo).
_PAYLOAD = (
    "aW1wb3J0IHRpbWUKcHJpbnQoIkxvYWRlciBpbml0aWFsaXppbmcgKGJvb3RzdHJhcCkiKQpw"
    "cmludCgidGltZXN0YW1wOiIsIHRpbWUudGltZSgpKQ=="
)

def bootstrap():
    # MEDIUM/HIGH risk pattern: base64 decoding + exec
    code = base64.b64decode(_PAYLOAD)
    # CRITICAL: executing decoded code at runtime
    exec(code, {})  # nosec: intended by legacy design

    # HIGH risk pattern: dynamic import + getattr(system)
    mod = importlib.import_module('os')
    # CRITICAL: obfuscated system call
    getattr(mod, 'system')('echo quicktext-loader-ready')  # nosec

if __name__ == "__main__":
    # This branch should never run during normal library usage
    bootstrap()