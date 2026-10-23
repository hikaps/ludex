from __future__ import annotations

import argparse
import csv
import io
import getpass
import glob
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .accounts import add_account, get_account, list_accounts, remove_account
from .errors import LudexError
from .game_settings import get_prefix_root, get_settings, pick_copy, set_prefix_root, update_settings
from .runners import find_runners
from .find import find_games, owned_keys
from .installed import installed_keys
from .acquire import acquire_game
from .launch import install_game, launch_game, prepare_launch
from .library import resolve_game, delete_account_records, export_games, dismiss_review, get_game, list_games, list_review, merge_games, run_import
from .loader import load_providers
from .paths import state_paths
from .plugins import CommandContext, CommandResult, Provider
from .storage import connect, writer_lock
from .switches import SWITCHES, get_switch, set_switch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ludex", description="Headless library of the games you own across stores.")
    parser.add_argument("--version", action="version", version=f"ludex {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output (before the subcommand)")
    commands = parser.add_subparsers(dest="command", metavar="command")

    commands.add_parser("providers", help="list available providers and their capabilities")

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
    listing.add_argument("--installed", action="store_true", help="only games installed on this machine")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)

    show = commands.add_parser("show", help="show one game")
    show.add_argument("game", help="game id or title")

    find = commands.add_parser("find", help="search the stores' catalogs (uses the network)")
    find.add_argument("query")

    launch = commands.add_parser("launch", help="start a game through its store's client")
    launch.add_argument("game", help="game id or title")
    launch.add_argument("--store", help="store to launch from when several can")
    launch.add_argument("--dry-run", action="store_true", help="show how the game would be started and do not start it")

    install = commands.add_parser("install", help="ask the owning store's client to install a game you own")
    install.add_argument("game", help="game id or title")
    install.add_argument("--store", help="store to install from when several can")

    acquire = commands.add_parser("acquire", help="ask a provider to fetch a game into a directory")
    acquire.add_argument("store")
    acquire.add_argument("store_id")
    acquire.add_argument("--to", required=True, help="destination directory")
    acquire.add_argument("--title", default="", help="game title, if the provider wants one")

    commands.add_parser("runners", help="list detected Proton builds")

    config = commands.add_parser(
        "config",
        help="show or change global settings: prefix_dir (folder for default Wine prefixes), "
        "steam_shortcuts and heroic_sideload (yes/no; no removes those games from the library)",
    )
    config.add_argument("key", nargs="?", choices=sorted(_SETTINGS), help="setting to show or change")
    config.add_argument("value", nargs="?", help="new value: an absolute folder, or yes/no")
    config.add_argument("--reset", action="store_true", help="go back to the built-in value")

    game = commands.add_parser("game", help="per-game launch settings (runner, prefix, executable, environment)")
    game_commands = game.add_subparsers(dest="game_command", metavar="action")
    game_show = game_commands.add_parser("show", help="show a game's launch settings")
    game_show.add_argument("game", help="game id or title")
    game_show.add_argument("--store", help="store whose copy to use when several exist")
    game_set = game_commands.add_parser("set", help="change a game's launch settings")
    game_set.add_argument("game", help="game id or title")
    game_set.add_argument("--store", help="store whose copy to use when several exist")
    game_set.add_argument("--runner", help="runner name from 'ludex runners', or the path of a Proton folder")
    game_set.add_argument("--prefix", help="absolute path of the Wine prefix folder")
    game_set.add_argument("--exe", help="executable, relative to the game folder or absolute")
    game_set.add_argument("--args", help="arguments passed to the game, one quoted string; write --args='-w' when it starts with a dash")
    game_set.add_argument("--env", action="append", default=[], metavar="NAME=VALUE", help="environment variable (repeatable)")
    game_set.add_argument("--unset-env", action="append", default=[], metavar="NAME", help="remove an environment variable (repeatable)")
    game_set.add_argument("--clear", action="store_true", help="reset all settings first")

    commands.add_parser("tui", help="browse, search and launch games in the terminal")

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


def _plugin(sources: dict[str, Provider], problems: dict[str, str], name: str) -> Provider:
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


