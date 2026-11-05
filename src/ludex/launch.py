"""Start or install an owned game through its store's own client (the plugin supplies the URL)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .errors import LudexError
from .game_settings import get_settings
from .jobs import Job, start_job
from .library import get_game
from .runners import resolve_runner
from .plugins import Provider, SourceError


def open_url(url: str, what: str) -> None:
    """Hand ``url`` to the desktop (xdg-open); errors name ``what`` but never the URL."""
    try:
        subprocess.run(["xdg-open", url], check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise LudexError("launcher_missing", "xdg-open is not installed") from None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise LudexError("launch_failed", f"the system could not open {what}") from None


def _pick(conn, sources: Mapping[str, Provider], game_id: int, store: str | None, usable, verb: str) -> dict:
    game = get_game(conn, game_id)
    candidates = [o for o in game["ownership"] if not o["removed"] and usable(sources.get(o["store"]))]
    if store is not None:
        candidates = [o for o in candidates if o["store"] == store]
    stores = sorted({o["store"] for o in candidates})
    if not candidates:
        raise LudexError(f"not_{verb}able", f"game {game_id} has no owned copy that can be {verb}ed")
    if len(stores) > 1:
        raise LudexError(f"{verb}_ambiguous", f"game {game_id} can be {verb}ed from {', '.join(stores)}; pass --store")
    return candidates[0]


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    target: str
    url: str | None = None
    argv: tuple[str, ...] = ()
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)  # only what ludex adds to the inherited environment


def _prefix_for(store: str, store_id: str, root: Path) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{store}-{store_id}")[:60]
    return root / f"{slug}-{hashlib.sha1(f'{store}/{store_id}'.encode()).hexdigest()[:8]}"


def _executable(folder: Path, settings, runner_set: bool) -> Path | None:
    """The configured executable, or for a runner the folder's only .exe; None means 'let the provider decide'."""
    if settings.executable:
        exe = Path(settings.executable)
        if not exe.is_absolute():
            exe = (folder / exe).resolve()
            if not exe.is_relative_to(folder.resolve()):
                raise LudexError("launch_failed", "the configured executable is outside the game folder")
        if not exe.is_file():
            raise LudexError("launch_failed", f"the configured executable does not exist: {exe.name}")
        return exe
    if runner_set:
        exes = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".exe" and not f.name.lower().startswith("unins"))
        if len(exes) != 1:
            raise LudexError("launch_failed", "cannot tell which .exe to run; set one with 'ludex game set GAME --exe FILE'")
        return exes[0]
    return None


def prepare_launch(
    conn,
    sources: Mapping[str, Provider],
    game_id: int,
    store: str | None = None,
    config_for: Callable[[str, str], Mapping[str, str]] | None = None,
    prefix_root: Path | None = None,
) -> LaunchPlan:
    """Decide how to start a game without starting it. ``config_for(store, account)`` gives the account configuration and ``prefix_root`` the folder for default Wine prefixes."""
    record = _pick(
        conn, sources, game_id, store,
        lambda p: p is not None and (p.launch_url or p.launch_command or p.game_folder), "launch",
    )
    target = f"{record['store']}:{record['store_id']}"
    provider = sources[record["store"]]
    if provider.launch_url:
        return LaunchPlan(target, url=provider.launch_url(record["store_id"]))
    if config_for is None:
        raise LudexError("launch_failed", "this provider launches by command and no account configuration is available")
    settings = get_settings(conn, record["store"], record["store_id"])
    try:
        config = config_for(record["store"], record["account"])
        exe = None
        if provider.game_folder and (settings.executable or settings.runner):
            exe = _executable(Path(provider.game_folder(config, record["store_id"])), settings, bool(settings.runner))
        argv = [str(a) for a in provider.launch_command(config, record["store_id"])] if exe is None else [str(exe)]
    except LudexError:
        raise
    except Exception as exc:
        raise LudexError("launch_failed", f"provider {record['store']} could not build a launch command ({type(exc).__name__})") from None
    if not argv or not Path(argv[0]).is_absolute():
        raise LudexError("launch_failed", f"provider {record['store']} returned an invalid launch command")
    cwd = Path(argv[0]).parent
    env = dict(settings.env)
    if settings.runner:
        umu = shutil.which("umu-run")
        if umu is None:
            raise LudexError("launcher_missing", "umu-run is not installed (needed to run Windows games)")
        runner = resolve_runner(settings.runner)
        prefix = Path(settings.prefix) if settings.prefix else (_prefix_for(record["store"], record["store_id"], prefix_root) if prefix_root else None)
        if prefix is None:
            raise LudexError("launch_failed", "no prefix configured and no state folder to put one in")
        env.update({"WINEPREFIX": str(prefix), "PROTONPATH": str(runner.path), "GAMEID": env.get("GAMEID", "umu-0")})
        argv = [umu, *argv]
    return LaunchPlan(target, argv=(*argv, *settings.args), cwd=cwd, env=env)


