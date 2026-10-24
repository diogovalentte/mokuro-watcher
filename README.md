# mokuro-watcher

Runs [mokuro](https://github.com/kha-white/mokuro) on the raw chapters Kaizoku downloads and publishes the `.cbz` + `.mokuro` pair to a folder that [mokuro-reader](https://github.com/diogovalentte/mokuro-reader) reads over WebDAV.

```
/Medias/Mangas/<Series>/<Chapter>.cbz                         ← written by Kaizoku
/Medias/Mangas/.mokuro-staging/...                            ← mokuro runs here
/Medias/Mangas/.mokuro-reader/<Series>/<Chapter>.{cbz,mokuro} ← served over WebDAV
```

## How it works

- Every `SCAN_INTERVAL_SECONDS` it scans the library. A `.cbz` is queued once it has been untouched for `MIN_AGE_SECONDS` and the `<Web>` of its `ComicInfo.xml` belongs to one of the `SOURCES`.
- On the **first run** everything that already exists is recorded and skipped: only chapters downloaded afterwards are processed.
- **New series** in the library: its initial download is skipped the same way. Incoming chapters are recorded without processing until `SERIES_BASELINE_SECONDS` pass with no new chapter in it; from then on every new chapter is processed. To process the initial backlog too, use `force`.
- mokuro takes the series title from the folder the `.cbz` is in, which in staging is the chapter's folder. Before publishing, the `.mokuro` gets `title` = the series folder name and `title_uuid` = a fixed `uuid5` of that name, so every chapter lands in the same series in the reader.
- One chapter at a time. The published `.cbz` is a hardlink (takes no space); the `.mokuro` is moved before the `.cbz`, so the reader never lists a volume without OCR.
- Failure: retried on the next scans; after `MAX_ATTEMPTS` it gives up and notifies on ntfy.
- `.cbz` deleted from the library → the published pair is deleted too.
- Redownload (mtime/size changed) → reprocessed.
- In both cases the cover (`<Chapter>.webp`/`.jpg`) the reader uploaded next to the `.cbz` is deleted, because the reader only generates a cover for a volume that has none; the new one is made when the volume is downloaded in the reader. The same goes for an import that replaces the published `.cbz`.
- **Burst** in a known series (`SERIES_BURST_THRESHOLD` new or changed chapters in the same scan, as when the series is deleted and added again in Kaizoku from another source) → treated as a new series: nothing is processed until `SERIES_BASELINE_SECONDS` pass with no new chapter. An already published chapter keeps its old pair, which stays consistent because the published `.cbz` still points to the old file; it is only unpublished if the file was overwritten in place (same inode).

Folders starting with `.` in the library are skipped.

## Importing `.mokuro` files made elsewhere

The old backlog of a new series isn't processed here (hours of CPU). You can run mokuro on a machine with a GPU and import just the `.mokuro` files:

- each file must be named after a `.cbz` already in `$LIBRARY_DIR/<Series>/` (`[0001]_Chapter_1.mokuro` ↔ `[0001]_Chapter_1.cbz`); anything else is rejected, file by file;
- it gets the same `title`/`title_uuid` as chapters processed here, is published in the same order (`.mokuro`, then the `.cbz` hardlink) and the chapter is marked `done` in the registry, so deleting or redownloading it works like any other;
- an already published chapter has its `.mokuro` replaced; a queued chapter leaves the queue.

Through the API (used by the Mokuro page of [valentium](https://github.com/diogovalentte/valentium)), bound to `API_PORT` only by the `run` command, with no authentication:

```
GET  /series   → {"series": [{"name", "chapters", "published"}]}
POST /import   {"series": "...", "files": [{"name": "x.mokuro", "content": "<json>"}]}
               → {"results": [{"name", "status": "imported|replaced|rejected", "detail"}]}
```

## Configuration

| Variable | Default |
|---|---|
| `LIBRARY_DIR` | `/Medias/Mangas` |
| `OUTPUT_DIR` | `$LIBRARY_DIR/.mokuro-reader` |
| `STAGING_DIR` | `$LIBRARY_DIR/.mokuro-staging` |
| `STATE_DB` | `/state/mokuro-watcher.db` |
| `SOURCES` | `klmanga,rawkuma,jmanga` |
| `SCAN_INTERVAL_SECONDS` | `300` |
| `MIN_AGE_SECONDS` | `120` |
| `SERIES_BASELINE_SECONDS` | `21600` (6h) |
| `SERIES_BURST_THRESHOLD` | `5` |
| `MAX_ATTEMPTS` | `3` |
| `MOKURO_TIMEOUT_SECONDS` | `7200` |
| `NTFY_ADDRESS`, `NTFY_TOPIC`, `NTFY_TOKEN` | empty (no notifications) |
| `API_PORT` | `8000` (empty or `0` disables it) |

`OUTPUT_DIR` and `STAGING_DIR` must be on the same filesystem as the library (hardlinks).

Volumes: `/cache` holds the OCR models (~900 MB, downloaded on the first run), `/state` holds the registry.

## Commands

```bash
mokuro-watcher run              # loop (default)
mokuro-watcher once             # scan once and exit
mokuro-watcher force <Series>   # queue a series' old backlog (and close its new-series window)
mokuro-watcher fix-titles       # fix title/title_uuid of the already published .mokuro files (idempotent)
mokuro-watcher import <Series> <folder>  # publish the folder's .mokuro files (see above)
```

Inside the container: `docker exec mokuro-watcher mokuro-watcher force Skip_to_Loafer`.

## Tests

```bash
uvx --python 3.11 --with pytest pytest -q
```

## Release

Tag push → tests → image `ghcr.io/diogovalentte/mokuro-watcher:{tag,latest}` → redeploy webhook of the `mokuro-watcher` stack in Portainer.
