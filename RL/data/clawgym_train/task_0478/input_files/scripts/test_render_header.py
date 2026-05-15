#!/usr/bin/env python3
import json

def main():
    # Simulate a deterministic failure
    result = {
        'test_id': 'render_header',
        'status': 'fail',
        'message': 'Expected "Welcome" header, got "W3lcome"',
        'duration_ms': 7
    }
    print(json.dumps(result))

if __name__ == '__main__':
    main()
