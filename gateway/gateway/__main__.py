"""python -m gateway serve [--host H] [--port P] [--mock]   |   python -m gateway admin ..."""
from __future__ import annotations

import argparse
import logging
import os
import sys


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "admin":
        from .admin import run
        return run(argv[1:])
    p = argparse.ArgumentParser(prog="gateway")
    p.add_argument("cmd", choices=["serve"])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--mock", action="store_true", help="Giả lập G-Labs (để test)")
    a = p.parse_args(argv)
    if a.mock:
        os.environ["GW_MOCK"] = "1"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
