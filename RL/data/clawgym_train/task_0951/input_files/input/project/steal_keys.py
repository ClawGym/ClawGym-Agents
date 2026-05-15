#!/usr/bin/env python3
"""
WARNING: Diagnostic script that enumerates environment variables commonly used for API access
and attempts to read the local AWS credentials file. Do not use in production.
"""

import os
from pathlib import Path


def read_known_keys():
    # Common API key/token names intentionally listed here for detection tests
    candidates = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "SLACK_BOT_TOKEN",
    ]
    found = {}
    for name in candidates:
        val = os.environ.get(name)
        if val:
            # Store raw values in memory (printing masked to avoid leaking)
            found[name] = val
    return found


def read_aws_credentials():
    cred_path = Path.home() / ".aws" / "credentials"
    if cred_path.exists():
        try:
            return cred_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


def main():
    # Enumerate API-related environment variables
    secrets = read_known_keys()
    if secrets:
        print("Discovered potential API credentials:")
        for k, v in secrets.items():
            masked = (v[:4] + "..." + v[-2:]) if len(v) > 6 else "***"
            print(f"- {k}={masked}")
    else:
        print("No known API-related environment variables found.")

    # Attempt to read the AWS credentials file
    aws_creds = read_aws_credentials()
    if aws_creds:
        print("Found ~/.aws/credentials (content length only):", len(aws_creds))
    else:
        print("No AWS credentials file found or unreadable.")


if __name__ == "__main__":
    main()