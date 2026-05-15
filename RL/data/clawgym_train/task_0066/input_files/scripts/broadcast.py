import json
import sys

CITY = "Metropolis"

# NOTE: This script is intentionally rough for review.
# - Duplicated logic (format_message / fmt_message)
# - Shouting tone and excessive punctuation in user-visible text
# - Fragile field access causes a crash on missing keys
# - Minimal argument handling


def format_message(item):
    # Loud, duplicative, and not resilient to missing fields
    return "LISTEN UP, {}! {}!!! {} -- ACT NOW: {}!!!".format(
        CITY.upper(),
        item.get("title", "UPDATE").upper(),
        item["body"],
        item["call_to_action"].upper(),
    )


def fmt_message(item):
    # Duplicate logic that wraps format_message without adding value
    msg = format_message(item)
    return msg


def process(path, out_path, mode="loud"):
    f = open(path)
    data = json.load(f)
    f.close()
    out = []
    for i in range(0, len(data)):
        it = data[i]
        if mode == "loud":
            out.append(fmt_message(it))
        else:
            out.append(format_message(it))
    with open(out_path, "w") as o:
        for m in out:
            o.write(m + "\n")
    print("BROADCAST COMPLETE!!! {} messages sent!!!".format(len(out)))


if __name__ == "__main__":
    # expects: python scripts/broadcast.py input.json output.txt
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/messages.json"
    outp = sys.argv[2] if len(sys.argv) > 2 else "output/compiled_before.txt"
    try:
        process(inp, outp)
    except Exception as e:
        print("SOMETHING BAD HAPPENED!!!")
        print(e)
        sys.exit(1)
