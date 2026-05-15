# A quick one-off script a colleague wrote to fetch WHO homepage and save it.
# I plan to build on this for clinic advisory memos, but it's brittle.
# Please refactor this into a small, testable module and a simple pipeline.

import urllib.request, os

URL = "https://www.who.int"  # TODO: make configurable?

def go():
    try:
        resp = urllib.request.urlopen(URL, timeout=4)
        html = resp.read()
        f = open("who.html","wb")
        f.write(html)
        f.close()
        print("saved", len(html), "bytes")
    except Exception as e:
        print("err", e)

if __name__ == "__main__":
    go()
