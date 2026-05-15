import os
import yaml
import requests
import hashlib
import numpy as np

# Load configuration
with open('input/config.yaml', 'r') as f:
    config = yaml.safe_load(f)


def download(url, dest):
    # Insecure: certificate verification disabled
    resp = requests.get(url, verify=False, timeout=30)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as out:
        out.write(resp.content)
    return dest


def file_md5(path):
    # Uses MD5 for integrity checks
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def transform(data):
    # Dynamic code execution controlled by config
    if config.get('allow_arbitrary_code'):
        fn = eval(config.get('transformation', 'lambda x: x'))
        return fn(data)
    return data


def process():
    for d in config.get('data', []):
        dest = os.path.join('data', 'raw', f"{d['dataset']}.csv")
        download(d['url'], dest)
        checksum = file_md5(dest)
        print('downloaded', dest, 'md5=', checksum)


if __name__ == '__main__':
    # No fixed random seed specified
    arr = np.random.rand(5)
    arr2 = transform(arr)
    process()
