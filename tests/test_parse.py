from issuebot.parse import parse_command, split_issue, strip_reply_fallback

KEYS = ("diddy", "musik")


def test_command_names_and_help():
    assert parse_command("!issue Titel").kind == "issue"
    assert parse_command("!Bug Absturz").kind == "bug"
    assert parse_command("!idee Dark Mode").kind == "idea"
    assert parse_command("!issue").kind == "help"
    assert parse_command("!issue hilfe").kind == "help"
    assert parse_command("!issuebot").kind == "help"
    assert parse_command("!play song") is None          # Befehl eines anderen Bots
    assert parse_command("!issues") is None
    assert parse_command("issue ohne Präfix") is None
    assert parse_command("%issue x", "%").arg == "x"


def test_pipe_splits_title_and_body():
    d = split_issue("Login geht nicht | Nach dem Update kommt nur ein weißer Bildschirm.", KEYS)
    assert d.title == "Login geht nicht"
    assert d.body == "Nach dem Update kommt nur ein weißer Bildschirm."
    assert d.repo_key is None


def test_newline_splits_title_and_body():
    d = split_issue("Karte flackert\nWenn ich pausiere,\nflackert die Karte.", KEYS)
    assert d.title == "Karte flackert"
    assert d.body == "Wenn ich pausiere,\nflackert die Karte."


def test_quoted_title():
    d = split_issue('"Sound knackt im Call" passiert nur bei Video an', KEYS)
    assert d.title == "Sound knackt im Call"
    assert d.body == "passiert nur bei Video an"
    d = split_issue("„Deutsche Anführungszeichen“ gehen auch", KEYS)
    assert d.title == "Deutsche Anführungszeichen"


def test_short_text_is_all_title():
    d = split_issue("Emoji-Picker schließt sich sofort", KEYS)
    assert d.title == "Emoji-Picker schließt sich sofort" and d.body == ""


def test_long_text_first_sentence_is_title():
    text = ("Der Musikbot hängt nach Skip. Wenn die Warteschlange leer ist und man Skip drückt, "
            "bleibt die Karte auf Spielt stehen und nichts passiert mehr bis zum Neustart.")
    d = split_issue(text, KEYS)
    assert d.title == "Der Musikbot hängt nach Skip"
    assert d.body.startswith("Wenn die Warteschlange")


def test_long_text_without_sentence_keeps_everything_in_body():
    text = "wort " * 60
    d = split_issue(text, KEYS)
    assert len(d.title) <= 80 and d.title.endswith("…")
    assert d.body == text.strip()


def test_question_mark_stays_in_title():
    text = "Warum lädt der Raum so langsam? " + "x" * 100
    assert split_issue(text, KEYS).title == "Warum lädt der Raum so langsam?"


def test_repo_prefix():
    d = split_issue("musik: Skip tut nichts | Details", KEYS)
    assert d.repo_key == "musik" and d.title == "Skip tut nichts"
    d = split_issue("Fehler: Absturz beim Start", KEYS)       # kein bekannter Kurzname
    assert d.repo_key is None and d.title == "Fehler: Absturz beim Start"


def test_only_body_becomes_title():
    d = split_issue("| nur Beschreibung hier", KEYS)
    assert d.title == "nur Beschreibung hier"


def test_reply_fallback_is_removed():
    body = "> <@a:x> alte Nachricht\n> zweite Zeile\n\n!issue Titel | Text"
    assert strip_reply_fallback(body) == "!issue Titel | Text"
    assert parse_command(body).arg == "Titel | Text"
