import sys
import json
from pathlib import Path

INPUT_CURR = Path('input/bootcamp_curriculum.md')
INPUT_BG = Path('input/customer_background.md')
INPUT_ROLES = Path('input/target_roles.json')

def read_bullets(md_path):
    skills = set()
    with open(md_path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s.startswith('- '):
                skills.add(s[2:].strip())
    return skills

def load_roles(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    roles = data.get('roles', [])
    titles = [r.get('title', '') for r in roles]
    must_haves = set()
    for r in roles:
        for m in r.get('must_have', []):
            must_haves.add(m)
    return titles, must_haves

def main():
    if len(sys.argv) != 3:
        print('Usage: python tools/validate_plan.py <study_plan.md> <mentor_message.txt>')
        sys.exit(2)
    plan_path = Path(sys.argv[1])
    msg_path = Path(sys.argv[2])

    if not INPUT_CURR.exists() or not INPUT_BG.exists() or not INPUT_ROLES.exists():
        print('Missing required input files in input/.')
        sys.exit(1)

    if not plan_path.exists() or not msg_path.exists():
        print('Missing output files to validate.')
        sys.exit(1)

    curriculum_skills = read_bullets(INPUT_CURR)
    background_skills = read_bullets(INPUT_BG)
    role_titles, role_musts = load_roles(INPUT_ROLES)

    covered = curriculum_skills.union(background_skills)
    gap_skills = sorted([s for s in role_musts if s not in covered])

    plan_text = plan_path.read_text(encoding='utf-8')
    msg_text = msg_path.read_text(encoding='utf-8')

    ok = True

    # Check weeks
    weeks_ok = all(w in plan_text for w in [
        'Week 1', 'Week 2', 'Week 3', 'Week 4'
    ])
    print(f'Weeks present (1-4): {"OK" if weeks_ok else "MISSING"}')
    ok = ok and weeks_ok

    # Check role titles referenced
    roles_ok = all(title in plan_text for title in role_titles if title)
    print(f'References all role titles: {"OK" if roles_ok else "MISSING"}')
    ok = ok and roles_ok

    # Check all gap skills included in study plan
    gaps_in_plan = [g for g in gap_skills if g in plan_text]
    gaps_ok = len(gaps_in_plan) == len(gap_skills)
    print('Gap skills (must-have but not covered): ' + (', '.join(gap_skills) if gap_skills else '[none]'))
    print(f'All gap skills mentioned in plan: {"OK" if gaps_ok else "MISSING"}')
    ok = ok and gaps_ok

    # Mentor message checks
    msg_lower = msg_text.lower()
    asks_feedback = 'feedback' in msg_lower
    asks_resources = ('resource' in msg_lower) or ('recommendation' in msg_lower)
    gap_mentions_in_msg = {g for g in gap_skills if g in msg_text}
    msg_ok = asks_feedback and asks_resources and (len(gap_mentions_in_msg) >= 2)
    print(f"Mentor message asks for feedback: {'OK' if asks_feedback else 'NO'}")
    print(f"Mentor message asks for resources/recommendations: {'OK' if asks_resources else 'NO'}")
    print(f"Mentor message mentions >=2 gap skills (found {len(gap_mentions_in_msg)}): {'OK' if len(gap_mentions_in_msg) >= 2 else 'NO'}")
    if gap_skills:
        print('Gap skills mentioned in message: ' + (', '.join(sorted(gap_mentions_in_msg)) if gap_mentions_in_msg else '[none]'))
    ok = ok and msg_ok

    if ok:
        print('ALL CHECKS PASSED')
        sys.exit(0)
    else:
        print('VALIDATION FAILED')
        sys.exit(1)

if __name__ == '__main__':
    main()
