import argparse
import logging
from pathlib import Path

from .config import Config
from .importer import InvalidImport, import_mokuro
from .processor import fix_published_titles
from .registry import Registry
from .watcher import ensure_dirs, force_series, process_pending, run_forever, sync_library


def main() -> None:
    parser = argparse.ArgumentParser(prog="mokuro-watcher")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="scan and process in a loop (default)")
    sub.add_parser("once", help="scan once and exit")
    force = sub.add_parser("force", help="queue every raw chapter of a series")
    force.add_argument("series", help="name of the series folder in the library")
    sub.add_parser("fix-titles", help="fix title and title_uuid of the already published .mokuro files")
    imp = sub.add_parser("import", help="publish .mokuro files made outside the watcher for a series")
    imp.add_argument("series", help="name of the series folder in the library")
    imp.add_argument("directory", type=Path, help="folder with the .mokuro files")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env()
    registry = Registry(config.state_db)
    ensure_dirs(config)

    if args.command == "import":
        files = [(p.name, p.read_bytes()) for p in sorted(args.directory.glob("*.mokuro"))]
        try:
            results = import_mokuro(config, registry, args.series, files)
        except InvalidImport as e:
            raise SystemExit(str(e)) from e
        for r in results:
            print(f"{r.status:9} {r.name} {r.detail}".rstrip())
        print(f"{sum(r.status != 'rejected' for r in results)}/{len(results)} published")
    elif args.command == "fix-titles":
        changed = fix_published_titles(config.output_dir)
        print(f"{changed} .mokuro files fixed")
    elif args.command == "force":
        queued = force_series(config, registry, args.series)
        print(f"{queued} chapters queued; the loop processes them on the next scan")
    elif args.command == "once":
        sync_library(config, registry)
        process_pending(config, registry)
    else:
        run_forever(config, registry)


if __name__ == "__main__":
    main()
