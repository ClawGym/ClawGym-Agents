#!/usr/bin/env python3
import csv, yaml

def load_contacts(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def load_config(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)

def select_primary_recipients(config):
    # The notifier only uses primary_recipients for initial alerts.
    # backup_recipients are used only if escalation happens elsewhere.
    return config.get("primary_recipients", [])

def resolve_recipients(contacts, ids):
    by_id = {row["contact_id"]: row for row in contacts}
    resolved = []
    missing = []
    for cid in ids:
        row = by_id.get(cid)
        if row:
            resolved.append(row)
        else:
            missing.append(cid)
    return resolved, missing

if __name__ == "__main__":
    contacts = load_contacts("input/contacts.csv")
    config = load_config("input/alert_config.yaml")
    ids = select_primary_recipients(config)
    rows, missing = resolve_recipients(contacts, ids)
    print(f"Resolved {len(rows)} recipients")
    for cid in missing:
        print(f"MISSING contact_id: {cid}")
