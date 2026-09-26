import logging
import time
from pathlib import Path

from . import registry as reg
from .config import Config
from .library import is_raw_source, list_cbz
from .notify import notify
from .processor import ProcessingError, process_chapter, unpublish_chapter

log = logging.getLogger(__name__)


def sync_library(config: Config, registry: reg.Registry, now: float | None = None) -> None:
    """Bring the registry in line with the library.

    On the very first run every existing chapter becomes `seen` (or `ignored`) so only
    chapters downloaded afterwards get processed.
    """
    now = time.time() if now is None else now
    baseline = not registry.baseline_done
    files = list_cbz(config.library_dir)
    present = set()

    for file in files:
        present.add(file.path)
        known = registry.get(file.path)
        if known and known.mtime_ns == file.mtime_ns and known.size == file.size:
            continue
        if not baseline and now - file.mtime_ns / 1e9 < config.min_age_seconds:
            continue  # probably still being written by mangal
        raw = is_raw_source(config.library_dir / file.path, config.sources)
        if not raw:
            status = reg.IGNORED
        elif baseline:
            status = reg.SEEN
        else:
            status = reg.PENDING
        if known and known.status == reg.DONE and status != reg.PENDING:
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

    if baseline:
        registry.mark_baseline_done()
        log.info("linha de base registrada: %d capítulos existentes ignorados", len(files))


def process_pending(config: Config, registry: reg.Registry) -> int:
    processed = 0
    for chapter in registry.pending():
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
    """Queue every raw chapter of a series, including ones from before the baseline."""
    series_dir = config.library_dir / series
    if not series_dir.is_dir():
        raise SystemExit(f"série não encontrada: {series_dir}")
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