def launch_game(
    conn,
    sources: Mapping[str, Provider],
    game_id: int,
    store: str | None = None,
    config_for: Callable[[str, str], Mapping[str, str]] | None = None,
    prefix_root: Path | None = None,
) -> str:
    """Start a game; returns ``store:store_id``. ponytail: no installed check, the client reports a game that is not installed; add when launch must pick installed copies."""
    plan = prepare_launch(conn, sources, game_id, store, config_for, prefix_root)
    if plan.url is not None:
        open_url(plan.url, f"the {plan.target.partition(':')[0]} client for this game")
        return plan.target
    if "WINEPREFIX" in plan.env:
        Path(plan.env["WINEPREFIX"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            list(plan.argv), cwd=plan.cwd, env={**os.environ, **plan.env}, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise LudexError("launch_failed", "the game could not be started (is it executable?)") from None
    return plan.target


def prepare_install(
    conn, sources: Mapping[str, Provider], game_id: int, store: str | None = None, config_for: Callable[[str, str], Mapping[str, str]] | None = None
) -> LaunchPlan:
    record = _pick(conn, sources, game_id, store, lambda p: p is not None and (p.install_url or p.install_command), "install")
    target = f"{record['store']}:{record['store_id']}"
    provider = sources[record["store"]]
    if provider.install_url:
        return LaunchPlan(target, url=provider.install_url(record["store_id"]))
    if config_for is None:
        raise LudexError("install_failed", "this provider installs by command and no account configuration is available")
    try:
        argv = [str(a) for a in provider.install_command(config_for(record["store"], record["account"]), record["store_id"])]
    except LudexError:
        raise
    except SourceError as exc:
        raise LudexError("install_failed", exc.message) from None
    except Exception as exc:
        raise LudexError("install_failed", f"provider {record['store']} could not build an install command ({type(exc).__name__})") from None
    if not argv or not Path(argv[0]).is_absolute():
        raise LudexError("install_failed", f"provider {record['store']} returned an invalid install command")
    return LaunchPlan(target, argv=tuple(argv))


def install_game(
    conn,
    sources: Mapping[str, Provider],
    game_id: int,
    store: str | None = None,
    config_for: Callable[[str, str], Mapping[str, str]] | None = None,
    log_dir: Path | None = None,
) -> tuple[str, Job | None]:
    """Ask the owning store's client to install a game you own, or start the plugin's install command in the background.

    Returns ``(store:store_id, job)``; the job (see ``ludex.jobs``) is ``None`` when a client was asked.
    """
    plan = prepare_install(conn, sources, game_id, store, config_for)
    if plan.url is not None:
        open_url(plan.url, f"the {plan.target.partition(':')[0]} client for this game")
        return plan.target, None
    if log_dir is None:
        raise LudexError("install_failed", "no state folder to write the install log in")
    return plan.target, start_job(conn, "install", game_id, plan.target, get_game(conn, game_id)["title"], list(plan.argv), log_dir)
