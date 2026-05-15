import os
import json

# User-facing messages (to be rewritten for clarity and brevity)
START_MSG = "Starting the run now (this will maybe take a long time and it might do a bunch of things)."
DOWNLOAD_MSG = "About to grab some stuff from the web probably - fingers crossed!"
DONE_MSG = "All operations completed successfully (I think). Please look somewhere in the output possibly."

CONFIG_PATH = os.path.join("config", "settings.json")


def load_settings(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def main():
    settings = load_settings()
    output_dir = settings.get("output_dir", "output")
    print(START_MSG)
    ensure_dir(output_dir)

    # TODO: Validate that settings["rfc"] identifies the correct official source, id, and format
    # TODO: Download the official plaintext of RFC 8259 from the IETF RFC Editor
    #       Save it to os.path.join(output_dir, "raw", "rfc8259.txt") (create directories as needed)
    # TODO: Compute a summary (sha256, line_count, word_count, keyword_counts) and write output/summary.json
    # TODO: Rewrite the three user-facing messages above for clarity and brevity, and create
    #       output/messages_rewrite.md showing Before/After for each message

    # Placeholder artifact to keep the script runnable before implementation
    raw_dir = os.path.join(output_dir, "raw")
    ensure_dir(raw_dir)
    placeholder_path = os.path.join(output_dir, "placeholder.txt")
    with open(placeholder_path, "w", encoding="utf-8") as f:
        f.write("Replace this placeholder by implementing the download and summary.")

    print(DOWNLOAD_MSG)
    print(DONE_MSG)


if __name__ == "__main__":
    main()
