#!/usr/bin/env python3
import os
import sys
import json
import glob
import csv

def eprint(*args):
    print(*args, file=sys.stderr)

def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()

def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else 'config/curriculum.json'
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        eprint(f"Failed to load config: {e}")
        return 2

    required = ['week_name', 'output_dir', 'news_dir', 'stories_dir', 'prompts_file', 'nights']
    for k in required:
        if k not in cfg:
            eprint(f"Missing required config key: {k}")
            return 2

    news_dir = cfg['news_dir']
    stories_dir = cfg['stories_dir']
    prompts_file = cfg['prompts_file']

    if not os.path.isdir(news_dir):
        eprint(f"News directory not found: {news_dir}")
        return 2
    if not os.path.isdir(stories_dir):
        eprint(f"Stories directory not found: {stories_dir}")
        return 2
    if not os.path.isfile(prompts_file):
        eprint(f"Prompts file not found: {prompts_file}")
        return 2

    news_files = sorted(glob.glob(os.path.join(news_dir, '*.txt')))
    story_files = sorted(glob.glob(os.path.join(stories_dir, '*.txt')))
    try:
        with open(prompts_file, 'r', encoding='utf-8') as f:
            prompts = [line.strip() for line in f if line.strip() != '']
    except Exception as e:
        eprint(f"Failed to read prompts: {e}")
        return 2

    if not news_files:
        eprint('No news .txt files found.')
        return 2
    if not story_files:
        eprint('No story .txt files found.')
        return 2
    if not prompts:
        eprint('No prompts found in prompts file.')
        return 2

    try:
        nights = int(cfg['nights'])
    except Exception:
        eprint("'nights' must be an integer in the config.")
        return 2

    out_dir = cfg['output_dir']
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"{cfg['week_name']}.md")
    idx_path = os.path.join(out_dir, f"{cfg['week_name']}_segments_index.csv")

    with open(md_path, 'w', encoding='utf-8') as md, open(idx_path, 'w', newline='', encoding='utf-8') as idx:
        writer = csv.writer(idx)
        writer.writerow(['day', 'segment_type', 'source_file'])
        for i in range(nights):
            day = i + 1
            news_path = news_files[i % len(news_files)]
            story_path = story_files[i % len(story_files)]
            prompt_text = prompts[i % len(prompts)]
            news_text = read_text(news_path)
            story_text = read_text(story_path)
            md.write(f"Day {day}\n")
            md.write(f"News: {news_text}\n")
            md.write(f"Story: {story_text}\n")
            md.write(f"Reflection: {prompt_text}\n\n")
            writer.writerow([day, 'news', os.path.relpath(news_path)])
            writer.writerow([day, 'story', os.path.relpath(story_path)])
            writer.writerow([day, 'reflection', f"prompts:{(i % len(prompts)) + 1}"])

    print(f"Wrote schedule to {md_path} and index to {idx_path}.")
    return 0

if __name__ == '__main__':
    sys.exit(main())
