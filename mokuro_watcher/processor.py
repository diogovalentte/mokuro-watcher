import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

# Fixed namespace so every run, and every chapter, derives the same title_uuid for a series.
TITLE_UUID_NAMESPACE = uuid.UUID("6f1d6c2e-3b0a-4f5e-9a57-2d6b8f4c1e90")


class ProcessingError(Exception):
    pass


def process_chapter(
    rel_path: str,
    library_dir: Path,
    staging_dir: Path,
    output_dir: Path,
    mokuro_command: tuple[str, ...],
    timeout_seconds: int,
) -> None:
    """OCR one chapter in staging, then publish the .cbz + .mokuro pair to the output dir.

    The .cbz is hardlinked, never copied: staging and output live on the library's filesystem.
    The .mokuro is moved before the .cbz so the reader never lists a volume without its OCR.
    """
    source = library_dir / rel_path
    series, filename = rel_path.split("/", 1)
    stem = Path(filename).stem

    work_dir = staging_dir / series / stem
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    try:
        staged_cbz = work_dir / filename
        os.link(source, staged_cbz)

        try:
            result = subprocess.run(
                [*mokuro_command, str(staged_cbz)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            raise ProcessingError(f"mokuro passou de {timeout_seconds}s") from e
        staged_mokuro = work_dir / f"{stem}.mokuro"
        if result.returncode != 0 or not staged_mokuro.is_file():
            output = (result.stderr or result.stdout or "").strip()
            raise ProcessingError(f"mokuro saiu com {result.returncode}: {output[-1500:]}")
        set_series_title(staged_mokuro, series)

        target_dir = output_dir / series
        target_dir.mkdir(parents=True, exist_ok=True)
        os.replace(staged_mokuro, target_dir / f"{stem}.mokuro")
        os.replace(staged_cbz, target_dir / filename)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _remove_if_empty(work_dir.parent)


def series_title_uuid(series: str) -> str:
    return str(uuid.uuid5(TITLE_UUID_NAMESPACE, series))


def set_series_title(path_mokuro: Path, series: str) -> bool:
    """Name the series after its library folder, not the staging folder mokuro saw.

    mokuro takes `title` from the folder the .cbz is in, and that folder only ever holds
    one chapter, so it also mints a new `title_uuid` per chapter. Returns whether the file
    changed.
    """
    data = json.loads(path_mokuro.read_text(encoding="utf-8"))
    fixed = with_series_title(data, series)
    if fixed == data:
        return False
    tmp = path_mokuro.with_name(path_mokuro.name + ".tmp")
    tmp.write_text(json.dumps(fixed, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path_mokuro)
    return True


def with_series_title(data: dict, series: str) -> dict:
    return {**data, "title": series, "title_uuid": series_title_uuid(series)}


def fix_published_titles(output_dir: Path) -> int:
    """Apply `set_series_title` to every .mokuro already published. Returns how many changed."""
    changed = 0
    for path_mokuro in sorted(output_dir.glob("*/*.mokuro")):
        if set_series_title(path_mokuro, path_mokuro.parent.name):
            changed += 1
    return changed


def unpublish_chapter(rel_path: str, output_dir: Path) -> None:
    series, filename = rel_path.split("/", 1)
    target_dir = output_dir / series
    for name in (filename, f"{Path(filename).stem}.mokuro"):
        (target_dir / name).unlink(missing_ok=True)
    _remove_if_empty(target_dir)


def _remove_if_empty(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError:
        pass