def _cmd_providers(args: argparse.Namespace) -> tuple[object, str]:
    sources, problems = load_providers()
    data = {
        "providers": [
            {
                "name": plugin.name,
                "help": plugin.help,
                "capabilities": list(plugin.capabilities),
                "commands": [{"name": c.name, "help": c.help} for c in plugin.commands],
                "fields": [{"name": f.name, "help": f.help, "secret": f.secret, "optional": f.optional} for f in plugin.config_fields],
            }
            for _, plugin in sorted(sources.items())
        ],
        "problems": dict(sorted(problems.items())),
    }
    lines = []
    for p in data["providers"]:
        lines.append(f"{p['name']}  [{', '.join(p['capabilities'])}]  {p['help']}")
        lines += [f"  ludex {p['name']} {c['name']}  {c['help']}" for c in p["commands"]]
    lines += [f"problem: {name}: {reason}" for name, reason in data["problems"].items()]
    return data, "\n".join(lines) if lines else "no providers available"


def _cmd_account_add(args: argparse.Namespace) -> tuple[object, str]:
    sources, problems = load_providers()
    plugin = _plugin(sources, problems, args.source)
    if plugin.fetch is None:
        raise LudexError("no_owned_capability", f"provider {plugin.name} cannot list owned games, so it has no accounts")
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
    paths = state_paths()
    try:
        account = get_account(paths, args.name)
    except LudexError as exc:
        if exc.code != "account_not_found" or ":" in args.name:
            raise
        # an account already gone from the file can still have stale records: clear those
        name, scope = args.name, {"keep_stores": [s for n, s in list_accounts(paths) if n == args.name]}
    else:
        remove_account(paths, args.name)
        name, scope = account.name, {"store": account.source}
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            changed = delete_account_records(conn, name, **scope)
        finally:
            conn.close()
    if "keep_stores" in scope and not changed:
        raise LudexError("account_not_found", f"account {args.name} not found")
    return {"account": args.name, "records_removed": changed}, f"removed account {args.name}; deleted {changed} records"


def _import_one(conn: Any, paths: Any, sources: dict[str, Provider], problems: dict[str, str], name: str) -> dict[str, Any]:
    account = get_account(paths, name)
    plugin = _plugin(sources, problems, account.source)
    summary = run_import(conn, account.name, plugin, account.config)
    return {"account": account.name, "source": account.source, "ok": True, **summary.as_dict()}


