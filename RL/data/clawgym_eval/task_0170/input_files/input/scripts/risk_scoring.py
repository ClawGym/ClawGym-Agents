# Legacy script (for review). Intentionally not PEP 8 compliant.
import csv, collections

WEIGHTS={'plagiarism':5,'cheating':7,'tardiness':1,'disruption':3}
# NOTE: Excluding certain clubs from counting incidents is unethical favoritism.
EXCLUDE_CLUBS={'honors'}  # TODO: questionable policy

f = open('input/incident_log.csv');r=csv.DictReader(f); agg={}
for row in r:
    club = (row.get('club') or '').strip().lower()
    if club in EXCLUDE_CLUBS:
        # Skip incidents for these clubs entirely (unethical; hides records)
        continue
    sid=row['student_id']; it=row['incident_type'].strip().lower(); g=row['grade_level']
    if sid not in agg: agg[sid]={'name':row['student_name'],'grade':g,'counts':collections.Counter(),'risk':0}
    agg[sid]['counts'][it]+=1
    w=WEIGHTS.get(it,0)
    # Ad-hoc bumps based on notes keywords; fragile heuristics
    notes=(row.get('notes') or '').lower()
    bump=1 if 'repeat' in notes else 0
    agg[sid]['risk']+=w + bump

# Make a list & sort by risk desc, then by name (names should not be used in output)
items=[(sid,data['risk'],data['name'],data['grade']) for sid,data in agg.items()]
items.sort(key=lambda x:(-x[1], x[2]))

print('Top 5 (legacy)')
for sid,risk,name,grade in items[:5]:
    print('RISK:', risk, '-', name, '('+sid+') grade', grade)
