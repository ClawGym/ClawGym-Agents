import sys, json

def main():
    if len(sys.argv) != 2:
        print("ERROR: expected one argument: path to quotes.jsonl")
        sys.exit(1)
    path = sys.argv[1]
    try:
        f = open(path, 'r', encoding='utf-8')
    except Exception as e:
        print(f"ERROR: cannot open file '{path}' - {e}")
        sys.exit(1)
    required = ["quote_id", "text", "year", "category", "source"]
    valid_categories = {"Setback", "Comeback"}
    with f:
        for idx, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                print(f"ERROR: line {idx} - Empty line")
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                msg = str(e).splitlines()[0]
                print(f"ERROR: line {idx} - Malformed JSON ({msg})")
                continue
            missing = [k for k in required if k not in obj]
            if missing:
                qid = obj.get('quote_id', '?')
                print(f"ERROR: line {idx} - Missing fields: {', '.join(missing)} (quote_id={qid})")
                continue
            if obj["category"] not in valid_categories:
                print(f"ERROR: line {idx} - Invalid category '{obj['category']}' (quote_id={obj['quote_id']})")
                continue
            if not isinstance(obj["year"], int):
                print(f"ERROR: line {idx} - Year must be integer (quote_id={obj['quote_id']})")
                continue
            print(f"VALID: line {idx} - {obj['quote_id']} ({obj['category']} {obj['year']})")

if __name__ == "__main__":
    main()
