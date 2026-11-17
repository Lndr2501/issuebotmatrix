"""Start: python -m issuebot   (Konfiguration ueber Umgebungsvariablen, siehe .env.example)."""
from __future__ import annotations

import json
import logging
import os
import sys

from .bot import IssueBot
from .config import Config, ConfigError
from .github import GitHub
from .store import Store

log = logging.getLogger("issuebot")


def adopt_legacy_token(cfg: Config) -> bool:
    """Update vom alten Bot: dessen Token (Datei `access_token` im Store) wird in die
    `credentials.json` der Library uebernommen. Gleiches Geraet, gleiche E2EE-Schluessel, kein
    neues Geraet. Ist der Token ungueltig, meldet sich der Bot mit dem Passwort neu an."""
    legacy = os.path.join(cfg.store_path, "access_token")
    target = os.path.join(cfg.store_path, "credentials.json")
    if cfg.token or os.path.exists(target) or not os.path.exists(legacy):
        return False
    with open(legacy, encoding="utf-8") as fh:
        token = fh.read().strip()
    if not token:
        return False
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"homeserver": cfg.homeserver, "user_id": cfg.user, "device_id": cfg.device_id,
                   "access_token": token}, fh)
    log.info("Token des frueheren Bots uebernommen (Geraet %s)", cfg.device_id)
    return True


def build(cfg: Config) -> IssueBot:
    os.makedirs(cfg.data_dir, exist_ok=True)
    store = Store(cfg.db_path)
    store.prune()
    github = GitHub(cfg.github_token, api=cfg.github_api)
    researcher = None
    if cfg.ai_base_url:
        from .research import ChatAI, Researcher
        researcher = Researcher(
            ChatAI(cfg.ai_base_url, cfg.ai_model, cfg.ai_api_key, timeout=cfg.ai_timeout,
                   max_tokens=cfg.ai_max_tokens, reasoning=cfg.ai_reasoning),
            github, context_chars=cfg.ai_context_chars, rewrite_title=cfg.ai_rewrite_title)
    os.makedirs(cfg.store_path, exist_ok=True)
    adopt_legacy_token(cfg)
    return IssueBot(cfg, github, store, researcher)


def main() -> None:
    try:
        cfg = Config.from_env()
    except ConfigError as exc:
        print(f"Konfiguration unvollständig: {exc} (siehe .env.example)", file=sys.stderr)
        raise SystemExit(2)
    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    app = build(cfg)
    log.info("Ziel-Repos: %s", ", ".join(f"{k}={v}" for k, v in cfg.repos.items()))
    log.info("KI-Recherche: %s",
             f"{cfg.ai_model} @ {cfg.ai_base_url}" if app.researcher else "aus")
    try:
        app.bot.run()
    finally:
        app.store.close()


if __name__ == "__main__":
    main()
