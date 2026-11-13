"""Start: python -m issuebot   (Konfiguration ueber Umgebungsvariablen, siehe .env.example)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from .bot import Bot
from .config import Config, ConfigError
from .github import GitHub
from .matrix import Matrix
from .store import Store

log = logging.getLogger("issuebot")


async def amain() -> int:
    try:
        cfg = Config.from_env()
    except ConfigError as exc:
        print(f"Konfiguration unvollständig: {exc} (siehe .env.example)", file=sys.stderr)
        return 2
    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    os.makedirs(cfg.data_dir, exist_ok=True)

    store = Store(cfg.db_path)
    store.prune()
    matrix = Matrix(cfg)
    bot = Bot(cfg, matrix, GitHub(cfg.github_token, api=cfg.github_api), store)
    matrix.on_text = bot.on_text

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await matrix.login()
        await matrix.first_sync()
        log.info("Bereit. Ziel-Repos: %s", ", ".join(f"{k}={v}" for k, v in cfg.repos.items()))
        sync = asyncio.create_task(matrix.run())
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({sync, waiter}, return_when=asyncio.FIRST_COMPLETED)
        matrix.stop()
        if sync in done and sync.exception():
            log.error("Sync-Loop abgestürzt", exc_info=sync.exception())
            return 1
        sync.cancel()
    finally:
        await matrix.close()
        store.close()
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(amain()))
    except KeyboardInterrupt:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
