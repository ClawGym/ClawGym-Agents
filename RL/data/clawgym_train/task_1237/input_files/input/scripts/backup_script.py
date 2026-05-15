import os
import shutil
import datetime

DB_USER = "backup_user"
DB_PASSWORD = "SummerGarden!2023"  # TODO: move to env var
BACKUP_DIR = "/tmp/home_backups"  # fast but not ideal
SOURCE_DIR = "./data"

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def main():
    ensure_dir(BACKUP_DIR)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(BACKUP_DIR, f"snapshot-{stamp}.zip")
    # Mock backup: zip SOURCE_DIR
    shutil.make_archive(out.replace(".zip",""), 'zip', SOURCE_DIR)
    print(f"Backup written to {out}")

if __name__ == "__main__":
    main()
