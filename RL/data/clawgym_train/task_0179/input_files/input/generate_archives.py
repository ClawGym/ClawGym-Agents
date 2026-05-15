#!/usr/bin/env python3
import os
import shutil
import tarfile
import zipfile
import gzip
from io import BytesIO
from pathlib import Path


def ensure_clean_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def tar_add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes, mtime: int = 0):
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = mtime
    tar.addfile(info, BytesIO(data))


def write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def build_inner_tar_gz(tmp_dir: Path) -> Path:
    # Contents for inner.tar.gz:
    # - nested/data.csv
    # - nested/more/notes.txt.gz (single-file gzip of notes.txt)
    data_csv = b"id,value\n1,foo\n2,bar\n"
    notes_txt = b"These are nested notes.\n"
    notes_gz = gzip.compress(notes_txt)

    inner_path = tmp_dir / "inner.tar.gz"
    with tarfile.open(inner_path, "w:gz") as tar:
        tar_add_bytes(tar, "nested/data.csv", data_csv)
        tar_add_bytes(tar, "nested/more/notes.txt.gz", notes_gz)
    return inner_path


def build_extra_tgz(tmp_dir: Path) -> Path:
    # Contents for extra.tgz:
    # - alpha.txt
    alpha_txt = b"alpha\n"
    extra_path = tmp_dir / "extra.tgz"
    with tarfile.open(extra_path, "w:gz") as tar:
        tar_add_bytes(tar, "alpha.txt", alpha_txt)
    return extra_path


def build_pack_tar(tmp_dir: Path) -> Path:
    # Contents for pack.tar:
    # - leaf.txt
    leaf_txt = b"leaf\n"
    pack_path = tmp_dir / "pack.tar"
    with tarfile.open(pack_path, "w") as tar:
        tar_add_bytes(tar, "leaf.txt", leaf_txt)
    return pack_path


def build_another_zip(tmp_dir: Path, pack_tar_path: Path) -> Path:
    # Contents for another.zip:
    # - doc.md
    # - pack.tar (built previously)
    doc_md = b"# Doc\n"
    another_zip_path = tmp_dir / "another.zip"
    with zipfile.ZipFile(another_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.md", doc_md)
        zf.write(pack_tar_path, arcname="pack.tar")
    return another_zip_path


def build_top_zip(archives_dir: Path, inner_path: Path, extra_path: Path, another_path: Path) -> Path:
    # Contents for top.zip (top-level):
    # - readme.txt
    # - inner.tar.gz
    # - extra.tgz
    # - another.zip
    readme_txt = b"Top level README\n"
    top_zip_path = archives_dir / "top.zip"
    with zipfile.ZipFile(top_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.txt", readme_txt)
        zf.write(inner_path, arcname="inner.tar.gz")
        zf.write(extra_path, arcname="extra.tgz")
        zf.write(another_path, arcname="another.zip")
    return top_zip_path


def build_solo_gz(archives_dir: Path) -> Path:
    # solo.txt.gz (single-file gzip of solo.txt)
    solo_txt = b"a solo line\n"
    solo_gz_path = archives_dir / "solo.txt.gz"
    with gzip.open(solo_gz_path, "wb") as gz:
        gz.write(solo_txt)
    return solo_gz_path


def main():
    # Place archives under input/archives relative to this script
    script_dir = Path(__file__).resolve().parent
    archives_dir = script_dir / "archives"

    # Clean and prepare
    ensure_clean_dir(archives_dir)
    tmp_dir = archives_dir / "_build_tmp"
    ensure_clean_dir(tmp_dir)

    # Build nested pieces
    inner_path = build_inner_tar_gz(tmp_dir)
    extra_path = build_extra_tgz(tmp_dir)
    pack_tar_path = build_pack_tar(tmp_dir)
    another_zip_path = build_another_zip(tmp_dir, pack_tar_path)

    # Build top.zip with the components
    build_top_zip(archives_dir, inner_path, extra_path, another_zip_path)

    # Build solo.txt.gz alongside top.zip
    build_solo_gz(archives_dir)

    # Cleanup temporary files, leaving only the required archives
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Created archives in: {archives_dir}")
    print("- top.zip (contains readme.txt, inner.tar.gz, extra.tgz, another.zip)")
    print("- solo.txt.gz (single-file gzip of solo.txt)")


if __name__ == "__main__":
    main()