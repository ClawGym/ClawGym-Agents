import os

def list_data_files():
    data_dir = 'data'
    try:
        return [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.endswith('.csv')]
    except FileNotFoundError:
        return []

if __name__ == '__main__':
    print('Legacy analyzer not in use.')
