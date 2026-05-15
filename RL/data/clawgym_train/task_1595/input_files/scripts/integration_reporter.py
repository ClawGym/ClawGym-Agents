# quick-and-dirty draft script (needs refactor)
import csv
import json

ISSUES = []  # global accumulator that should be removed during refactor

# NOTE: expects rooms.json and specs.csv in data/, but does not take CLI args yet

def load_rooms(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    rooms = {}
    for r in data.get('rooms', []):
        rooms[r['name']] = r
    return rooms


def main():
    rooms = load_rooms('data/rooms.json')  # hardcoded, refactor to CLI
    per_room = {}
    counts = {'rooms': len(rooms), 'items': 0}

    with open('data/specs.csv', 'r', encoding='utf-8') as f:  # hardcoded, refactor to CLI
        reader = csv.DictReader(f)
        for row in reader:
            counts['items'] += 1
            room = row.get('room', '').strip()
            per_room.setdefault(room, {'plumbing': 0, 'electrical': 0})
            system = (row.get('system') or '').strip().lower()

            if system == 'plumbing':
                per_room[room]['plumbing'] += 1
                finish = (row.get('fixture_finish') or '').strip().lower()
                expected = (rooms.get(room, {}).get('plumbing_finish') or '').strip().lower()
                if finish and expected and finish != expected:
                    ISSUES.append({
                        'room': room,
                        'item_id': row.get('item_id'),
                        'type': 'PLUMBING_FINISH_MISMATCH',
                        'detail': f"{finish} vs {expected}"
                    })

            elif system == 'electrical':
                per_room[room]['electrical'] += 1
                # BUG: wrong field name used here (should be 'faceplate_color')
                faceplate = (row.get('faceplate_colour') or '').strip().lower()
                expected_face = (rooms.get(room, {}).get('electrical_faceplate_color') or '').strip().lower()
                if faceplate and expected_face and faceplate != expected_face:
                    ISSUES.append({
                        'room': room,
                        'item_id': row.get('item_id'),
                        'type': 'FACEPLATE_COLOR_MISMATCH',
                        'detail': f"{faceplate} vs {expected_face}"
                    })
                req_gfci = ((row.get('requires_gfci') or '').strip().lower() == 'true')
                has_gfci = ((row.get('gfci') or '').strip().lower() == 'true')
                if req_gfci and not has_gfci:
                    ISSUES.append({
                        'room': room,
                        'item_id': row.get('item_id'),
                        'type': 'MISSING_GFCI',
                        'detail': 'requires GFCI but gfci=false/missing'
                    })
                mounting = (row.get('mounting') or '').strip().lower()
                allow_exposed = bool(rooms.get(room, {}).get('exposed_conduit', False))
                if mounting == 'exposed' and not allow_exposed:
                    ISSUES.append({
                        'room': room,
                        'item_id': row.get('item_id'),
                        'type': 'EXPOSED_CONDUIT_NOT_ALLOWED',
                        'detail': 'mounting=exposed where concealed is required'
                    })

    # Currently just prints; refactor to write files to an output directory and add a CLI
    print('rooms:', counts['rooms'])
    print('items:', counts['items'])
    for r, ct in per_room.items():
        print(r, ct)
    for issue in ISSUES:
        print(issue)
    print('TODO: write integration_report.md, action_items.md, status_summary.json, and client_update.md')


if __name__ == '__main__':
    main()
