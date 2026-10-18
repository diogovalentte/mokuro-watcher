import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import registry as reg
from .config import Config
from .library import list_cbz
from .processor import remove_covers, with_series_title

IMPORTED = "imported"
REPLACED = "replaced"
REJECTED = "rejected"


class InvalidImport(Exception):
    """The request as a whole is invalid, as opposed to one of its files."""


@dataclass(frozen=True)
class ImportResult:
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class SeriesSummary:
    name: str
    chapters: int
    published: int


def import_mokuro(
    config: Config, registry: reg.Registry, series: str, files: list[tuple[str, bytes]]
) -> list[ImportResult]:
    """Publish .mokuro files made outside the watcher (e.g. on a GPU machine) for one series.

    Each file must be named after a .cbz already in the series' library folder. The pair is
    published the same way the watcher publishes its own (.mokuro first, then the .cbz
    hardlink) and the chapter is registered as done, so a later delete or redownload of
    the .cbz is handled like any chapter the watcher processed itself.
    """
    series_dir = _series_dir(config, series)
    return [_import_one(config, registry, series, series_dir, name, content) for name, content in files]


def list_series(config: Config) -> list[SeriesSummary]:
    chapters: dict[str, list[str]] = {}
    for file in list_cbz(config.library_dir):
        series, filename = file.path.split("/", 1)
        chapters.setdefault(series, []).append(filename)
    summaries = []
    for series, filenames in sorted(chapters.items()):
        out = config.output_dir / series
        published = sum(1 for f in filenames if (out / f).with_suffix(".mokuro").is_file())
        summaries.append(SeriesSummary(series, len(filenames), published))
    return summaries


def to_dict(item: ImportResult | SeriesSummary) -> dict:
    return asdict(item)


def _series_dir(config: Config, series: str) -> Path:
    if not series or series.startswith(".") or "/" in series or "\\" in series:
        raise InvalidImport(f"nome de série inválido: {series!r}")
    series_dir = config.library_dir / series
    if not series_dir.is_dir():
        raise InvalidImport(f"série não encontrada na biblioteca: {series}")
    return series_dir


def _import_one(
    config: Config,
    registry: reg.Registry,
    series: str,
    series_dir: Path,
    name: str,
    content: bytes,
) -> ImportResult:
    if Path(name).name != name or "\\" in name or not name.endswith(".mokuro"):
        return ImportResult(name, REJECTED, "não é um arquivo .mokuro")
    stem = name[: -len(".mokuro")]
    cbz_name = f"{stem}.cbz"
    library_cbz = series_dir / cbz_name
    if not library_cbz.is_file():
        return ImportResult(name, REJECTED, f"{cbz_name} não existe na biblioteca")
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ImportResult(name, REJECTED, "JSON inválido")
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        return ImportResult(name, REJECTED, "não parece um .mokuro (sem a lista pages)")

    target_dir = config.output_dir / series
    target_dir.mkdir(parents=True, exist_ok=True)
    target_mokuro = target_dir / name
    replaced = target_mokuro.is_file()

    tmp = target_dir / f".{name}.tmp"
    tmp.write_text(json.dumps(with_series_title(data, series), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target_mokuro)
    if _link(library_cbz, target_dir / cbz_name):
        remove_covers(target_dir, stem)

    stat = library_cbz.stat()
    registry.upsert(f"{series}/{cbz_name}", stat.st_mtime_ns, stat.st_size, reg.DONE)
    return ImportResult(name, REPLACED if replaced else IMPORTED)


def _link(source: Path, target: Path) -> bool:
    """Point `target` at `source`'s inode, replacing whatever was there in one step.

    Returns whether `target` changed.
    """
    try:
        if target.stat().st_ino == source.stat().st_ino:
            return False
    except FileNotFoundError:
        pass
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.unlink(missing_ok=True)
    os.link(source, tmp)
    os.replace(tmp, target)
    return True
