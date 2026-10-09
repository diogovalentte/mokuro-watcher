import json
import threading
import urllib.error
import urllib.request

import pytest

from mokuro_watcher import registry as reg
from mokuro_watcher.api import make_server
from mokuro_watcher.importer import (
    IMPORTED,
    REJECTED,
    REPLACED,
    InvalidImport,
    import_mokuro,
    list_series,
)
from mokuro_watcher.processor import series_title_uuid
from mokuro_watcher.watcher import process_pending, sync_library

from .test_watcher import RAW, env, make_cbz, start  # noqa: F401


def mokuro(title="[0001]_Chapter_1", pages=None) -> bytes:
    data = {
        "title": title,
        "title_uuid": "from-the-pc",
        "volume": title,
        "volume_uuid": "v",
        "pages": pages if pages is not None else [{"blocks": []}],
    }
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_import_publishes_pair_and_registers_done(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)

    results = import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])

    assert [r.status for r in results] == [IMPORTED]
    out = config.output_dir / "Raw"
    published = json.loads((out / "[0001]_Chapter_1.mokuro").read_text(encoding="utf-8"))
    assert published["title"] == "Raw"
    assert published["title_uuid"] == series_title_uuid("Raw")
    assert published["volume_uuid"] == "v"
    assert (out / "[0001]_Chapter_1.cbz").stat().st_ino == (
        library / "Raw/[0001]_Chapter_1.cbz"
    ).stat().st_ino
    assert registry.get("Raw/[0001]_Chapter_1.cbz").status == reg.DONE
    assert sorted(p.name for p in out.iterdir()) == [
        "[0001]_Chapter_1.cbz",
        "[0001]_Chapter_1.mokuro",
    ]


def test_imported_chapter_is_left_alone_then_unpublished_on_delete(env):
    config, registry, library = env
    start(config, registry, library)
    cbz = make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])

    sync_library(config, registry)
    assert process_pending(config, registry) == 0
    assert registry.get("Raw/[0001]_Chapter_1.cbz").status == reg.DONE

    cbz.unlink()
    sync_library(config, registry)
    assert not (config.output_dir / "Raw").exists()


def test_import_wins_over_a_queued_chapter(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    sync_library(config, registry)
    assert registry.get("Raw/[0001]_Chapter_1.cbz").status == reg.PENDING

    import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])

    assert process_pending(config, registry) == 0
    published = json.loads(
        (config.output_dir / "Raw/[0001]_Chapter_1.mokuro").read_text(encoding="utf-8")
    )
    assert published["pages"] == [{"blocks": []}]


def test_import_again_replaces(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])

    results = import_mokuro(
        config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro(pages=[{"blocks": [1]}]))]
    )

    assert [r.status for r in results] == [REPLACED]
    published = json.loads(
        (config.output_dir / "Raw/[0001]_Chapter_1.mokuro").read_text(encoding="utf-8")
    )
    assert published["pages"] == [{"blocks": [1]}]


def test_import_relinks_a_published_cbz_from_an_old_download(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])
    (library / "Raw/[0001]_Chapter_1.cbz").unlink()
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)

    import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])

    assert (config.output_dir / "Raw/[0001]_Chapter_1.cbz").stat().st_ino == (
        library / "Raw/[0001]_Chapter_1.cbz"
    ).stat().st_ino


@pytest.mark.parametrize(
    ("name", "content", "detail"),
    [
        ("[0009]_Chapter_9.mokuro", mokuro(), "[0009]_Chapter_9.cbz não existe na biblioteca"),
        ("[0001]_Chapter_1.json", mokuro(), "não é um arquivo .mokuro"),
        ("../Raw/[0001]_Chapter_1.mokuro", mokuro(), "não é um arquivo .mokuro"),
        ("[0001]_Chapter_1.mokuro", b"{not json", "JSON inválido"),
        ("[0001]_Chapter_1.mokuro", b'{"title": "x"}', "não parece um .mokuro (sem a lista pages)"),
    ],
)
def test_import_rejects_one_file_without_failing_the_rest(env, name, content, detail):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    make_cbz(library, "Raw/[0002]_Chapter_2.cbz", RAW)

    results = import_mokuro(
        config, registry, "Raw", [(name, content), ("[0002]_Chapter_2.mokuro", mokuro())]
    )

    assert [(r.status, r.detail) for r in results] == [(REJECTED, detail), (IMPORTED, "")]
    assert not (config.output_dir / "Raw/[0001]_Chapter_1.mokuro").exists()


@pytest.mark.parametrize("series", ["Nope", "", ".mokuro-reader", "Raw/../En"])
def test_import_refuses_unknown_series(env, series):
    config, registry, library = env
    start(config, registry, library)
    with pytest.raises(InvalidImport):
        import_mokuro(config, registry, series, [("[0000]_Chapter_0.mokuro", mokuro())])


def test_list_series_counts_published(env):
    config, registry, library = env
    start(config, registry, library)
    make_cbz(library, "Raw/[0001]_Chapter_1.cbz", RAW)
    import_mokuro(config, registry, "Raw", [("[0001]_Chapter_1.mokuro", mokuro())])

    assert [(s.name, s.chapters, s.published) for s in list_series(config)] == [
        ("En", 1, 0),
        ("Raw", 2, 1),
    ]


@pytest.fixture
def api(env):
    config, registry, library = env
    server = make_server(config, 0, host="127.0.0.1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", config, registry, library
    server.shutdown()
    server.server_close()


def call(url, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_api_series_and_import(api):
    base, config, registry, library = api
    start(config, registry, library)
    make_cbz(library, "生徒会にも穴はある！/[0001]_Chapter_1.cbz", RAW)

    status, body = call(f"{base}/series")
    assert status == 200
    assert {"name": "生徒会にも穴はある！", "chapters": 1, "published": 0} in body["series"]

    status, body = call(
        f"{base}/import",
        {
            "series": "生徒会にも穴はある！",
            "files": [
                {"name": "[0001]_Chapter_1.mokuro", "content": mokuro().decode("utf-8")},
                {"name": "[0002]_Chapter_2.mokuro", "content": mokuro().decode("utf-8")},
            ],
        },
    )
    assert status == 200
    assert body["results"] == [
        {"name": "[0001]_Chapter_1.mokuro", "status": IMPORTED, "detail": ""},
        {
            "name": "[0002]_Chapter_2.mokuro",
            "status": REJECTED,
            "detail": "[0002]_Chapter_2.cbz não existe na biblioteca",
        },
    ]
    assert registry.get("生徒会にも穴はある！/[0001]_Chapter_1.cbz").status == reg.DONE


def test_api_rejects_bad_requests(api):
    base, config, registry, library = api
    start(config, registry, library)
    assert call(f"{base}/import", {"series": "Nope", "files": []}) == (
        400,
        {"error": "série não encontrada na biblioteca: Nope"},
    )
    assert call(f"{base}/import", {"files": []})[0] == 400
    assert call(f"{base}/nope")[0] == 404
