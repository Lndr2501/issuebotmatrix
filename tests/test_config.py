import pytest

from issuebot.config import Config, ConfigError, parse_repos

BASE = {"MATRIX_HOMESERVER": "https://m.example/", "MATRIX_USER": "@issuebot:example.org",
        "MATRIX_PASSWORD": "pw", "GITHUB_TOKEN": "t", "ISSUE_REPOS": "diddy=Lndr/diddy,Lndr/MusikBot"}


def test_repos_order_and_default_keys():
    r = parse_repos("diddy=Lndr/diddy, Lndr/MusikBot")
    assert list(r) == ["diddy", "musikbot"] and r["musikbot"] == "Lndr/MusikBot"


def test_bad_repo():
    with pytest.raises(ConfigError):
        parse_repos("x=nur-ein-name")


def test_from_env_defaults():
    cfg = Config.from_env(BASE)
    assert cfg.homeserver == "https://m.example"
    assert cfg.default_repo_key == "diddy"
    assert cfg.labels == ["matrix"]
    assert (cfg.rate_count, cfg.rate_seconds) == (5, 600)
    assert cfg.server_name == "example.org"


def test_ai_settings_and_output_budget():
    cfg = Config.from_env({**BASE, "AI_BASE_URL": "https://proxy.example/v1/", "AI_MODEL": "model",
                           "AI_REASONING": "MEDIUM", "AI_MAX_TOKENS": "12000"})
    assert cfg.ai_base_url == "https://proxy.example/v1"
    assert cfg.ai_reasoning == "medium" and cfg.ai_max_tokens == 12000
    with pytest.raises(ConfigError, match="AI_MODEL"):
        Config.from_env({**BASE, "AI_BASE_URL": "https://proxy.example/v1"})


def test_missing_values():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "GITHUB_TOKEN": ""})
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "MATRIX_PASSWORD": ""})
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "RATE_LIMIT": "viele"})
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "BOT_PREFIX": "x"})
