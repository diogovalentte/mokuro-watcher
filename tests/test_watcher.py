import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

from mokuro_watcher import registry as reg
from mokuro_watcher.config import Config
from mokuro_watcher.library import is_raw_source, source_host
from mokuro_watcher.processor import fix_published_titles, series_title_uuid
from mokuro_watcher.watcher import force_series, process_pending, sync_library

FAKE_MOKURO = (sys.executable, str(Path(__file__).parent / "fake_mokuro.py"))
OLD = time.time() - 3600


def make_cbz(library: Path, rel: str, web: str | None, mtime: float = OLD) -> Path:
    path = library / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("000001.jpg", b"img")
        if web is not None:
            archive.writestr("ComicInfo.xml", f"<ComicInfo><Web>{web}</Web></ComicInfo>")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def env(tmp_path):
    library = tmp_path / "Mangas"
    library.mkdir()
    config = Config.from_env(
        {
            "LIBRARY_DIR": str(library),
            "STATE_DB": str(tmp_path / "state.db"),
            "MIN_AGE_SECONDS": "120",
            "MAX_ATTEMPTS": "2",
        }
    )
    config = Config(**{**config.__dict__, "mokuro_command": FAKE_MOKURO})
    registry = reg.Registry(config.state_db)
    yield config, registry, library
    registry.close()


RAW = "https://klmanga.town/manga-raw/x/chapter-1"
EN = "https://mangadex.org/chapter/abc"


def start(config, registry, library):
    """First run over a library that already has the Raw and En series."""
    make_cbz(library, "Raw/[0000]_Chapter_0.cbz", RAW)
    make_cbz(library, "En/[0000]_Chapter_0.cbz", EN)
    sync_library(config, registry)


def test_source_filter(tmp_path):
    raw = make_cbz(tmp_path, "A/[0001]_Chapter_1.cbz", RAW)
    en = make_cbz(tmp_path, "B/[0001]_Chapter_1.cbz", EN)
    none = make_cbz(tmp_path, "C/[0001]_Chapter_1.cbz", None)
    sources = ("klmanga", "rawkuma", "jmanga")
    assert source_host(raw) == "klmanga.town"
    assert is_raw_source(raw, sources)
    assert not is_raw_source(en, sources)
    assert not is_raw_source(none, sources)


@pytest.mark.parametrize(
    "web",
    [
        "https://klmanga.town/x",
        "https://klmanga.zone/x",
        "https://www.rawkuma.net/x",
        "https://rawkuma.io/x",
        "https://jmanga.to/x",
        "https://JMANGA.ac/x",
    ],
)
def test_source_matches_any_domain(tmp_path, web):
    cbz = make_cbz(tmp_path, "A/[0001]_Chapter_1.cbz", web)
    assert is_raw_source(cbz, ("klmanga", "rawkuma", "jmanga"))


def test_first_run_is_baseline_only(env):
    config, registry, library = env
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    make_cbz(library, "En/[0001]_Chapter_1.cbz", EN)

    sync_library(config, registry)

    assert registry.get("Raw/[0001]_Chapter_1.cbz").status == reg.SEEN
    assert registry.get("En/[0001]_Chapter_1.cbz").status == reg.IGNORED
    assert registry.pending() == []


def test_new_raw_chapter_is_published(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0002]_Chapter_2.cbz", RAW)
    make_cbz(library, "En/[0002]_Chapter_2.cbz", EN)

    sync_library(config, registry)
    assert process_pending(config, registry) == 1

    out = config.output_dir / "Raw"
    assert (out / "[0002]_Chapter_2.cbz").is_file()
    assert (out / "[0002]_Chapter_2.mokuro").is_file()
    assert not (config.output_dir / "En").exists()
    # hardlink, not a copy
    assert (out / "[0002]_Chapter_2.cbz").stat().st_ino == (
        library / "Raw/[0002]_Chapter_2.cbz"
    ).stat().st_ino
    assert registry.get("Raw/[0002]_Chapter_2.cbz").status == reg.DONE
    assert not any(config.staging_dir.iterdir())


def test_output_and_staging_are_not_scanned(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0002]_Chapter_2.cbz", RAW)
    sync_library(config, registry)
    process_pending(config, registry)

    sync_library(config, registry)

    paths = {c.path for c in registry.all()}
    assert paths == {
        "Raw/[0000]_Chapter_0.cbz",
        "En/[0000]_Chapter_0.cbz",
        "Raw/[0002]_Chapter_2.cbz",
    }


def test_chapter_still_being_written_waits(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0003]_Chapter_3.cbz", RAW, mtime=time.time())

    sync_library(config, registry)
    assert registry.get("Raw/[0003]_Chapter_3.cbz") is None

    sync_library(config, registry, now=time.time() + 600)
    assert registry.get("Raw/[0003]_Chapter_3.cbz").status == reg.PENDING


def test_failure_retries_then_gives_up(env, monkeypatch):
    config, registry, library = env
    notes = []
    monkeypatch.setattr("mokuro_watcher.watcher.notify", lambda *a: notes.append(a))
    start(config, registry, library)
    make_cbz(library, "Raw/[0004]_fail.cbz", RAW)
    sync_library(config, registry)

    process_pending(config, registry)
    chapter = registry.get("Raw/[0004]_fail.cbz")
    assert (chapter.status, chapter.attempts) == (reg.PENDING, 1)
    assert "boom" in chapter.last_error
    assert notes == []

    process_pending(config, registry)
    assert registry.get("Raw/[0004]_fail.cbz").status == reg.FAILED
    assert len(notes) == 1
    assert not (config.output_dir / "Raw").exists()


