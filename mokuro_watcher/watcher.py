import logging
import time
from pathlib import Path

from . import registry as reg
from .api import start_api
from .config import Config
from .library import LibraryFile, is_raw_source, list_cbz
from .notify import notify
from .processor import ProcessingError, process_chapter, unpublish_chapter

log = logging.getLogger(__name__)


def sync_library(config: Config, registry: reg.Registry, now: float | None = None) -> None:
    """Bring the registry in line with the library.

    On the very first run every existing chapter becomes `seen` (or `ignored`) so only
    chapters downloaded afterwards get processed. A series that shows up later gets the
    same treatment for its initial download: its chapters are `seen` until
    `series_baseline_seconds` pass without a new one arriving. So does a known series
    that gets `series_burst_threshold` new or changed chapters in one scan, which is what
    re-adding it in Kaizoku from another source looks like. A chapter already published
    keeps its pair through that window, unless its file was rewritten in place.
    """
    now = time.time() if now is None else now
    baseline = not registry.baseline_done
    files = list_cbz(config.library_dir)
    present = set()
    series_until = registry.series_baselines()
    known_series = {chapter.path.split("/", 1)[0] for chapter in registry.all()}

    if not baseline:
        _open_burst_windows(config, registry, files, series_until, known_series, now)

    for file in files:
        present.add(file.path)
        series = file.path.split("/", 1)[0]
        if series not in series_until:
            is_new = not baseline and series not in known_series
            series_until[series] = now + config.series_baseline_seconds if is_new else 0
            registry.set_series_baseline(series, series_until[series])
            if is_new:
                log.info("série nova: %s, download inicial ignorado", series)
        series_baseline = series_until[series] > now

        known = registry.get(file.path)
        if known and known.mtime_ns == file.mtime_ns and known.size == file.size:
            continue
        settling = baseline or series_baseline
        if series_baseline:
            series_until[series] = now + config.series_baseline_seconds
            registry.set_series_baseline(series, series_until[series])
        if not baseline and now - file.mtime_ns / 1e9 < config.min_age_seconds:
            continue  # probably still being written by mangal
        raw = is_raw_source(config.library_dir / file.path, config.sources)
        if not raw:
            status = reg.IGNORED
        elif settling:
            status = reg.SEEN
        else:
            status = reg.PENDING
        if known and known.status == reg.DONE and status != reg.PENDING:
            if status == reg.SEEN and _published_pair_intact(config, file.path):
                status = reg.DONE
            else:
                unpublish_chapter(file.path, config.output_dir)
        registry.upsert(file.path, file.mtime_ns, file.size, status)
        if status == reg.PENDING:
            log.info("capítulo novo: %s", file.path)

    for chapter in registry.all():
        if chapter.path in present:
            continue
        if chapter.status == reg.DONE:
            unpublish_chapter(chapter.path, config.output_dir)
            log.info("capítulo removido da biblioteca, despublicado: %s", chapter.path)
        registry.delete(chapter.path)

    present_series = {path.split("/", 1)[0] for path in present}
    for series in series_until:
        if series not in present_series:
            registry.delete_series(series)

    if baseline:
        registry.mark_baseline_done()
        log.info("linha de base registrada: %d capítulos existentes ignorados", len(files))


def _open_burst_windows(
    config: Config,
    registry: reg.Registry,
    files: list[LibraryFile],
    series_until: dict[str, float],
    known_series: set[str],
    now: float,
) -> None:
    """Treat a burst of new or changed chapters in a known series as an initial download.

    Counts files still being written too: the download spans several scans, and those are
    skipped this time anyway, so the window has to be open before the first one settles.
    """
    changed: dict[str, int] = {}
    for file in files:
        series = file.path.split("/", 1)[0]
        if series not in known_series or series_until.get(series, 0) > now:
            continue
        known = registry.get(file.path)
        if known and known.mtime_ns == file.mtime_ns and known.size == file.size:
            continue
        changed[series] = changed.get(series, 0) + 1
    for series, count in changed.items():
        if count >= config.series_burst_threshold:
            series_until[series] = now + config.series_baseline_seconds
            registry.set_series_baseline(series, series_until[series])
            log.info("rajada em %s: %d capítulos, tratada como download inicial", series, count)


def _published_pair_intact(config: Config, rel_path: str) -> bool:
    """Whether the published pair still holds the images its .mokuro was made from.

    The published .cbz is a hardlink, so a file rewritten in place changed it too; one
    deleted and downloaded again left the published link on the old inode.
    """
    series, filename = rel_path.split("/", 1)
    published = config.output_dir / series / filename
    try:
        published_ino = published.stat().st_ino
    except FileNotFoundError:
        return False
    return (
        published.with_suffix(".mokuro").is_file()
        and published_ino != (config.library_dir / rel_path).stat().st_ino
    )


def process_pending(config: Config, registry: reg.Registry, now: float | None = None) -> int:
    """Process the queue, holding back series whose initial download window is open."""
    now = time.time() if now is None else now
    held = {name for name, until in registry.series_baselines().items() if until > now}
    processed = 0
    for chapter in registry.pending():
        if chapter.path.split("/", 1)[0] in held:
            continue
        current = registry.get(chapter.path)
        if current is None or current.status != reg.PENDING:
            continue  # imported through the API while earlier chapters were processing
        log.info("processando %s", chapter.path)
        started = time.monotonic()
        try:
            process_chapter(
                chapter.path,
                config.library_dir,
                config.staging_dir,
                config.output_dir,
                config.mokuro_command,
                config.mokuro_timeout_seconds,
            )
        except (ProcessingError, OSError) as e:
            failed = registry.record_failure(chapter.path, str(e), config.max_attempts)
            log.error("falha em %s (tentativa %d): %s", chapter.path, failed.attempts, e)
            if failed.status == reg.FAILED:
                notify(
                    config.ntfy_url,
                    config.ntfy_topic,
                    config.ntfy_token,
                    "mokuro-watcher: capítulo falhou",
                    f"{chapter.path} falhou {failed.attempts} vezes: {str(e)[-500:]}",
                )
            continue
        registry.set_status(chapter.path, reg.DONE)
        processed += 1
        log.info("publicado %s em %.0fs", chapter.path, time.monotonic() - started)
    return processed


def force_series(config: Config, registry: reg.Registry, series: str) -> int:
    """Queue every raw chapter of a series, including ones from before the baseline.

    Also ends the series' initial download window, so the rest of it gets processed too.
    """
    series_dir = config.library_dir / series
    if not series_dir.is_dir():
        raise SystemExit(f"série não encontrada: {series_dir}")
    registry.set_series_baseline(series, 0)
    queued = 0
    for file in list_cbz(config.library_dir):
        if not file.path.startswith(f"{series}/"):
            continue
        if not is_raw_source(config.library_dir / file.path, config.sources):
            continue
        registry.upsert(file.path, file.mtime_ns, file.size, reg.PENDING)
        queued += 1
    return queued


def run_forever(config: Config, registry: reg.Registry) -> None:
    if config.api_port:
        start_api(config, config.api_port)
        log.info("API ouvindo na porta %d", config.api_port)
    while True:
        try:
            sync_library(config, registry)
            process_pending(config, registry)
        except Exception:
            log.exception("erro na varredura")
        time.sleep(config.scan_interval_seconds)


def ensure_dirs(config: Config) -> None:
    for directory in (config.output_dir, config.staging_dir):
        Path(directory).mkdir(parents=True, exist_ok=True)
