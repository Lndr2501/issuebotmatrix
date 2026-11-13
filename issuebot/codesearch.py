"""Code eines Repos durchsuchen, damit die KI echte Zeilen zitieren kann. Rein (kein Netz):
Eingang ist das Tar-Archiv eines Commits (GitHub-Tarball), alles bleibt im Speicher."""
from __future__ import annotations

import io
import math
import re
import tarfile
from collections import Counter
from dataclasses import dataclass

MAX_FILE_BYTES = 400_000
SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "out", "target", "vendor", "Pods", "DerivedData",
    "test-results", "coverage", "__pycache__", ".venv", "venv", ".next", ".cache", "public",
}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "flake.lock",
              "poetry.lock", "uv.lock"}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".svg", ".lock", ".snap", ".pbxproj")
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".cjs", ".mjs", ".rs", ".swift", ".kt", ".java", ".go",
    ".c", ".h", ".cpp", ".hpp", ".m", ".mm", ".cs", ".rb", ".php", ".sh", ".css", ".scss", ".html",
    ".vue", ".svelte", ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".sql", ".nix", ".ini",
    ".cfg", ".conf", ".xml", ".plist", ".gradle", ".proto", ".graphql", ".env.example",
}


@dataclass
class Hit:
    path: str
    score: float
    lines: list[int]          # 1-basierte Treffer-Zeilen
    terms: list[str]


class CodeIndex:
    def __init__(self, files: dict[str, list[str]]):
        self.files = files

    # ------------------------------------------------------------------ Aufbau
    @classmethod
    def from_tarball(cls, data: bytes) -> "CodeIndex":
        files: dict[str, list[str]] = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            for m in tar:
                if not m.isfile() or m.size > MAX_FILE_BYTES:
                    continue
                # GitHub packt alles in "<owner>-<repo>-<sha>/..."
                parts = m.name.split("/")[1:]
                if not parts or not _wanted(parts):
                    continue
                fh = tar.extractfile(m)
                if fh is None:
                    continue
                raw = fh.read()
                if b"\x00" in raw[:8000]:
                    continue
                text = raw.decode("utf-8", errors="replace")
                files["/".join(parts)] = text.splitlines()
        return cls(files)

    def overview(self, max_lines: int = 60) -> str:
        """Ordner mit Dateizahl, damit die KI weiss, wie das Repo aufgebaut ist."""
        dirs: Counter[str] = Counter()
        for p in self.files:
            parts = p.split("/")
            dirs["/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")] += 1
        rows = [f"{d}/ ({n} Dateien)" if d != "." else f"(Wurzel) ({n} Dateien)"
                for d, n in sorted(dirs.items(), key=lambda x: (-x[1], x[0]))[:max_lines]]
        return "\n".join(rows)

    # ------------------------------------------------------------------ Suche
    def search(self, terms: list[str], path_hints: list[str] = (), limit: int = 8) -> list[Hit]:
        terms = _clean_terms(terms)
        if not terms:
            return []
        pats = {t: re.compile(re.escape(t), re.IGNORECASE) for t in terms}
        df: Counter[str] = Counter()
        per_file: dict[str, dict[str, list[int]]] = {}
        for path, lines in self.files.items():
            found: dict[str, list[int]] = {}
            for t, pat in pats.items():
                hit_lines = [i + 1 for i, line in enumerate(lines) if pat.search(line)]
                if hit_lines:
                    found[t] = hit_lines
            # Treffer im Dateipfad zaehlen auch
            for t in terms:
                if t.lower() in path.lower() and t not in found:
                    found[t] = [1]
            if found:
                per_file[path] = found
                df.update(found.keys())
        n = max(1, len(self.files))
        hints = [h.lower().strip("/") for h in path_hints if h and len(h) >= 3]
        hits = []
        for path, found in per_file.items():
            score = sum(math.log(1 + n / df[t]) * (1 + math.log(len(ls))) for t, ls in found.items())
            score *= 1 + 0.5 * (len(found) - 1)              # mehrere Begriffe in einer Datei
            if any(h in path.lower() for h in hints):
                score *= 2
            lower = path.lower()
            if (lower.endswith((".md", ".txt")) or "/test" in lower or lower.startswith("test")
                    or "/tools/" in lower or ".test." in lower or ".spec." in lower):
                score *= 0.6                                  # Doku/Tests/Hilfsprogramme nach hinten
            lines = sorted({ln for ls in found.values() for ln in ls})
            hits.append(Hit(path, score, lines, sorted(found)))
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    def snippets(self, hits: list[Hit], budget_chars: int, context: int = 12) -> str:
        """Ausschnitte mit Zeilennummern um die Treffer, bis das Zeichenbudget voll ist."""
        out: list[str] = []
        used = 0
        windows = {h.path: _windows(h.lines, context, len(self.files[h.path]))[:3] for h in hits}
        # Erst jede Datei zeigen, dann weitere Fenster. Sonst verdraengt die erste grosse
        # Datei andere Plattformen vollstaendig aus dem Kontext.
        for round_no in range(3):
            for h in hits:
                if round_no >= len(windows[h.path]):
                    continue
                a, b = windows[h.path][round_no]
                remaining = budget_chars - used - (1 if out else 0)
                quota = min(remaining, budget_chars // max(1, len(hits))) if round_no == 0 else remaining
                lines = self.files[h.path]
                while b >= a:
                    body = "\n".join(f"{i:>5}| {lines[i - 1][:240]}" for i in range(a, b + 1))
                    block = f"### {h.path} (Zeilen {a}-{b})\n{body}\n"
                    if len(block) <= quota:
                        used += len(block) + (1 if out else 0)
                        out.append(block)
                        break
                    b -= 1
        return "\n".join(out)

    def valid_range(self, path: str, start: int, end: int, max_span: int = 80):
        """Pruefen und begrenzen, was die KI als Codestelle nennt. None, wenn es die Datei nicht gibt."""
        lines = self.files.get(path)
        if not lines or not isinstance(start, int) or not isinstance(end, int):
            return None
        n = len(lines)
        if not 1 <= start <= n or end < start:
            return None
        end = max(start, min(end, n, start + max_span))
        return start, end


def _wanted(parts: list[str]) -> bool:
    if any(p in SKIP_DIRS or p.startswith(".") and p not in (".github",) for p in parts[:-1]):
        return False
    name = parts[-1]
    if name in SKIP_FILES or name.endswith(SKIP_SUFFIXES):
        return False
    dot = name.rfind(".")
    suffix = name[dot:].lower() if dot > 0 else ""
    return suffix in TEXT_SUFFIXES or name in ("Dockerfile", "Makefile", "README", "LICENSE")


def _clean_terms(terms) -> list[str]:
    out = []
    for t in terms or []:
        if not isinstance(t, str):
            continue
        t = t.strip().strip("`'\"")
        if 3 <= len(t) <= 60 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:15]


def _windows(lines: list[int], context: int, n: int) -> list[tuple[int, int]]:
    wins: list[list[int]] = []
    for ln in lines:
        a, b = max(1, ln - context), min(n, ln + context)
        if wins and a <= wins[-1][1] + 2:
            wins[-1][1] = max(wins[-1][1], b)
        else:
            wins.append([a, b])
    # die Fenster mit den meisten Treffern zuerst
    wins.sort(key=lambda w: -sum(1 for ln in lines if w[0] <= ln <= w[1]))
    return [(a, min(b, a + 39)) for a, b in wins]
