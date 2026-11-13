# IssueBotMatrix

Ein Matrix-Bot, der aus einer Chat-Nachricht ein **GitHub-Issue** macht. Passt zu
[Diddy](https://github.com/Lndr2501/diddy): Antworten kommen als Diddy-Karten, die Befehle
erscheinen beim Tippen als Vorschlag, und Diddy zeigt den Bot als Bot an. In Element & Co.
kommt normaler Text.

```
!issue Login geht nicht | Nach dem Update sehe ich nur einen weißen Bildschirm.
```

→ `✅ Issue #42 in Lndr2501/diddy angelegt: Login geht nicht` + Link

## Befehle

| Befehl | Wirkung |
|---|---|
| `!issue Titel \| Beschreibung` | Issue anlegen |
| `!issue Titel` ⇧↵ `Beschreibung` | Titel in Zeile 1, Beschreibung darunter (Shift+Enter) |
| `!issue "Titel" Beschreibung` | Titel in Anführungszeichen (auch „…“) |
| `!issue Kurzer Text` | bis 80 Zeichen: alles ist der Titel |
| `!issue Langer Text. Mehr …` | erster Satz = Titel, Rest = Beschreibung |
| `!bug …` · `!idee …` | wie `!issue`, zusätzlich Label `bug` bzw. `enhancement` |
| `!issue musik: Titel \| …` | anderes Repo per Kurzname (siehe `ISSUE_REPOS`) |
| `!issue` · `!issuebot` | Hilfe |

Aliase: `!ticket`, `!problem`, `!fehler`, `!feature`, `!wunsch`, `!idea`.
`!help` beantwortet der Bot absichtlich nicht (das macht schon der Musikbot).

## Schnellstart (Docker)

1. Matrix-Account für den Bot anlegen, z. B. `@issuebot:dein.server`.
2. GitHub: [Fine-grained Token](https://github.com/settings/personal-access-tokens/new) nur für die
   Ziel-Repos, Berechtigung **Issues: Read and write**.
3. Starten:
   ```bash
   cp .env.example .env      # Zugang, Token, ISSUE_REPOS eintragen
   docker compose up -d --build
   ```
4. Bot in den Raum einladen. Für die Befehlsvorschläge in Diddy braucht er **Moderator** (Stufe 50);
   ohne geht alles andere trotzdem.

## Sicherheit und Datenschutz

- Einladungen nimmt der Bot nur von Leuten auf **seinem eigenen Server** an (`INVITE_SERVERS`
  erweitert das, `ALLOWED_USERS` schränkt alles auf bestimmte Personen ein).
- Höchstens 5 Issues pro Person in 10 Minuten (`RATE_LIMIT`).
- Nachrichten von vor dem Start werden nie ausgeführt, jede Nachricht höchstens einmal
  (gemerkt in `/data`), auch nach Neustart.
- Im Issue steht unten „Gemeldet über Matrix von Name (`@id`)“. Bei öffentlichen Repos ist das
  öffentlich: `REPORTER_IN_ISSUE=id` oder `off`. Raumnamen landen nie im Issue.
- Anzeigenamen werden entschärft (keine Links/Bilder/@-Erwähnungen über den Namen).
- Verschlüsselte Räume gehen (E2EE über matrix-nio/vodozemac). Das Gerät des Bots liegt im
  Docker-Volume; `docker compose down -v` macht ihn zu einem neuen Gerät.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Aufbau: `parse.py` (Titel/Beschreibung trennen), `bot.py` (Logik), `github.py` (REST),
`cards.py` (Diddy-Karten, Protokoll: `docs/bot-cards.md` im Diddy-Repo), `matrix.py` (nio),
`store.py` (SQLite).