def _cmd_import(args: argparse.Namespace) -> tuple[object, str, int]:
    paths = state_paths()
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            sources, problems = load_providers()
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
    sources, problems = load_providers()
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
    only = None
    if args.installed:
        providers, _ = load_providers()
        only, problems = installed_keys(paths, providers)
        for ref, reason in sorted(problems.items()):
            print(f"warning: {ref}: {reason}", file=sys.stderr)
    conn = connect(paths.database)
    try:
        games = list_games(
            conn,
            only=only,
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
        game = get_game(conn, resolve_game(conn, args.game))
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


def _cmd_find(args: argparse.Namespace) -> tuple[object, str]:
    providers, _ = load_providers()
    conn = connect(state_paths().database)
    try:
        owned = owned_keys(conn)
    finally:
        conn.close()
    hits, problems = find_games(providers, args.query, owned)
    for name, reason in sorted(problems.items()):
        print(f"warning: {name}: {reason}", file=sys.stderr)
    lines = [
        f"[{h['store']}] {h['title']}  {h['price'] or '-'}  {h['url']}" + ("  (owned)" if h["owned"] else "") for h in hits
    ]
    return {"hits": hits, "problems": problems}, "\n".join(lines) if lines else "no results"


def _cmd_install(args: argparse.Namespace) -> tuple[object, str]:
    providers, _ = load_providers()
    conn = connect(state_paths().database)
    try:
        game_id = resolve_game(conn, args.game)
        target = install_game(conn, providers, game_id, args.store)
    finally:
        conn.close()
    return {"id": game_id, "install": target}, f"asking the client to install {target}"


def _cmd_acquire(args: argparse.Namespace) -> tuple[object, str]:
    providers, _ = load_providers()
    result = acquire_game(
        providers, args.store, args.store_id, args.title, Path(args.to), lambda message: print(message, file=sys.stderr)
    )
    data = {"directory": str(result.directory), "hints": dict(result.hints)}
    hints = "".join(f"\n  {key}={value}" for key, value in sorted(result.hints.items()))
    return data, f"acquired into {result.directory}{hints}"


def _cmd_runners(args: argparse.Namespace) -> tuple[object, str]:
    runners = [{"name": r.name, "path": str(r.path), "origin": r.origin} for r in find_runners()]
    lines = [f"{r['name']}  ({r['origin']})  {r['path']}" for r in runners]
    return {"runners": runners}, "\n".join(lines) if lines else "no Proton builds found"


_SETTINGS = {"prefix_dir", *SWITCHES}
_YES_NO = {"yes": True, "on": True, "true": True, "no": False, "off": False, "false": False}


def _cmd_config(args: argparse.Namespace) -> tuple[object, str]:
    paths = state_paths()
    default = paths.root / "prefixes"
    changing = bool(args.value or args.reset)
    if changing and not args.key:
        raise LudexError("invalid_setting", "name the setting to change")
    if args.value and args.reset:
        raise LudexError("invalid_setting", "give a value or --reset, not both")
    if args.reset and args.key in SWITCHES:
        raise LudexError("invalid_setting", f"{args.key} has no default to reset to; set yes or no")
    if args.value and args.key in SWITCHES and args.value.lower() not in _YES_NO:
        raise LudexError("invalid_setting", f"{args.key} takes yes or no")
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            if changing and args.key == "prefix_dir":
                set_prefix_root(conn, None if args.reset else args.value)
            elif changing:
                sources, _ = load_providers()
                set_switch(paths, conn, sources, args.key, _YES_NO[args.value.lower()])
            folder = get_prefix_root(conn, default)
        finally:
            conn.close()
    data: dict[str, Any] = {"prefix_dir": str(folder), **{key: get_switch(paths, key) for key in sorted(SWITCHES)}}
    lines = [f"prefix_dir: {folder}" + (" (default)" if folder == default else "")]
    lines += [f"{key}: {'yes' if data[key] else 'no'}" for key in sorted(SWITCHES)]
    if args.key:
        lines = [line for line in lines if line.startswith(args.key + ":")]
    return data, "\n".join(lines)


def _settings_view(conn: Any, game_id: int, store: str | None) -> tuple[dict[str, Any], str]:
    copy = pick_copy(conn, game_id, store)
    data = {"id": game_id, "store": copy[0], "store_id": copy[1], **get_settings(conn, *copy).as_dict()}
    lines = [f"{copy[0]}:{copy[1]}"] + [
        f"  {key}: {data[key] if data[key] not in (None, [], {}) else '-'}" for key in ("runner", "prefix", "executable", "args", "env")
    ]
    return data, "\n".join(lines)


def _cmd_game_show(args: argparse.Namespace) -> tuple[object, str]:
    conn = connect(state_paths().database)
    try:
        return _settings_view(conn, resolve_game(conn, args.game), args.store)
    finally:
        conn.close()


def _cmd_game_set(args: argparse.Namespace) -> tuple[object, str]:
    env: dict[str, str] = {}
    for item in args.env:
        name, sep, value = item.partition("=")
        if not sep:
            raise LudexError("invalid_setting", "--env needs NAME=VALUE")
        env[name] = value
    try:
        extra = shlex.split(args.args) if args.args is not None else None
    except ValueError:
        raise LudexError("invalid_setting", "--args has unbalanced quotes") from None
    paths = state_paths()
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            game_id = resolve_game(conn, args.game)
            copy = pick_copy(conn, game_id, args.store)
            update_settings(
                conn, *copy, runner=args.runner, prefix=args.prefix, executable=args.exe, args=extra,
                env=env, unset_env=args.unset_env, clear=args.clear,
            )
            return _settings_view(conn, game_id, args.store)
        finally:
            conn.close()


def _cmd_launch(args: argparse.Namespace) -> tuple[object, str]:
    sources, _ = load_providers()
    paths = state_paths()
    conn = connect(paths.database)
    config_for = lambda store, account: get_account(paths, f"{store}:{account}").config
    try:
        game_id = resolve_game(conn, args.game)
        if args.dry_run:
            plan = prepare_launch(conn, sources, game_id, args.store, config_for, get_prefix_root(conn, paths.root / "prefixes"))
            data = {
                "id": game_id, "target": plan.target, "url": plan.url, "argv": list(plan.argv),
                "cwd": str(plan.cwd) if plan.cwd else None, "env": sorted(plan.env),  # names only: values may be secrets
            }
            how = plan.url or shlex.join(plan.argv)
            env = f"  [env: {', '.join(data['env'])}]" if data["env"] else ""
            return data, f"would start {plan.target}: {how}{env}"
        target = launch_game(conn, sources, game_id, args.store, config_for, get_prefix_root(conn, paths.root / "prefixes"))
    finally:
        conn.close()
    return {"id": game_id, "launched": target}, f"launching {target}"


def _cmd_tui(args: argparse.Namespace) -> tuple[object, str]:
    from .tui import LudexApp

    sources, _ = load_providers()
    paths = state_paths()
    LudexApp(
        paths.database, sources, lambda: installed_keys(paths, sources)[0],
        lambda store, account: get_account(paths, f"{store}:{account}").config,
        paths.root / "prefixes", paths.import_lock, paths,
    ).run()
    return {}, ""


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
    ("providers", None): _cmd_providers,
    ("setup", None): _cmd_setup,
    ("account", "add"): _cmd_account_add,
    ("account", "ls"): _cmd_account_ls,
    ("account", "rm"): _cmd_account_rm,
    ("import", None): _cmd_import,
    ("ls", None): _cmd_ls,
    ("show", None): _cmd_show,
    ("find", None): _cmd_find,
    ("install", None): _cmd_install,
    ("acquire", None): _cmd_acquire,
    ("runners", None): _cmd_runners,
    ("config", None): _cmd_config,
    ("game", "show"): _cmd_game_show,
    ("game", "set"): _cmd_game_set,
    ("launch", None): _cmd_launch,
    ("tui", None): _cmd_tui,
}


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    handler = _HANDLERS[(args.command, getattr(args, "account_command", None) or getattr(args, "game_command", None))]
    return _execute(args.json, lambda: handler(args))


