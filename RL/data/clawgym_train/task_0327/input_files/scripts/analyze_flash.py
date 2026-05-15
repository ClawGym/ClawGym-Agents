# NOTE: This is a quick-and-dirty script for counting words per story.
# It needs refactoring and better features.

import os
import csv

# bad global state and naming on purpose
fileName = "data/flash_fiction.csv"

# naive word counter
def wc(t):
    c = 0
    for piece in t.split(" "):
        if piece.strip() != "":
            c += 1
    return c

# read csv into list
f = open(fileName, "r", encoding="utf-8")
reader = csv.DictReader(f)
rows = []
for r in reader:
    rows.append(r)
# forgot to use with-statement
f.close()

# ensure output dir
if not os.path.exists("output"):
    try:
        os.makedirs("output")
    except Exception as e:
        print("could not make output dir:", e)

# write counts in a simple format
try:
    out = open("output/word_counts.txt", "w", encoding="utf-8")
except Exception as e:
    print("err opening output:", e)
    out = open("word_counts.txt", "w", encoding="utf-8")

for i in range(0, len(rows)):
    rr = rows[i]
    text = rr.get("text", "")
    try:
        words = wc(text)
    except Exception as ex:
        print("ERR counting:", ex)
        words = 0
    line = str(rr.get("id", "")) + "," + rr.get("title", "") + ",words=" + str(words)
    out.write(line + "\n")

out.close()
print("done")
