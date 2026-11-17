<p align="center">
  <img src="branding/logo/issuebot-green-rounded.svg" width="128" alt="IssueBot-Logo">
</p>

<h1 align="center">IssueBotMatrix</h1>

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

## KI-Recherche (optional)

Mit `AI_BASE_URL` und `AI_MODEL` (jede OpenAI-kompatible API: Ollama, vLLM, LM Studio, OpenAI …)
bereitet der Bot jedes neue Issue im Hintergrund auf. Die Chat-Antwort kommt trotzdem sofort.

1. Die KI liest das Issue und nennt Suchbegriffe (Funktionsnamen, UI-Texte, Dateinamen).
2. Der Bot lädt den aktuellen Stand des Repos (Tarball, im Speicher, ~3 s für Diddy) und sucht.
3. Die KI bekommt die Fundstellen mit Zeilennummern und schreibt: präziser Titel, Zusammenfassung,
   Schritte/Erwartet/Tatsächlich, **relevante Codestellen**, Hinweise für die Umsetzung, offene Fragen.
4. Der Bot prüft jede Codestelle gegen den echten Code (erfundene fliegen raus) und schreibt alles
   ins Issue. Codestellen sind Permalinks auf den Commit, GitHub zeigt sie als Code-Ausschnitt.
   Die Originalmeldung bleibt aufklappbar darunter.

Kein Tool-Calling nötig: zwei Chat-Anfragen über **`/chat/completions` mit `stream: true`**.
Normale JSON-Antworten werden ebenfalls akzeptiert. Bei unbrauchbarem JSON gibt es genau einen
zweiten Versuch ohne JSON-Zwang; HTTP-/Verbindungsfehler werden nicht blind wiederholt.

- `AI_REASONING`: leer = kein `reasoning_effort` senden; sonst `none`, `low`, `medium`, `high`
  (weitere Stufen je nach Anbieter). Suchbegriffe nutzen `low`, die Aufbereitung die eingestellte
  Stufe. `none` lässt das Denken für beide Schritte ausgeschaltet.
- `AI_MAX_TOKENS=12000`: Ausgabe inklusive Denk-Tokens. `AI_CONTEXT_CHARS=24000` begrenzt den
  gesendeten Code, nicht das Kontextfenster des Modells.
- Die KI bekommt zusätzlich Projektbeschreibung und README-Anfang. Knappe Wünsche sollen nicht
  zu erfundenen Fehlern werden; bei unklarer Einordnung bleibt der Originaltitel erhalten.
- Code-Verweise werden auf tatsächlich gezeigte Zeilen geprüft. Wird das Issue während der
  Recherche bearbeitet, verwirft der Bot das Ergebnis statt die Bearbeitung zu überschreiben.

Es läuft immer nur eine Recherche gleichzeitig. Fehler landen nur im Log; das angelegte Issue
bleibt dann unverändert. Recherchen sind Hintergrundaufgaben im Speicher: nach einem Neustart
werden unterbrochene Aufgaben nicht automatisch nachgeholt.

Datenschutz: Issue-Text, Repository-Beschreibung, README-Auszug und Code-Ausschnitte gehen an den
konfigurierten KI-Anbieter. Die Matrix-Melderzeile wird vor dem Senden entfernt.

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

Aufbau: `parse.py` (Titel/Beschreibung trennen), `bot.py` (Befehle und Logik auf der Bot-Library
[diddybot](https://github.com/Lndr2501/diddy/tree/main/sdk/python): Matrix, E2EE, Einladungen, Diddy-Karten,
Befehlsvorschläge und Bot-Profil kommen von dort), `github.py` (REST), `research.py` + `codesearch.py`
(KI-Recherche), `store.py` (SQLite). Tests ohne Server: `diddybot.testing.TestClient`; Ende-zu-Ende gegen einen
Synapse: `DIDDY_TEST_HOMESERVER=http://127.0.0.1:8008 pytest tests/test_integration.py`.

Update vom Bot vor Version 0.2: Der alte Token (`/data/matrix-store/access_token`) wird beim ersten Start in die
`credentials.json` der Library übernommen. Das Gerät und die E2EE-Schlüssel bleiben gleich.

## Logo

Zeichen, Farbtöne und Bauanleitung stehen in [`branding/`](branding/README.md). Der Bot setzt sein Matrix-Profilbild beim Start selbst.
