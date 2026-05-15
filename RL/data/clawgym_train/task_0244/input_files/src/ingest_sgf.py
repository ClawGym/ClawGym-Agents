import os
import yaml

def load_config(path="config/config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def read_notes(notes_path):
    # BUG: no explicit encoding; can fail on Burmese text
    with open(notes_path, "r") as f:
        return f.read()

def process_sgf_directory(cfg):
    input_dir = cfg.get("input_dir", "games")
    output_dir = cfg.get("output_dir", "out/records")
    notes_path = cfg.get("notes_file", "notes/chronicles.md")

    # BUG: output directory may not exist; currently no guard
    notes = read_notes(notes_path)

    for name in os.listdir(input_dir):
        if not name.lower().endswith(".sgf"):
            continue
        sgf_path = os.path.join(input_dir, name)
        if not os.path.exists(sgf_path):
            # Simulate a log line (in real run, a logger would emit this)
            print(f"ERROR FileNotFoundError: no such file {sgf_path}")
            continue
        # Placeholder for SGF processing using notes
        print(f"INFO processed {sgf_path} with notes length {len(notes)}")

if __name__ == "__main__":
    cfg = load_config()
    process_sgf_directory(cfg)
