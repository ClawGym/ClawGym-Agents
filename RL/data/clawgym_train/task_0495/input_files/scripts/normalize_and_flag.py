import sys
import csv
import json
import argparse
from urllib.parse import urlparse

def main():
    parser = argparse.ArgumentParser(description="Normalize posts and flag known disinformation domains.")
    parser.add_argument("--posts", required=True, help="Path to posts CSV with columns: post_id,timestamp,user_id,url,text")
    parser.add_argument("--flagged", required=True, help="Path to JSON with key 'flagged_domains' listing domains to flag")
    args = parser.parse_args()

    try:
        with open(args.flagged, 'r', encoding='utf-8') as f:
            data = json.load(f)
            flagged_set = set([d.lower() for d in data.get("flagged_domains", [])])
    except Exception as e:
        sys.stderr.write(f"failed_to_load_flagged:{e}\n")
        sys.exit(1)

    seen = set()
    writer = csv.writer(sys.stdout)
    writer.writerow(["post_id", "timestamp", "user_id", "domain", "flagged"])  # flagged is 0/1

    try:
        with open(args.posts, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = str(row.get("post_id", "")).strip()
                if pid == "":
                    sys.stderr.write("malformed_row:missing_post_id\n")
                    continue
                if pid in seen:
                    sys.stderr.write(f"duplicate_post_id:{pid}\n")
                    continue
                seen.add(pid)

                url = (row.get("url") or "").strip()
                if "://" not in url or url == "":
                    sys.stderr.write(f"malformed_url:{pid}\n")
                    domain = ""
                    flagged = 0
                else:
                    parsed = urlparse(url)
                    domain = parsed.netloc.lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                    flagged = 1 if domain in flagged_set else 0

                writer.writerow([
                    pid,
                    (row.get("timestamp") or "").strip(),
                    (row.get("user_id") or "").strip(),
                    domain,
                    flagged
                ])
    except FileNotFoundError as e:
        sys.stderr.write(f"file_not_found:{e}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"processing_error:{e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
