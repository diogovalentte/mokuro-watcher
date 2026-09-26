import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

WEB_TAG = re.compile(rb"<Web>\s*([^<\s]+)\s*</Web>")


@dataclass(frozen=True)
class LibraryFile:
    path: str  # relative to the library, e.g. "Series/[0001]_Chapter_1.cbz"
    mtime_ns: int
    size: int


def list_cbz(library_dir: Path) -> list[LibraryFile]:
    """Every .cbz one level below each series folder, skipping dot folders."""
    files = []
    with os.scandir(library_dir) as series_entries:
        for series in series_entries:
            if series.name.startswith(".") or not series.is_dir(follow_symlinks=False):
                continue
            with os.scandir(series.path) as chapter_entries:
                for chapter in chapter_entries:
                    if not chapter.name.lower().endswith(".cbz") or not chapter.is_file():
                        continue
                    stat = chapter.stat()
                    files.append(
                        LibraryFile(
                            path=f"{series.name}/{chapter.name}",
                            mtime_ns=stat.st_mtime_ns,
                            size=stat.st_size,
                        )
                    )
    return files


def source_host(cbz_path: Path) -> str | None:
    """Host of the <Web> URL in the chapter's ComicInfo.xml, or None."""
    try:
        with zipfile.ZipFile(cbz_path) as archive:
            name = next(
                (n for n in archive.namelist() if n.lower() == "comicinfo.xml"), None
            )
            if name is None:
                return None
            match = WEB_TAG.search(archive.read(name))
    except (zipfile.BadZipFile, OSError):
        return None
    if not match:
        return None
    return urlparse(match.group(1).decode("utf-8", "replace")).hostname


def is_raw_source(cbz_path: Path, sources: tuple[str, ...]) -> bool:
    host = source_host(cbz_path)
    return host is not None and any(source in host.lower() for source in sources)
