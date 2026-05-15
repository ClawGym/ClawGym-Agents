import os
import yaml

# Minimal archiver core (non-recursive). Reads config/archiver.yaml and filters by file extension.
# NOTE: When case_sensitive is True, extensions must match exactly as listed.

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def list_candidates(src, exts, case_sensitive=True):
    names = []
    allowed = exts[:]
    if not case_sensitive:
        allowed = [e.lower() for e in allowed]
    for name in os.listdir(src):
        full = os.path.join(src, name)
        if os.path.isfile(full):
            ext = os.path.splitext(name)[1]
            if not case_sensitive:
                ext = ext.lower()
            if ext in allowed:
                names.append(name)
    return names

def main():
    conf = load_config('config/archiver.yaml')
    src = conf['source_dir']
    dst = conf['archive_dir']
    exts = conf.get('allowed_extensions', [])
    case = conf.get('case_sensitive', True)
    print(f"Loaded config: source_dir={src} archive_dir={dst} allowed_extensions={exts} case_sensitive={case}")
    cand = list_candidates(src, exts, case)
    if cand:
        print(f"Would archive {len(cand)} file(s): {cand}")
    else:
        print("Found 0 candidate files; nothing to archive")

if __name__ == '__main__':
    main()
