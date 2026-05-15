import argparse
import csv
import json
import math
import os
import sys


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_tracks(path, track_col, duration_col):
    tracks = []
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Will raise KeyError if the expected columns are missing.
            name = row[track_col]
            length = float(row[duration_col])
            tracks.append((name, length))
    return tracks


def distribute_sessions(lengths, total_sessions):
    total_len = sum(lengths)
    if total_len <= 0:
        return [0] * len(lengths)
    if total_sessions <= 0:
        return [0] * len(lengths)

    shares = [(ln / total_len) * total_sessions for ln in lengths]
    floors = [math.floor(s) for s in shares]
    remainders = [s - math.floor(s) for s in shares]

    # Enforce at least one session per track
    sessions = [max(1, int(fl)) for fl in floors]
    used = sum(sessions)

    # If we overshoot, reduce sessions from tracks with the smallest remainder (but keep at least 1)
    while used > total_sessions:
        candidates = [i for i in range(len(sessions)) if sessions[i] > 1]
        if not candidates:
            break
        i_min = min(candidates, key=lambda i: remainders[i])
        sessions[i_min] -= 1
        used -= 1

    # Distribute any leftover to tracks with the largest remainders
    while used < total_sessions:
        i_max = max(range(len(sessions)), key=lambda i: remainders[i])
        sessions[i_max] += 1
        used += 1
        # Avoid repeatedly selecting the same track
        remainders[i_max] = 0.0

    return sessions


def write_plan(out_path, tracks, per_session_minutes, sessions):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['track_name', 'planned_sessions', 'session_minutes', 'total_minutes'])
        for (name, _length), s in zip(tracks, sessions):
            writer.writerow([name, s, per_session_minutes, s * per_session_minutes])


def main():
    parser = argparse.ArgumentParser(description='Build a simple practice plan based on track lengths and config settings.')
    parser.add_argument('--input', required=True, help='Path to input CSV with track data')
    parser.add_argument('--config', required=True, help='Path to JSON config')
    parser.add_argument('--out', required=True, help='Path to write the practice plan CSV')
    args = parser.parse_args()

    cfg = load_config(args.config)

    try:
        track_col = cfg['track_name_column']
        # BUG: The script ignores the config and hardcodes the wrong duration column name.
        # It should read from cfg['duration_column'] but currently uses a hardcoded value.
        duration_col = 'duration_s'  # <-- This causes a KeyError with the provided input.
        per_session_minutes = int(cfg['per_session_minutes'])
        practice_minutes = int(cfg['practice_minutes'])
    except KeyError as e:
        print(f"Missing config key: {e}", file=sys.stderr)
        sys.exit(2)

    if per_session_minutes <= 0 or practice_minutes <= 0:
        print('per_session_minutes and practice_minutes must be positive integers', file=sys.stderr)
        sys.exit(2)

    if practice_minutes % per_session_minutes != 0:
        print('practice_minutes must be divisible by per_session_minutes', file=sys.stderr)
        sys.exit(2)

    total_sessions = practice_minutes // per_session_minutes

    try:
        tracks = read_tracks(args.input, track_col, duration_col)
    except Exception as e:
        print(f'Failed to read tracks: {e}', file=sys.stderr)
        # Re-raise to show full stack trace for debugging
        raise

    lengths = [ln for _name, ln in tracks]
    sessions = distribute_sessions(lengths, total_sessions)

    write_plan(args.out, tracks, per_session_minutes, sessions)
    print(f'Wrote plan to {args.out}')


if __name__ == '__main__':
    main()
