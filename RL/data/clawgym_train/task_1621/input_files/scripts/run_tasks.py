import os
import sys
import json
import argparse
import hashlib
from datetime import datetime
from urllib import request, error
from html.parser import HTMLParser

CONFIG_PATH = os.path.join('input', 'schedule.json')
DATA_DIR = os.path.join('workspace', 'data')
NOTES_DIR = os.path.join('workspace', 'notes')
LOGS_DIR = os.path.join('workspace', 'logs')

class TitleDescParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = None
        self.meta_description = None
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'title':
            self.in_title = True
        if tag.lower() == 'meta':
            attrs_dict = dict(attrs)
            # match name="description"
            if attrs_dict.get('name', '').lower() == 'description' and self.meta_description is None:
                self.meta_description = attrs_dict.get('content')
    def handle_endtag(self, tag):
        if tag.lower() == 'title':
            self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            # accumulate the first non-empty title
            text = (data or '').strip()
            if text:
                if self.title is None:
                    self.title = text
                else:
                    self.title += text


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(NOTES_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)


def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_job(cfg, name):
    for job in cfg.get('jobs', []):
        if job.get('name') == name:
            return job
    return None


def write_log(line):
    ensure_dirs()
    with open(os.path.join(LOGS_DIR, 'fetch.log'), 'a', encoding='utf-8') as f:
        f.write(line.rstrip('\n') + '\n')


def run_echo(job):
    msg = job.get('config', {}).get('message', '')
    print(msg)


def run_fetch_official_homepage(job):
    """
    Implement this job so that it:
    - Reads source_domain and page_path from job['config']
    - Downloads the HTML via HTTPS
    - Writes raw HTML to workspace/data/homepage_raw.html
    - Extracts <title> and meta description and writes a JSON record to workspace/data/homepage_meta.json
    - Appends a log entry to workspace/logs/fetch.log
    - Handles network errors gracefully by writing a JSON record with null fields where necessary
    Only use Python's standard library.
    """
    raise NotImplementedError('Implement fetch_official_homepage job here')


def dispatch(job):
    jtype = job.get('type')
    if jtype == 'echo':
        return run_echo(job)
    if jtype == 'fetch_official_homepage':
        return run_fetch_official_homepage(job)
    raise ValueError(f"Unknown job type: {jtype}")


def main():
    parser = argparse.ArgumentParser(description='Simple job runner using schedule.json')
    parser.add_argument('--run-once', dest='run_once', help='Run a single job by name and exit')
    args = parser.parse_args()

    cfg = load_config()

    if args.run_once:
        job = find_job(cfg, args.run_once)
        if not job:
            print(f"Job not found: {args.run_once}", file=sys.stderr)
            sys.exit(1)
        dispatch(job)
    else:
        # For simplicity, no continuous scheduler here.
        # The schedule lives in input/schedule.json and can be used by external orchestrators, or run with --run-once.
        print(json.dumps(cfg, indent=2))

if __name__ == '__main__':
    main()
