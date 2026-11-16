import json
import os

from issuebot.__main__ import adopt_legacy_token
from issuebot.config import Config

CFG = dict(homeserver="https://m", user="@issuebot:example.org", password="pw", github_token="t",
           repos={"diddy": "Lndr/diddy"})


def test_old_token_becomes_library_credentials(tmp_path):
    cfg = Config(**CFG, data_dir=str(tmp_path))
    os.makedirs(cfg.store_path)
    with open(os.path.join(cfg.store_path, "access_token"), "w") as fh:
        fh.write("syt_old\n")
    assert adopt_legacy_token(cfg)
    path = os.path.join(cfg.store_path, "credentials.json")
    assert json.load(open(path)) == {"homeserver": "https://m", "user_id": "@issuebot:example.org",
                                     "device_id": "issuebot", "access_token": "syt_old"}
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert not adopt_legacy_token(cfg)             # second start: the library's file wins


def test_nothing_to_adopt(tmp_path):
    cfg = Config(**CFG, data_dir=str(tmp_path))
    os.makedirs(cfg.store_path)
    assert not adopt_legacy_token(cfg)
