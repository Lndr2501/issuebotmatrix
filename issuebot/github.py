"""Duenner GitHub-Client: nur Issues anlegen (REST, Token im Header)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

log = logging.getLogger("issuebot.github")

API = "https://api.github.com"


class GitHubError(Exception):
    """Fehler mit einer Meldung, die man so im Chat zeigen kann (ohne Token oder Rohdaten)."""


@dataclass
class CreatedIssue:
    number: int
    url: str
    repo: str
    title: str


class GitHub:
    def __init__(self, token: str, api: str = API, timeout: float = 20.0):
        self._token = token
        self._api = api.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "issuebotmatrix",
        }

    async def create_issue(self, repo: str, title: str, body: str,
                           labels: list[str]) -> CreatedIssue:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        url = f"{self._api}/repos/{repo}/issues"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as s:
                async with s.post(url, json=payload, headers=self._headers()) as r:
                    data = await r.json(content_type=None)
                    status = r.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("GitHub nicht erreichbar: %s", exc)
            raise GitHubError("GitHub ist gerade nicht erreichbar.") from exc
        except ValueError as exc:
            raise GitHubError("GitHub hat unlesbar geantwortet.") from exc

        if status == 201 and isinstance(data, dict) and data.get("number"):
            return CreatedIssue(number=int(data["number"]), url=str(data.get("html_url", "")),
                                repo=repo, title=str(data.get("title", title)))
        msg = data.get("message", "") if isinstance(data, dict) else ""
        log.warning("Issue anlegen in %s: HTTP %s %s", repo, status, msg)
        if status == 401:
            raise GitHubError("GitHub-Token ist ungültig oder abgelaufen.")
        if status in (403, 404):
            raise GitHubError(f"Kein Zugriff auf {repo} (Token braucht Issues: Lesen und Schreiben).")
        if status == 410:
            raise GitHubError(f"Issues sind in {repo} abgeschaltet.")
        if status == 422:
            raise GitHubError("GitHub hat das Issue abgelehnt (Titel/Labels prüfen).")
        raise GitHubError(f"GitHub-Fehler (HTTP {status}).")

    # ------------------------------------------------------------------ fuer die KI-Recherche
    async def _request(self, method: str, path: str, *, json_body: Optional[dict] = None,
                       raw: bool = False, timeout: Optional[float] = None):
        url = f"{self._api}{path}"
        tmo = aiohttp.ClientTimeout(total=timeout) if timeout else self._timeout
        try:
            async with aiohttp.ClientSession(timeout=tmo) as s:
                async with s.request(method, url, json=json_body, headers=self._headers()) as r:
                    data = await (r.read() if raw else r.json(content_type=None))
                    if r.status >= 300:
                        msg = data.get("message", "") if isinstance(data, dict) else ""
                        raise GitHubError(f"GitHub {method} {path}: HTTP {r.status} {msg}".strip())
                    return data
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise GitHubError(f"GitHub nicht erreichbar ({method} {path})") from exc

    async def head_sha(self, repo: str) -> str:
        """Commit-SHA des Standard-Branches."""
        info = await self._request("GET", f"/repos/{repo}")
        branch = info.get("default_branch") or "main"
        data = await self._request("GET", f"/repos/{repo}/commits/{branch}")
        return str(data["sha"])

    async def tarball(self, repo: str, sha: str) -> bytes:
        return await self._request("GET", f"/repos/{repo}/tarball/{sha}", raw=True, timeout=300)

    async def update_issue(self, repo: str, number: int, *, title: Optional[str] = None,
                           body: Optional[str] = None) -> None:
        payload = {k: v for k, v in (("title", title), ("body", body)) if v}
        if payload:
            await self._request("PATCH", f"/repos/{repo}/issues/{number}", json_body=payload)

    async def get_issue(self, repo: str, number: int) -> dict:
        return await self._request("GET", f"/repos/{repo}/issues/{number}")
