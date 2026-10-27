from __future__ import annotations

import argparse
from logging.handlers import RotatingFileHandler
import logging
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(prog="MemuMusic", description="Independent desktop music player")
    parser.add_argument("--serve", action="store_true", help="Run the local UI without opening a desktop window")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    from . import __version__
    if args.version:
        print(f"MemuMusic {__version__}")
        return
    if args.data_dir:
        os.environ["MEMUMUSIC_DATA_DIR"] = str(args.data_dir.resolve())
    from .paths import data_dir
    handler = RotatingFileHandler(data_dir() / "memumusic.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        if args.serve:
            from .server import LocalServer
            server = LocalServer(args.port).start()
            if args.ready_file:
                args.ready_file.write_text(server.url, encoding="utf-8")
            if __import__("sys").stdout:
                print(server.url, flush=True)
            try:
                while server.thread.is_alive():
                    time.sleep(.2)
            except KeyboardInterrupt:
                pass
            finally:
                server.stop()
        else:
            from .desktop import run
            run()
    except Exception as exc:
        logging.exception("Application failed")
        if os.name == "nt" and not args.serve:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"{exc}\n\nЖурнал / Log: {data_dir() / 'memumusic.log'}", "MemuMusic", 0x10)
        raise


if __name__ == "__main__":
    main()
