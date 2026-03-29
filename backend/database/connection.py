import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from database.schema import SCHEMA_SQL

_db_path = os.environ.get("DATABASE_PATH", str(Path(__file__).resolve().parent.parent / "msft.db"))


def get_db_path() -> str:
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    return _db_path


def init_db() -> None:
    conn = sqlite3.connect(get_db_path())
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