def test_removed_chapter_is_unpublished(env):
    config, registry, library = env
    start(config, registry, library)
    src = make_cbz(library, "Raw/[0005]_Chapter_5.cbz", RAW)
    sync_library(config, registry)
    process_pending(config, registry)
    (config.output_dir / "volume-data.json").write_text("{}")

    src.unlink()
    sync_library(config, registry)

    assert registry.get("Raw/[0005]_Chapter_5.cbz") is None
    assert not (config.output_dir / "Raw").exists()
    assert (config.output_dir / "volume-data.json").is_file()


def test_redownloaded_chapter_is_reprocessed(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0006]_Chapter_6.cbz", RAW)
    sync_library(config, registry)
    process_pending(config, registry)

    make_cbz(library, "Raw/[0006]_Chapter_6.cbz", RAW, mtime=OLD + 60)
    sync_library(config, registry)
    assert registry.get("Raw/[0006]_Chapter_6.cbz").status == reg.PENDING
    process_pending(config, registry)
    published = config.output_dir / "Raw/[0006]_Chapter_6.cbz"
    assert published.stat().st_ino == (library / "Raw/[0006]_Chapter_6.cbz").stat().st_ino


def test_force_queues_backlog_raw_only(env):
    config, registry, library = env
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    make_cbz(library, "Raw/[0002]_Chapter_2.cbz", RAW)
    make_cbz(library, "En/[0001]_Chapter_1.cbz", EN)
    sync_library(config, registry)

    assert force_series(config, registry, "Raw") == 2
    sync_library(config, registry)
    assert len(registry.pending()) == 2
    assert force_series(config, registry, "En") == 0


def test_new_series_initial_download_is_skipped(env):
    config, registry, library = env
    start(config, registry, library)
    window = config.series_baseline_seconds
    now = time.time()

    make_cbz(library, "Nova/[0001]_Chapter_1.cbz", RAW)
    make_cbz(library, "Nova/[0002]_Chapter_2.cbz", RAW, mtime=now)
    sync_library(config, registry, now=now)
    # the download keeps going, each chapter pushes the window forward
    make_cbz(library, "Nova/[0003]_Chapter_3.cbz", RAW)
    sync_library(config, registry, now=now + window - 60)
    make_cbz(library, "Nova/[0004]_Chapter_4.cbz", RAW)
    sync_library(config, registry, now=now + 2 * window - 120)

    assert registry.pending() == []
    assert {c.status for c in registry.all() if c.path.startswith("Nova/")} == {reg.SEEN}

    make_cbz(library, "Nova/[0005]_Chapter_5.cbz", RAW)
    sync_library(config, registry, now=now + 3 * window)
    assert [c.path for c in registry.pending()] == ["Nova/[0005]_Chapter_5.cbz"]


def test_new_chapter_in_existing_series_is_not_a_new_series(env):
    config, registry, library = env
    start(config, registry, library)
    # database from before series were tracked
    with registry.conn:
        registry.conn.execute("DELETE FROM series")

    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    sync_library(config, registry)
    assert [c.path for c in registry.pending()] == ["Raw/[0001]_Chapter_1.cbz"]


def test_series_removed_and_added_again_is_new(env):
    config, registry, library = env
    start(config, registry, library)
    (library / "Raw/[0000]_Chapter_0.cbz").unlink()
    sync_library(config, registry)

    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    sync_library(config, registry)
    assert registry.pending() == []


def test_force_ends_new_series_window(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Nova/[0001]_Chapter_1.cbz", RAW)
    sync_library(config, registry)

    assert force_series(config, registry, "Nova") == 1
    make_cbz(library, "Nova/[0002]_Chapter_2.cbz", RAW)
    sync_library(config, registry)
    assert len(registry.pending()) == 2


def test_published_mokuro_is_named_after_the_series(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "あさドラ！/[0001]_Chapter_1.cbz", RAW)
    make_cbz(library, "あさドラ！/[0002]_Chapter_2.cbz", RAW)
    force_series(config, registry, "あさドラ！")
    sync_library(config, registry)
    process_pending(config, registry)

    out = config.output_dir / "あさドラ！"
    first, second = (
        json.loads((out / f"{stem}.mokuro").read_text(encoding="utf-8"))
        for stem in ("[0001]_Chapter_1", "[0002]_Chapter_2")
    )
    assert first["title"] == second["title"] == "あさドラ！"
    assert first["title_uuid"] == second["title_uuid"] == series_title_uuid("あさドラ！")
    assert first["volume_uuid"] != second["volume_uuid"]
    assert first["pages"] == [{"blocks": [{"lines": ["日本語"]}]}]


def test_fix_published_titles(env):
    config, _, _ = env
    out = config.output_dir / "Raw"
    out.mkdir(parents=True)
    wrong = {"title": "[0001]_Chapter_1", "title_uuid": "x", "volume_uuid": "v", "pages": []}
    (out / "[0001]_Chapter_1.mokuro").write_text(json.dumps(wrong))
    (config.output_dir / "volume-data.json").write_text("{}")

    assert fix_published_titles(config.output_dir) == 1
    fixed = json.loads((out / "[0001]_Chapter_1.mokuro").read_text())
    assert fixed == {**wrong, "title": "Raw", "title_uuid": series_title_uuid("Raw")}
    assert (config.output_dir / "volume-data.json").read_text() == "{}"
    assert fix_published_titles(config.output_dir) == 0
