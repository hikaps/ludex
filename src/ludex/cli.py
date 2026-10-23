from __future__ import annotations

import argparse
import csv
import io
import getpass
import glob
import json
import os
import sys
from typing import Any

from . import __version__
from .accounts import add_account, get_account, list_accounts, remove_account
from .errors import LudexError
from .library import export_games, dismiss_review, get_game, list_games, list_review, merge_games, run_import
from .loader import load_sources
from .paths import state_paths
from .plugins import SourcePlugin
from .storage import connect, writer_lock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ludex", description="Headless library of the games you own across stores.")
    parser.add_argument("--version", action="version", version=f"ludex {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output (before the subcommand)")
    commands = parser.add_subparsers(dest="command", metavar="command")

    commands.add_parser("sources", help="list available source plugins")

    account = commands.add_parser("account", help="manage store accounts")
    account_commands = account.add_subparsers(dest="account_command", metavar="action")
    add = account_commands.add_parser("add", help="add an account")
    add.add_argument("source")
    add.add_argument("name")
    add.add_argument("--set", dest="fields", action="append", default=[], metavar="KEY=VALUE", help="non-secret field value")
    account_commands.add_parser("ls", help="list accounts")
    remove = account_commands.add_parser("rm", help="remove an account")
    remove.add_argument("name")

    setup = commands.add_parser("setup", help="guided: add an account for a source and import it")
    setup.add_argument("source", nargs="?")
    setup.add_argument("--name", help="account name (default: the source name)")

    imp = commands.add_parser("import", help="import owned games from an account")
    imp.add_argument("account", nargs="?")
    imp.add_argument("--all", action="store_true", help="import every account")

    listing = commands.add_parser("ls", help="list or search games")
    listing.add_argument("query", nargs="?")
    listing.add_argument("--store")
    listing.add_argument("--account")
    listing.add_argument("--removed", action="store_true", help="include removed games")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)

    show = commands.add_parser("show", help="show one game")
    show.add_argument("id", type=int)

    review = commands.add_parser("review", help="list title matches that need a decision")
    review.add_argument("--dismiss", type=int, metavar="ID", help="keep this item's game separate and drop it from the list")

    export = commands.add_parser("export", help="write the library to stdout as JSON or CSV")
    export.add_argument("--format", choices=("json", "csv"), default="json")
    export.add_argument("--removed", action="store_true", help="include removed records")

    merge = commands.add_parser("merge", help="merge game DROP into game KEEP")
    merge.add_argument("keep", type=int)
    merge.add_argument("drop", type=int)
    return parser


def _emit_json(ok: bool, data: object | None = None, error: LudexError | None = None) -> None:
    if ok:
        payload: dict[str, Any] = {"ok": True, "data": data}
        target = sys.stdout
    else:
        assert error is not None
        payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
        target = sys.stderr
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), file=target)


def _plugin(sources: dict[str, SourcePlugin], problems: dict[str, str], name: str) -> SourcePlugin:
    plugin = sources.get(name)
    if plugin is None:
        detail = f" ({problems[name]})" if name in problems else ""
        raise LudexError("unknown_source", f"unknown source {name}{detail}")
    return plugin


def _complete_path(text: str, state: int) -> str | None:
    matches = sorted(glob.glob(os.path.expanduser(text) + "*"))
    matches = [m + "/" if os.path.isdir(m) else m for m in matches]
    return matches[state] if state < len(matches) else None


def _input_path(prompt: str) -> str:
    try:
        import readline
    except ImportError:  # no readline: plain prompt
        return input(prompt)
    readline.set_completer(_complete_path)
    readline.set_completer_delims(" \t\n;")
    readline.parse_and_bind("bind ^I rl_complete" if "libedit" in (readline.__doc__ or "") else "tab: complete")
    try:
        return input(prompt)
    finally:
        readline.set_completer(None)


def _read_value(prompt: str, secret: bool, path: bool = False) -> str:
    if sys.stdin.isatty():
        value = getpass.getpass(prompt) if secret else _input_path(prompt) if path else input(prompt)
    else:
        value = sys.stdin.readline().rstrip("\r\n")
    return value


def _cmd_sources(args: argparse.Namespace) -> tuple[object, str]:
    sources, problems = load_sources()
    data = {
        "sources": [
            {
                "name": plugin.name,
                "help": plugin.help,
                "fields": [{"name": f.name, "help": f.help, "secret": f.secret, "optional": f.optional} for f in plugin.config_fields],
            }
            for _, plugin in sorted(sources.items())
        ],
        "problems": dict(sorted(problems.items())),
    }
    lines = [f"{s['name']}  {s['help']}" for s in data["sources"]]
    lines += [f"problem: {name}: {reason}" for name, reason in data["problems"].items()]
    return data, "\n".join(lines) if lines else "no sources available"


