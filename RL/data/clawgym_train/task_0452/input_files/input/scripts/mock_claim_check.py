import sys
import argparse

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))

def main():
    parser = argparse.ArgumentParser(description='Mock claim consistency checker')
    parser.add_argument('--id', required=True, type=str)
    parser.add_argument('--claim', required=True, type=str)
    parser.add_argument('--notes', required=True, type=str)
    args = parser.parse_args()

    cid = str(args.id)
    claim = (args.claim or '').lower()
    notes = (args.notes or '').lower()

    # Hard failure conditions
    if 'forgery' in claim or 'forgery' in notes:
        msg = f'conflicting claim: forgery flagged'
        sys.stderr.write(f'ERROR {cid} {msg}\n')
        sys.exit(2)
    if '[missing documents]' in notes:
        msg = 'missing documents in provenance'
        sys.stderr.write(f'ERROR {cid} {msg}\n')
        sys.exit(2)

    # Start with a neutral baseline
    score = 0.60

    # Positive signals
    if 'authenticated' in claim or 'authentic' in claim or 'original' in claim:
        score += 0.25

    # Negative soft signals
    if 'uncertain' in claim:
        score -= 0.20
    if 'restored' in notes:
        score -= 0.05

    # Replica/copy suppression (but not a hard error)
    if 'replica' in claim or 'copy' in claim or 'replica' in notes or 'copy' in notes:
        score = min(score, 0.30)

    score = clamp(score, 0.0, 1.0)
    sys.stdout.write(f'CONSISTENCY {cid} {score:.2f}\n')
    sys.exit(0)

if __name__ == '__main__':
    main()