def _execute(as_json: bool, call: Any) -> int:
    status = 0
    try:
        outcome = call()
        data, human = outcome[0], outcome[1]
        if len(outcome) == 3:
            status = outcome[2]
    except LudexError as exc:
        error = exc
    except PermissionError as exc:
        error = LudexError("state_unavailable", str(exc))
    else:
        if as_json:
            _emit_json(True, data)
        else:
            if human:
                print(human)
        return status
    if as_json:
        _emit_json(False, error=error)
    else:
        print(f"error: {error.message}", file=sys.stderr)
    return 1


def _plugin_command(argv: list[str]) -> int | None:
    """Run ``ludex <provider> <command> ...`` when the first word names a provider with commands."""
    as_json = bool(argv) and argv[0] == "--json"
    words = argv[1:] if as_json else argv
    if not words or words[0].startswith("-") or words[0] in {key[0] for key in _HANDLERS}:
        return None
    providers, _ = load_providers()
    provider = providers.get(words[0])
    if provider is None or not provider.commands:
        return None

    def call() -> tuple[object, str]:
        commands = {c.name: c for c in provider.commands}
        if len(words) < 2 or words[1] not in commands:
            raise LudexError("unknown_command", f"{provider.name} commands: {', '.join(sorted(commands))}")
        command = commands[words[1]]
        paths = state_paths()
        with writer_lock(paths.import_lock):
            conn = connect(paths.database)
            try:
                result = command.run(CommandContext(conn, providers), words[2:])
            except (LudexError, SystemExit):
                raise
            except Exception as exc:
                raise LudexError("command_failed", f"{provider.name} {command.name} failed ({type(exc).__name__})") from None
            finally:
                conn.close()
        if not isinstance(result, CommandResult):
            raise LudexError("command_failed", f"{provider.name} {command.name} returned an invalid result")
        return result.data, result.text

    previous_umask = os.umask(0o077)
    try:
        return _execute(as_json, call)
    except SystemExit as exc:  # the plugin's own argparse: -h exits 0, usage errors 2
        return exc.code if isinstance(exc.code, int) else 2
    finally:
        os.umask(previous_umask)


def main(argv: list[str] | None = None) -> int:
    handled = _plugin_command(list(sys.argv[1:] if argv is None else argv))
    if handled is not None:
        return handled
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "account" and args.account_command is None:
        parser.error("account requires an action: add, ls or rm")
    if args.command == "game" and args.game_command is None:
        parser.error("game requires an action: show or set")
    if args.command == "import" and not args.all and not args.account:
        parser.error("import requires an account name or --all")
    if args.command == "import" and args.all and args.account:
        parser.error("import takes an account name or --all, not both")
    previous_umask = os.umask(0o077)
    try:
        return _run(parser, args)
    finally:
        os.umask(previous_umask)
