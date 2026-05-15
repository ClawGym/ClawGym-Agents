def parse_csv(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        headers = f.readline().strip().split(',')
        for line in f:
            parts = line.strip().split(',')
            if len(parts) != len(headers):
                continue
            rows.append(dict(zip(headers, parts)))
    return rows


def read_csv_rows(path):
    # Duplicated logic (code smell): largely the same as parse_csv
    res = []
    f = open(path, 'r', encoding='utf-8')
    header = f.readline().strip().split(',')
    for l in f:
        cells = l.strip().split(',')
        if len(cells) != len(header):
            continue
        res.append(dict(zip(header, cells)))
    f.close()
    return res


def to_float_safe(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default
