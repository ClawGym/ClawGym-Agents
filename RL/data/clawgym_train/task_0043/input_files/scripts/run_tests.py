import os
import io
import json
import unittest

def main():
    os.makedirs('out', exist_ok=True)
    loader = unittest.TestLoader()
    suite = loader.discover('tests')

    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)

    # Write human-readable test output
    with open('out/test_results.txt', 'w', encoding='utf-8') as f:
        f.write(stream.getvalue())

    # Build machine-readable summary
    summary = {
        'testsRun': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'wasSuccessful': result.wasSuccessful(),
        'failedTests': [
            {
                'test': str(test),
                'message': (err.splitlines()[-1] if err else '').strip()
            }
            for test, err in result.failures
        ],
        'errorTests': [
            {
                'test': str(test),
                'message': (err.splitlines()[-1] if err else '').strip()
            }
            for test, err in result.errors
        ]
    }

    with open('out/test_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

if __name__ == '__main__':
    main()
