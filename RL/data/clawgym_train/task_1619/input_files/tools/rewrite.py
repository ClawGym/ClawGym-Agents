import argparse
import json
import os
from typing import Dict

# Minimal rewrite stub. Update this if tests reveal non-compliance with the style guide.

def rewrite_message(record: Dict) -> Dict:
    # Currently a pass-through with basic trimming only.
    out = dict(record)
    body = out.get("body", "")
    out["body"] = body.strip()
    return out


def process(in_path: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(in_path, "r", encoding="utf-8") as fin, open(out_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rewritten = rewrite_message(record)
            # Ensure stable field order for readability
            ordered = {
                "id": rewritten.get("id"),
                "recipient_name": rewritten.get("recipient_name"),
                "sender_name": rewritten.get("sender_name"),
                "subject": rewritten.get("subject", ""),
                "body": rewritten.get("body", "")
            }
            fout.write(json.dumps(ordered, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Rewrite outreach messages for tone, clarity, and brevity.")
    parser.add_argument("--in", dest="in_path", required=True, help="Path to input JSONL drafts.")
    parser.add_argument("--out", dest="out_path", required=True, help="Path to output JSONL rewrites.")
    args = parser.parse_args()
    process(args.in_path, args.out_path)


if __name__ == "__main__":
    main()
