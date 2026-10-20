import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


def person_key(name: str) -> str:
    """The person a name stands for: its first word, lowercase, accents stripped, so "Albéric X" and "alberic.loos" are "alberic"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    # Slack usernames like "alberic.loos" count too, so split on anything that is not a letter or digit.
    return next((word for word in re.split(r"[^a-z0-9]+", plain.lower()) if word), "")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    url: str = "http://127.0.0.1:8091"
    admin_token: str = ""
    bucket: str | None = None
    channel: str = "ask-knowly"
    allow_self: bool = False
    people: dict[str, str] = field(default_factory=dict)
    default_expert: str = ""
    port: int = 8091
    host: str = "127.0.0.1"
    slack_bot_token: str = ""
    slack_app_token: str = ""


def load() -> Settings:
    env = os.environ
    port = int(env.get("PORT") or Settings.port)
    pairs = (pair.split(":", 1) for pair in env.get("SLACK_PEOPLE", "").split(",") if ":" in pair)
    return Settings(
        data_dir=Path(env.get("KNOWLY_DATA_DIR") or Settings.data_dir),
        url=(env.get("KNOWLY_URL") or f"http://127.0.0.1:{port}").rstrip("/"),
        admin_token=env.get("KNOWLY_ADMIN_TOKEN", "").strip(),
        bucket=env.get("KNOWLY_BUCKET") or None,
        channel=(env.get("KNOWLY_CHANNEL") or Settings.channel).lstrip("#"),
        allow_self=env.get("KNOWLY_ALLOW_SELF") == "1",
        people={person_key(name): user_id.strip() for name, user_id in pairs if person_key(name) and user_id.strip()},
        default_expert=env.get("DEFAULT_EXPERT", "").strip(),
        port=port,
        host=env.get("HOST") or Settings.host,
        slack_bot_token=env.get("SLACK_BOT_TOKEN", ""),
        slack_app_token=env.get("SLACK_APP_TOKEN", ""),
    )
