"""Konfiguration komplett ueber Umgebungsvariablen (siehe .env.example)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "ja")


def _list(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_KEY_RE = re.compile(r"^[a-z0-9_-]+$")


def parse_repos(value: str) -> dict[str, str]:
    """`diddy=Lndr2501/diddy,musik=owner/repo` -> {"diddy": "Lndr2501/diddy", ...}.

    Ohne `name=` wird der Repo-Name (Teil nach dem /) klein geschrieben als Kurzname genommen.
    Reihenfolge bleibt erhalten; der erste Eintrag ist das Standard-Repo.
    """
    repos: dict[str, str] = {}
    for item in _list(value):
        key, sep, repo = item.partition("=")
        if not sep:
            repo, key = item, item.split("/")[-1]
        key, repo = key.strip().lower(), repo.strip()
        if not _REPO_RE.match(repo):
            raise ConfigError(f"ISSUE_REPOS: '{repo}' ist kein owner/repo")
        if not _KEY_RE.match(key):
            raise ConfigError(f"ISSUE_REPOS: Kurzname '{key}' nur a-z, 0-9, _ und -")
        repos[key] = repo
    return repos


@dataclass
class Config:
    homeserver: str
    user: str
    password: str = ""
    token: str = ""
    device_id: str = "issuebot"
    rooms: list[str] = field(default_factory=list)
    encryption_enabled: bool = True
    prefix: str = "!"

    github_token: str = ""
    github_api: str = "https://api.github.com"
    repos: dict[str, str] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    reporter: str = "name"           # name | id | off: was im Issue ueber den Melder steht

    allowed_users: list[str] = field(default_factory=list)
    invite_servers: list[str] = field(default_factory=list)   # leer = nur eigener Server
    rate_count: int = 5
    rate_seconds: int = 600

    # KI-Recherche (leer = aus)
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""
    ai_timeout: int = 300
    ai_context_chars: int = 24_000
    ai_rewrite_title: bool = True

    data_dir: str = "/data"
    log_level: str = "INFO"

    matrix_user_id: str = ""  # nach dem Login gesetzt

    @property
    def store_path(self) -> str:
        return os.path.join(self.data_dir, "matrix-store")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "issuebot.sqlite3")

    @property
    def default_repo_key(self) -> str:
        return next(iter(self.repos))

    @property
    def server_name(self) -> str:
        return self.user.partition(":")[2]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = dict(os.environ if env is None else env)
        missing = [k for k in ("MATRIX_HOMESERVER", "MATRIX_USER", "GITHUB_TOKEN", "ISSUE_REPOS")
                   if not e.get(k, "").strip()]
        if missing:
            raise ConfigError("fehlt: " + ", ".join(missing))
        if not e.get("MATRIX_PASSWORD") and not e.get("MATRIX_TOKEN"):
            raise ConfigError("MATRIX_PASSWORD oder MATRIX_TOKEN setzen")

        reporter = e.get("REPORTER_IN_ISSUE", "name").strip().lower() or "name"
        if reporter not in ("name", "id", "off"):
            raise ConfigError("REPORTER_IN_ISSUE: name, id oder off")

        rate = e.get("RATE_LIMIT", "5/600").strip() or "5/600"
        m = re.match(r"^(\d+)\s*/\s*(\d+)$", rate)
        if not m:
            raise ConfigError("RATE_LIMIT: Format <Anzahl>/<Sekunden>, z. B. 5/600")

        prefix = e.get("BOT_PREFIX", "!").strip() or "!"
        if len(prefix) > 2 or prefix.isalnum():
            raise ConfigError("BOT_PREFIX: ein oder zwei Satzzeichen")

        cfg = cls(
            homeserver=e["MATRIX_HOMESERVER"].strip().rstrip("/"),
            user=e["MATRIX_USER"].strip(),
            password=e.get("MATRIX_PASSWORD", ""),
            token=e.get("MATRIX_TOKEN", "").strip(),
            device_id=e.get("MATRIX_DEVICE_ID", "issuebot").strip() or "issuebot",
            rooms=_list(e.get("MATRIX_ROOMS")),
            encryption_enabled=_bool(e.get("ENCRYPTION_ENABLED"), True),
            prefix=prefix,
            github_token=e["GITHUB_TOKEN"].strip(),
            github_api=e.get("GITHUB_API_URL", "").strip() or "https://api.github.com",
            repos=parse_repos(e["ISSUE_REPOS"]),
            labels=_list(e.get("ISSUE_LABELS", "matrix")),
            reporter=reporter,
            allowed_users=_list(e.get("ALLOWED_USERS")),
            invite_servers=_list(e.get("INVITE_SERVERS")),
            rate_count=int(m.group(1)),
            rate_seconds=int(m.group(2)),
            ai_base_url=e.get("AI_BASE_URL", "").strip().rstrip("/"),
            ai_model=e.get("AI_MODEL", "").strip(),
            ai_api_key=e.get("AI_API_KEY", "").strip(),
            ai_timeout=int(e.get("AI_TIMEOUT", "300") or 300),
            ai_context_chars=int(e.get("AI_CONTEXT_CHARS", "24000") or 24000),
            ai_rewrite_title=_bool(e.get("AI_REWRITE_TITLE"), True),
            data_dir=e.get("DATA_DIR", "/data").strip() or "/data",
            log_level=e.get("LOG_LEVEL", "INFO").strip() or "INFO",
        )
        if not cfg.repos:
            raise ConfigError("ISSUE_REPOS ist leer")
        if cfg.ai_base_url and not cfg.ai_model:
            raise ConfigError("AI_MODEL fehlt (AI_BASE_URL ist gesetzt)")
        return cfg
