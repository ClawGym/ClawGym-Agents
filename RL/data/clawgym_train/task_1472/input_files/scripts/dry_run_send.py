import argparse
import csv
import os
import sys


def classify_email(email: str):
    local, _, domain = email.partition('@')
    if not local or not domain:
        return ("550", "Invalid mailbox")
    # Explicit blocklist mimicking provider/domain policy
    if domain in {"blockedrock.com", "loudblock.net"}:
        return ("BLOCKED", "domain policy (blocked domain)")
    # Heuristic invalid address
    if "invalid" in local:
        return ("550", "Invalid mailbox")
    # Mailbox full (hard bounce)
    if domain in {"fullbox.com"}:
        return ("552", "Mailbox full")
    # Temporary failures (soft bounce)
    if domain in {"tempfail.com", "greylist.me"}:
        return ("450", "Mailbox busy, try later")
    # Otherwise pretend it's deliverable
    return ("OK", "")


def main():
    parser = argparse.ArgumentParser(description="Dry-run email sender for bounce analysis.")
    parser.add_argument("--message", required=True, help="Path to message body text file")
    parser.add_argument("--recipients", required=True, help="Path to recipients CSV (email,name,segment)")
    parser.add_argument("--log", default="logs/send.log", help="Path to write send log")
    args = parser.parse_args()

    # Load message file (not used in classification; included for realism)
    try:
        with open(args.message, "r", encoding="utf-8") as f:
            _ = f.read()
    except Exception as e:
        print(f"ERROR,READ,{args.message},{e}", file=sys.stderr)
        sys.exit(2)

    os.makedirs(os.path.dirname(args.log), exist_ok=True)

    total = 0
    sent = 0
    failed = 0

    try:
        with open(args.recipients, newline="", encoding="utf-8") as f_in, open(args.log, "w", encoding="utf-8") as f_log:
            reader = csv.DictReader(f_in)
            for row in reader:
                email = (row.get("email") or "").strip()
                total += 1
                code, reason = classify_email(email)
                if code == "OK":
                    line = f"SENT,{email}"
                    print(line)
                    f_log.write(line + "\n")
                    sent += 1
                else:
                    line = f"ERROR,{code},{email},{reason}"
                    print(line, file=sys.stderr)
                    f_log.write(line + "\n")
                    failed += 1
            summary = f"SUMMARY,sent={sent},failed={failed},total={total}"
            print(summary)
            f_log.write(summary + "\n")
    except FileNotFoundError as e:
        print(f"ERROR,READ,{args.recipients},{e}", file=sys.stderr)
        sys.exit(2)

    # Non-zero exit if any failures to make error analysis required
    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
