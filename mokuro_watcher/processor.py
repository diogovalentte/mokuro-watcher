import os
import shutil
import subprocess
from pathlib import Path


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

        target_dir = output_dir / series
        target_dir.mkdir(parents=True, exist_ok=True)
        os.replace(staged_mokuro, target_dir / f"{stem}.mokuro")
        os.replace(staged_cbz, target_dir / filename)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _remove_if_empty(work_dir.parent)


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
