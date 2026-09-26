import argparse
import logging

from .config import Config
from .registry import Registry
from .watcher import ensure_dirs, force_series, process_pending, run_forever, sync_library


def main() -> None:
    parser = argparse.ArgumentParser(prog="mokuro-watcher")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="varre e processa em loop (padrão)")
    sub.add_parser("once", help="uma varredura e sai")
    force = sub.add_parser("force", help="enfileira os capítulos raw de uma série inteira")
    force.add_argument("series", help="nome da pasta da série na biblioteca")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env()
    registry = Registry(config.state_db)
    ensure_dirs(config)

    if args.command == "force":
        queued = force_series(config, registry, args.series)
        print(f"{queued} capítulos enfileirados; o loop processa na próxima varredura")
    elif args.command == "once":
        sync_library(config, registry)
        process_pending(config, registry)
    else:
        run_forever(config, registry)


if __name__ == "__main__":
    main()
