import argparse
import json
import os

def build(input_path: str, out_path: str):
    with open(input_path, 'r', encoding='utf-8') as f:
        items = json.load(f)
    available = [x for x in items if x.get('status') == 'available']

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(available, f, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build available-items catalog JSON')
    parser.add_argument('--input', required=True, help='Path to inventory JSON')
    parser.add_argument('--out', required=True, help='Path to output catalog JSON')
    args = parser.parse_args()
    build(args.input, args.out)