def _cmd_account_add(args: argparse.Namespace) -> tuple[object, str]:
    sources, problems = load_sources()
    plugin = _plugin(sources, problems, args.source)
    fields = {f.name: f for f in plugin.config_fields}
    config: dict[str, str] = {}
    for item in args.fields:
        key, separator, value = item.partition("=")
        if not separator:
            raise LudexError("invalid_field", "--set expects KEY=VALUE")
        if key not in fields:
            raise LudexError("unknown_field", f"source {plugin.name} has no field {key}")
        if fields[key].secret:
            raise LudexError("secret_via_argv", f"field {key} is secret; enter it at the prompt or on stdin")
        if not value:
            raise LudexError("empty_value", f"field {key} must not be empty")
        config[key] = value
    paths = state_paths()
    for field in plugin.config_fields:
        if field.name in config:
            continue
        value = _read_value(f"{field.name} ({field.help}): ", field.secret, field.path)
        if not value and not field.optional:
            raise LudexError("empty_value", f"field {field.name} must not be empty")
        if value:
            config[field.name] = value
    add_account(paths, args.name, plugin.name, config)
    return {"account": args.name, "source": plugin.name}, f"added account {args.name} ({plugin.name})"


def _cmd_account_ls(args: argparse.Namespace) -> tuple[object, str]:
    accounts = [{"name": name, "source": source} for name, source in list_accounts(state_paths())]
    lines = [f"{a['name']}  {a['source']}" for a in accounts]
    return {"accounts": accounts}, "\n".join(lines) if lines else "no accounts"


def _cmd_account_rm(args: argparse.Namespace) -> tuple[object, str]:
    remove_account(state_paths(), args.name)
    return {"account": args.name}, f"removed account {args.name}"


def _import_one(conn: Any, paths: Any, sources: dict[str, SourcePlugin], problems: dict[str, str], name: str) -> dict[str, Any]:
    account = get_account(paths, name)
    plugin = _plugin(sources, problems, account.source)
    summary = run_import(conn, account.name, plugin, account.config)
    return {"account": account.name, "source": account.source, "ok": True, **summary.as_dict()}


def _cmd_import(args: argparse.Namespace) -> tuple[object, str, int]:
    paths = state_paths()
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            sources, problems = load_sources()
            if not args.all:
                result = _import_one(conn, paths, sources, problems, args.account)
                return {k: v for k, v in result.items() if k != "ok"}, _import_line(result), 0
            results: list[dict[str, Any]] = []
            for name, source in list_accounts(paths):
                try:
                    results.append(_import_one(conn, paths, sources, problems, f"{source}:{name}"))
                except LudexError as exc:
                    results.append({"account": name, "source": source, "ok": False, "error": {"code": exc.code, "message": exc.message}})
        finally:
            conn.close()
    lines = [_import_line(r) if r["ok"] else f"{r['source']}:{r['account']}: error: {r['error']['message']}" for r in results]
    status = 1 if any(not r["ok"] for r in results) else 0
    return {"results": results}, "\n".join(lines) if lines else "no accounts", status


