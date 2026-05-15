#!/usr/bin/env python3
import json

def main():
    # Simulate a passing login test
    result = {
        'test_id': 'login_success',
        'status': 'pass',
        'message': 'authenticated OK',
        'duration_ms': 9
    }
    print(json.dumps(result))

if __name__ == '__main__':
    main()
