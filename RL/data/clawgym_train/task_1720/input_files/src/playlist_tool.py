import csv, sys, os

DATA_FILE = 'input/songs.csv'

# very simple script to print top songs (by rating only)
# TODO: improve everything

def loadcsv(p):
    f = open(p, 'r')
    rdr = csv.DictReader(f)
    rows = []
    for r in rdr:
        rows.append(r)
    return rows


def best_songs():
    rows = loadcsv(DATA_FILE)
    # convert rating to float for sort
    for r in rows:
        try:
            r['rating'] = float(r['rating'])
        except:
            r['rating'] = 0
    rows.sort(key=lambda x: x['rating'], reverse=True)
    return rows[:5]


def top():
    # duplicate logic, returns same as best_songs
    return best_songs()


def main():
    songs = top()
    print("Top 5 songs by rating:")
    for s in songs:
        print(s['title'], s['artist'], s['rating'])

if __name__ == '__main__':
    main()
