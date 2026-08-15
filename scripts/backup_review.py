"""Backup and restore .review_data with manifest verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = ".review_data"
DEFAULT_BACKUP_DIR = ".review_backups"
DEFAULT_MIGRATION_VERSION = "0001_review_data_governance"
MANIFEST_NAME = "backup_manifest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_data_files(data_dir: Path) -> list[Path]:
    return sorted(path for path in data_dir.rglob("*") if path.is_file())


def _safe_members(zip_file: zipfile.ZipFile, target_dir: Path) -> list[zipfile.ZipInfo]:
    target_root = target_dir.resolve()
    members: list[zipfile.ZipInfo] = []
    for member in zip_file.infolist():
        destination = (target_dir / member.filename).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise ValueError(f"unsafe archive member path: {member.filename}")
        members.append(member)
    return members


def create_backup(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
    *,
    migration_version: str = DEFAULT_MIGRATION_VERSION,
) -> Path:
    data_root = Path(data_dir)
    if not data_root.exists():
        raise FileNotFoundError(f"review data directory does not exist: {data_root}")
    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = backup_root / f"review_data_backup_{timestamp}.zip"

    files = _iter_data_files(data_root)
    manifest_files = []
    for path in files:
        relative = path.relative_to(data_root).as_posix()
        manifest_files.append({"path": relative, "sha256": file_sha256(path)})
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "migration_version": migration_version,
        "source_dir": str(data_root),
        "files": manifest_files,
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(data_root).as_posix())
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return archive_path


def _validate_extracted_manifest(extracted_dir: Path) -> dict[str, Any]:
    manifest_path = extracted_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise ValueError("backup archive is missing backup_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = extracted_dir / entry["path"]
        if not path.exists():
            raise ValueError(f"backup archive is missing data file: {entry['path']}")
        actual = file_sha256(path)
        if actual != entry["sha256"]:
            raise ValueError(f"backup sha256 mismatch for {entry['path']}")
    return manifest


def restore_backup(
    archive_path: str | Path,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    target = Path(data_dir)
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise FileExistsError(f"target data directory is not empty: {target}")
    with tempfile.TemporaryDirectory() as temp_name:
        extracted = Path(temp_name) / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for member in _safe_members(archive, extracted):
                archive.extract(member, extracted)
        manifest = _validate_extracted_manifest(extracted)
        if target.exists() and overwrite:
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        for entry in manifest.get("files", []):
            source = extracted / entry["path"]
            destination = target / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup or restore .review_data.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    backup = subcommands.add_parser("backup")
    backup.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    backup.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    backup.add_argument("--migration-version", default=DEFAULT_MIGRATION_VERSION)

    restore = subcommands.add_parser("restore")
    restore.add_argument("archive")
    restore.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    restore.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "backup":
        archive_path = create_backup(
            args.data_dir,
            args.backup_dir,
            migration_version=args.migration_version,
        )
        print(archive_path)
        return 0
    manifest = restore_backup(args.archive, args.data_dir, overwrite=args.overwrite)
    print(json.dumps({"restored": True, "migration_version": manifest.get("migration_version")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

