"""The detached process behind a ``download`` job: ``python -m ludex._acquire_worker STORE ID --to DIR [--title T]``.

Private to the core; it exists so a download never depends on a frontend being installed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .acquire import acquire_game, format_acquired, job_reporter
from .errors import LudexError
from .loader import load_providers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ludex._acquire_worker")
    parser.add_argument("store")
    parser.add_argument("store_id")
    parser.add_argument("--to", required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args(argv)
    previous_umask = os.umask(0o077)
    try:
        providers, _ = load_providers()
        result = acquire_game(
            providers, args.store, args.store_id, args.title, Path(args.to), job_reporter(lambda message: print(message, file=sys.stderr))
        )
    except LudexError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        os.umask(previous_umask)
    print(format_acquired(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
