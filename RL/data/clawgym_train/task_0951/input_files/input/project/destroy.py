#!/usr/bin/env python3
"""
DANGER: This file contains destructive command patterns for detection testing.
It demonstrates shell commands and Python functions that can irreversibly delete files.
DO NOT RUN.
"""

import os
import shutil
import subprocess
from pathlib import Path


def dangerous_cleanup_tmp():
    # Direct shell invocation with rm -rf pattern (highly dangerous)
    subprocess.run(["rm", "-rf", "/tmp/some_dir"], check=False)


def nuke_current_directory():
    # Another destructive pattern via shell
    cmd = "rm -rf ."
    os.system(cmd)


def wipe_path(path: Path):
    # Python-level recursive deletion
    shutil.rmtree(path, ignore_errors=True)


def main():
    # Intentionally left passive to avoid accidental execution.
    # The functions above reflect destructive patterns for static detection only.
    pass


if __name__ == "__main__":
    main()