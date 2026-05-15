#!/usr/bin/env bash
# Simulates sending an email; prints deterministic messages based on recipient.
# Usage: simulate_send.sh <recipient_email> <message_file_path>
set -euo pipefail
recipient="${1:-}"
msg_path="${2:-}"
if [[ -z "$recipient" || -z "$msg_path" ]]; then
  echo "ERROR: missing arguments" >&2
  exit 2
fi
if [[ ! -f "$msg_path" ]]; then
  echo "ERROR: message file not found" >&2
  exit 3
fi
# Check recipient rules
if [[ "$recipient" == *"bounce"* ]]; then
  echo "ERROR: mailbox full" >&2
  exit 1
fi
if [[ "$recipient" == *"invalid"* ]]; then
  echo "ERROR: recipient address invalid" >&2
  exit 1
fi
# Inspect message file size as a simple rule
size=$(wc -c < "$msg_path" | tr -d ' ')
if [[ "$size" -gt 4000 ]]; then
  echo "ERROR: message too long" >&2
  exit 1
fi
# Look for required headers in the message
if ! grep -q "^To: " "$msg_path"; then
  echo "ERROR: missing To header" >&2
  exit 1
fi
if ! grep -q "^Subject: " "$msg_path"; then
  echo "ERROR: missing Subject header" >&2
  exit 1
fi
echo "OK: queued for delivery (id=SIM12345)"
exit 0
