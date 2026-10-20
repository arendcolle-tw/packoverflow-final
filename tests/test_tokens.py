import sys

from knowly import tokens as tokens_mod
from knowly.tokens import Tokens


def test_member_tokens(tmp_path):
    tokens = Tokens(tmp_path / "tokens.db")
    token = tokens.add("tristan")
    assert token.startswith("wk_") and tokens.person_for(token) == "tristan"
    assert tokens.person_for("nope") is None
    other = tokens.add("alberic")
    assert tokens.revoke("tristan") == 1 and tokens.person_for(token) is None and tokens.person_for(other) == "alberic"


def test_cli_writes_to_the_data_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KNOWLY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["knowly-token", "  Alberic  "])
    tokens_mod.main()
    token = capsys.readouterr().out.strip()
    assert Tokens(tmp_path / "tokens.db").person_for(token) == "alberic"

    monkeypatch.setattr(sys, "argv", ["knowly-token", "alberic", "--revoke"])
    tokens_mod.main()
    assert capsys.readouterr().out.strip() == "revoked 1 tokens of alberic"
