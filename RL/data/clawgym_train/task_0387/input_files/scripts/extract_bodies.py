#!/usr/bin/env python3
import sys
import mailparser  # intentional: external dependency not allowed here


def main():
    import pathlib
    import csv
    in_dir = pathlib.Path("input/messages")
    out_dir = pathlib.Path("output/bodies")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for eml in in_dir.glob("*.eml"):
        mail = mailparser.parse_from_file(str(eml))
        msgid = mail.message_id or eml.stem
        body = mail.text_plain[0] if getattr(mail, "text_plain", None) else getattr(mail, "body", "")
        (out_dir / f"{msgid}.txt").write_text(body, encoding="utf-8")
        rows.append([msgid, mail.subject or "", (mail.from_[0][1] if mail.from_ else ""), len(body or "")])
    with open("output/summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["message_id", "subject", "from_email", "body_length"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