def _ask(prompt: str, default: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return _read_value("", False) or default


def _cmd_setup(args: argparse.Namespace) -> tuple[object, str]:
    sources, problems = load_sources()
    if not sources:
        raise LudexError("no_sources", "no source plugins are available")
    names = sorted(sources)
    source = args.source or _ask(f"source ({', '.join(names)}) [{names[0]}]: ", names[0])
    plugin = _plugin(sources, problems, source)
    name = args.name or _ask(f"account name [{source}]: ", source)
    if (name, source) in list_accounts(state_paths()):
        raise LudexError("account_exists", f"account {name} already exists for source {source}")
    print(f"{plugin.help}\nEnter skips optional fields.", file=sys.stderr)
    added = _cmd_account_add(argparse.Namespace(source=source, name=name, fields=[]))
    try:
        data, human, _ = _cmd_import(argparse.Namespace(account=f"{source}:{name}", all=False))
    except LudexError as exc:
        raise LudexError(exc.code, f"{exc.message}; account {name} was saved, fix the cause and run: ludex import {source}:{name}") from None
    return data, f"{added[1]}\n{human}"


def _import_line(result: dict[str, Any]) -> str:
    note = f" [{result['mode']}]" if result["mode"] else ""
    if not result["complete"]:
        note += " partial: nothing removed"
    return (
        f"{result['source']}:{result['account']}: {result['added']} added, {result['restored']} restored, "
        f"{result['removed']} removed, {result['total']} total{note}"
    )


def _cmd_ls(args: argparse.Namespace) -> tuple[object, str]:
    if args.limit < 1 or args.offset < 0:
        raise LudexError("invalid_paging", "--limit must be at least 1 and --offset must not be negative")
    paths = state_paths()
    conn = connect(paths.database)
    try:
        games = list_games(
            conn,
            query=args.query,
            store=args.store,
            account=args.account,
            include_removed=args.removed,
            limit=args.limit,
            offset=args.offset,
        )
    finally:
        conn.close()
    id_width = max((len(str(g["id"])) for g in games), default=0)
    title_width = max((len(g["title"]) for g in games), default=0)
    lines = [
        f"{g['id']:>{id_width}}  {g['title']:<{title_width}}  [{', '.join(g['stores'])}]" + (" (removed)" if g["removed"] else "")
        for g in games
    ]
    return {"games": games, "limit": args.limit, "offset": args.offset}, "\n".join(lines) if lines else "no games"


def _cmd_show(args: argparse.Namespace) -> tuple[object, str]:
    paths = state_paths()
    conn = connect(paths.database)
    try:
        game = get_game(conn, args.id)
    finally:
        conn.close()
    lines = [f"{game['id']}  {game['title']}  (added {game['created_at']})"]
    for o in game["ownership"]:
        state = "removed" if o["removed"] else "owned"
        lines.append(
            f"  {o['store']}:{o['store_id']}  account={o['account']}  {o['title']}  "
            f"{state}  first_seen={o['first_seen']}  last_seen={o['last_seen']}"
        )
    return game, "\n".join(lines)


def _cmd_review(args: argparse.Namespace) -> tuple[object, str]:
    paths = state_paths()
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            if args.dismiss is not None:
                dismiss_review(conn, args.dismiss)
                return {"dismissed": args.dismiss}, f"dismissed review item {args.dismiss}"
            items = list_review(conn)
        finally:
            conn.close()
    lines = []
    for item in items:
        lines.append(f"{item['id']}  game {item['game_id']}: {item['title']} [{item['store']}] may be the same as:")
        lines += [f"    game {c['id']}: {c['title']}" for c in item["candidates"]]
    return {"items": items}, "\n".join(lines) if lines else "nothing to review"


def _cmd_merge(args: argparse.Namespace) -> tuple[object, str]:
    paths = state_paths()
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            moved = merge_games(conn, args.keep, args.drop)
        finally:
            conn.close()
    return {"keep": args.keep, "drop": args.drop, "moved": moved}, f"merged game {args.drop} into {args.keep} ({moved} records)"


_CSV_FIELDS = ("game_id", "title", "store", "store_id", "account", "removed", "first_seen", "last_seen")


def _cmd_export(args: argparse.Namespace) -> tuple[object, str]:
    conn = connect(state_paths().database)
    try:
        games = export_games(conn, include_removed=args.removed)
    finally:
        conn.close()
    if args.format == "json":
        return {"games": games}, json.dumps(games, ensure_ascii=False, indent=2)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(_CSV_FIELDS)
    for game in games:
        for o in game["ownership"]:
            writer.writerow([game["id"], o["title"], o["store"], o["store_id"], o["account"], int(o["removed"]), o["first_seen"], o["last_seen"]])
    return {"games": games}, out.getvalue().rstrip("\n")


_HANDLERS = {
    ("export", None): _cmd_export,
    ("review", None): _cmd_review,
    ("merge", None): _cmd_merge,
    ("sources", None): _cmd_sources,
    ("setup", None): _cmd_setup,
    ("account", "add"): _cmd_account_add,
    ("account", "ls"): _cmd_account_ls,
    ("account", "rm"): _cmd_account_rm,
    ("import", None): _cmd_import,
    ("ls", None): _cmd_ls,
    ("show", None): _cmd_show,
}


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    handler = _HANDLERS[(args.command, getattr(args, "account_command", None))]
    status = 0
    try:
        outcome = handler(args)
        data, human = outcome[0], outcome[1]
        if len(outcome) == 3:
            status = outcome[2]
    except LudexError as exc:
        error = exc
    except PermissionError as exc:
        error = LudexError("state_unavailable", str(exc))
    else:
        if args.json:
            _emit_json(True, data)
        else:
            print(human)
        return status
    if args.json:
        _emit_json(False, error=error)
    else:
        print(f"error: {error.message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "account" and args.account_command is None:
        parser.error("account requires an action: add, ls or rm")
    if args.command == "import" and not args.all and not args.account:
        parser.error("import requires an account name or --all")
    if args.command == "import" and args.all and args.account:
        parser.error("import takes an account name or --all, not both")
    previous_umask = os.umask(0o077)
    try:
        return _run(parser, args)
    finally:
        os.umask(previous_umask)
