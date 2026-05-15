# Messy script to summarize catalog
import csv, os, sys

path = 'input/data/catalog.csv'
outpath = 'output/summary.txt'

artists = {}
mediums = {}
minyear = None
maxyear = None
total = 0

if not os.path.exists(path):
    print("missing file", path)
else:
    f = open(path, encoding='utf-8')
    r = csv.DictReader(f)
    for row in r:
        total = total + 1
        a = row.get('artist','').strip()
        m = row.get('medium','').strip()
        y = row.get('year','').strip()
        if a in artists:
            artists[a] = artists[a] + 1
        else:
            artists[a] = 1
        mediums[m] = mediums.get(m,0) + 1
        try:
            yi = int(y)
            if minyear is None or yi < minyear:
                minyear = yi
            if maxyear is None or yi > maxyear:
                maxyear = yi
        except:
            pass
    f.close()
    if not os.path.exists('output'):
        os.makedirs('output')
    with open(outpath,'w', encoding='utf-8') as wf:
        wf.write("ARTISTS\n")
        for k,v in artists.items():
            wf.write(k+":"+str(v)+"\n")
        wf.write("MEDIUMS\n")
        for k,v in mediums.items():
            wf.write(k+":"+str(v)+"\n")
        wf.write("YEARS\n")
        wf.write(str(minyear)+"-"+str(maxyear)+" total="+str(total)+"\n")
    print("done", outpath)
