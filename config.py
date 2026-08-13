import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "instance" / "database.db"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{DATABASE_PATH.as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
