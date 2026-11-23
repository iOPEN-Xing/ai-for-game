"""Stream a consistent studio backup; restore only into a new, empty data volume."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path

from studio.settings import data_dir

DB = "studio.sqlite3"
SUMS = "checksums.json"
OBJECT_DIRS = ("builds", "generated-art")
DIGEST = re.compile(r"[0-9a-f]{64}")
IMAGE_FILE = re.compile(r"[0-9a-f]{64}\.(?:png|json)")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_files(source: Path, database: Path) -> dict[str, Path]:
    files = {DB: database}
    builds = source / "builds"
    for bundle in builds.iterdir() if builds.exists() else ():
        if not DIGEST.fullmatch(bundle.name):
            continue  # A concurrent build has not been published yet.
        if not bundle.is_dir() or bundle.is_symlink():
            raise ValueError("构建目录无效")
        for item in bundle.iterdir():
            if item.is_symlink() or not item.is_file():
                raise ValueError("构建含无效文件")
            files[item.relative_to(source).as_posix()] = item
    # Cache records are installed after their immutable PNGs. Enumerate records first.
    images = source / "generated-art"
    for suffix in ("json", "png"):
        for item in images.glob("*." + suffix):
            if (
                IMAGE_FILE.fullmatch(item.name)
                and item.is_file()
                and not item.is_symlink()
            ):
                files[item.relative_to(source).as_posix()] = item
    return files


def verify_snapshot(files: dict[str, Path], hashes: dict[str, str]) -> None:
    if DB not in files:
        raise ValueError("备份缺少数据库")
    with closing(sqlite3.connect(files[DB].as_uri() + "?mode=ro", uri=True)) as con:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性校验失败")
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("数据库关联校验失败")
        query = "SELECT bundle FROM revisions WHERE bundle IS NOT NULL UNION SELECT bundle FROM rounds"
        for (key,) in con.execute(query):
            if not DIGEST.fullmatch(key) or f"builds/{key}/manifest.json" not in files:
                raise ValueError("备份缺少数据库引用的构建")
    bundles = {}
    for name, digest in sorted(hashes.items()):
        parts = Path(name).parts
        if parts[0] == "builds":
            key, filename = parts[1:]
            if key not in bundles:
                bundles[key] = hashlib.sha256()
            bundles[key].update(filename.encode() + b"\0" + bytes.fromhex(digest))
        elif parts[0] == "generated-art":
            item = files[name]
            if item.suffix == ".png" and digest != item.stem:
                raise ValueError("美术文件与资源标识不符")
            if item.suffix == ".json":
                blob = json.loads(item.read_text()).get("sha256", "")
                if (
                    not DIGEST.fullmatch(blob)
                    or f"generated-art/{blob}.png" not in files
                ):
                    raise ValueError("美术缓存缺少引用的图像")
    if any(state.hexdigest() != key for key, state in bundles.items()):
        raise ValueError("构建目录内容与构建标识不符")


def export_backup(source: Path, stream) -> None:
    with tempfile.TemporaryDirectory(prefix="loop-backup-") as temporary:
        snapshot = Path(temporary)
        with (
            closing(
                sqlite3.connect((source / DB).as_uri() + "?mode=ro", uri=True)
            ) as src,
            closing(sqlite3.connect(snapshot / DB)) as dst,
        ):
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            # A recovery must never resurrect a logged-out browser session.
            if dst.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_sessions'"
            ).fetchone():
                with dst:
                    dst.execute("DELETE FROM team_sessions")
        # Only the mutable database needs a temporary copy. Serve immutable files in place.
        files = snapshot_files(source, snapshot / DB)
        hashes = {name: sha256(path) for name, path in files.items()}
        verify_snapshot(files, hashes)
        (snapshot / SUMS).write_text(json.dumps(hashes, sort_keys=True))
        with tarfile.open(fileobj=stream, mode="w|gz") as archive:
            for name, path in files.items():
                archive.add(path, arcname=name, recursive=False)
            archive.add(snapshot / SUMS, arcname=SUMS, recursive=False)


def restore_backup(target: Path, stream) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError("恢复目标必须是新的空数据目录")
    with tempfile.TemporaryDirectory(dir=target, prefix=".restore-") as temporary:
        stage = Path(temporary)
        for category in OBJECT_DIRS:
            (stage / category).mkdir()
        files = set()
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                name = member.name
                path = Path(name)
                parts = path.parts
                allowed = (
                    name in (DB, SUMS)
                    or (
                        len(parts) == 3
                        and parts[0] == "builds"
                        and DIGEST.fullmatch(parts[1])
                    )
                    or (
                        len(parts) == 2
                        and parts[0] == "generated-art"
                        and IMAGE_FILE.fullmatch(parts[1])
                    )
                )
                if (
                    not allowed
                    or not member.isfile()
                    or path.as_posix() != name
                    or ".." in parts
                    or name in files
                ):
                    raise ValueError("备份包含无效条目")
                files.add(name)
                dest = stage / path
                dest.parent.mkdir(exist_ok=True)
                with (
                    closing(archive.extractfile(member)) as src,
                    dest.open("xb") as dst,
                ):
                    shutil.copyfileobj(src, dst)
        hashes = json.loads((stage / SUMS).read_text())
        paths = {name: stage / name for name in files - {SUMS}}
        actual = {name: sha256(path) for name, path in paths.items()}
        if actual != hashes:
            raise ValueError("备份清单校验失败")
        verify_snapshot(paths, actual)
        installed = []
        try:
            for name in (*OBJECT_DIRS, DB):
                os.rename(stage / name, target / name)
                installed.append(name)
        except OSError:
            for name in reversed(installed):
                os.rename(target / name, stage / name)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "restore"))
    parser.add_argument("--data-dir", type=Path, default=data_dir())
    args = parser.parse_args()
    root = args.data_dir.resolve()
    if args.action == "export":
        export_backup(root, sys.stdout.buffer)
    else:
        restore_backup(root, sys.stdin.buffer)


if __name__ == "__main__":
    main()
