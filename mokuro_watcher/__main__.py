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
    sub.add_parser("run", help="varre e processa em loop (padrão)")
    sub.add_parser("once", help="uma varredura e sai")
    force = sub.add_parser("force", help="enfileira os capítulos raw de uma série inteira")
    force.add_argument("series", help="nome da pasta da série na biblioteca")
    sub.add_parser("fix-titles", help="corrige título e title_uuid dos .mokuro já publicados")
    imp = sub.add_parser("import", help="publica .mokuro gerados fora do watcher para uma série")
    imp.add_argument("series", help="nome da pasta da série na biblioteca")
    imp.add_argument("directory", type=Path, help="pasta com os arquivos .mokuro")
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
        print(f"{sum(r.status != 'rejected' for r in results)}/{len(results)} publicados")
    elif args.command == "fix-titles":
        changed = fix_published_titles(config.output_dir)
        print(f"{changed} arquivos .mokuro corrigidos")
    elif args.command == "force":
        queued = force_series(config, registry, args.series)
        print(f"{queued} capítulos enfileirados; o loop processa na próxima varredura")
    elif args.command == "once":
        sync_library(config, registry)
        process_pending(config, registry)
    else:
        run_forever(config, registry)


if __name__ == "__main__":
    main()
