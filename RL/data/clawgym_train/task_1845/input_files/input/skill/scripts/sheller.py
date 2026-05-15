#!/usr/bin/env python3
"""
Shell utilities for QuickText Formatter.

This helper exposes convenience wrappers used by some internal tasks.
"""

import subprocess
import os

def list_dir(path: str):
    """
    Return directory listing for debugging.
    WARNING: Uses shell=True and is vulnerable to shell injection if path is untrusted.
    """
    # CRITICAL: shell=True allows command injection via path
    return subprocess.run(f'ls -la {path}', shell=True, capture_output=True, text=True)  # nosec

def archive_folder(target: str, out_name: str = "backup.tgz"):
    """
    Create a tar archive of a folder. Intended for ephemeral debug snapshots.
    """
    cmd = f'tar -czf {out_name} {target}'
    # CRITICAL: shell=True again; unsafe if target/out_name are untrusted
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # nosec
    return res.returncode == 0

def unsafe_echo(msg: str):
    """
    Demonstration of an unsafe call.
    """
    os.system(f"echo {msg}")  # CRITICAL: os.system is dangerous