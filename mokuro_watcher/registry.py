import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SEEN = "seen"
IGNORED = "ignored"
PENDING = "pending"
DONE = "done"
FAILED = "failed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
    path TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS series (
    name TEXT PRIMARY KEY,
    baseline_until REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Chapter:
    path: str
    mtime_ns: int
    size: int
    status: str
    attempts: int
    last_error: str | None


class Registry:
    def __init__(self, db_path: Path | str):
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @property
    def baseline_done(self) -> bool:
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'baseline_done'").fetchone()
        return row is not None

    def mark_baseline_done(self) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('baseline_done', ?)",
                (str(time.time()),),
            )

    def series_baselines(self) -> dict[str, float]:
        """Series name -> time until which new chapters of it are still the initial download."""
        return dict(self.conn.execute("SELECT name, baseline_until FROM series").fetchall())

    def set_series_baseline(self, name: str, until: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO series (name, baseline_until) VALUES (?, ?)",
                (name, until),
            )

    def delete_series(self, name: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM series WHERE name = ?", (name,))

    def get(self, path: str) -> Chapter | None:
        row = self.conn.execute("SELECT * FROM chapters WHERE path = ?", (path,)).fetchone()
        return _to_chapter(row) if row else None

    def all(self) -> list[Chapter]:
        return [_to_chapter(r) for r in self.conn.execute("SELECT * FROM chapters")]

    def upsert(self, path: str, mtime_ns: int, size: int, status: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO chapters (path, mtime_ns, size, status, attempts, last_error, updated_at)
                VALUES (?, ?, ?, ?, 0, NULL, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime_ns = excluded.mtime_ns,
                    size = excluded.size,
                    status = excluded.status,
                    attempts = 0,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (path, mtime_ns, size, status, time.time()),
            )

    def set_status(self, path: str, status: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET status = ?, updated_at = ? WHERE path = ?",
                (status, time.time(), path),
            )

    def record_failure(self, path: str, error: str, max_attempts: int) -> Chapter:
        with self.conn:
            self.conn.execute(
                """
                UPDATE chapters
                SET attempts = attempts + 1,
                    last_error = ?,
                    status = CASE WHEN attempts + 1 >= ? THEN ? ELSE status END,
                    updated_at = ?
                WHERE path = ?
                """,
                (error[-2000:], max_attempts, FAILED, time.time(), path),
            )
        chapter = self.get(path)
        assert chapter is not None
        return chapter

    def pending(self) -> list[Chapter]:
        rows = self.conn.execute(
            "SELECT * FROM chapters WHERE status = ? ORDER BY mtime_ns", (PENDING,)
        )
        return [_to_chapter(r) for r in rows]

    def delete(self, path: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chapters WHERE path = ?", (path,))


def _to_chapter(row: sqlite3.Row) -> Chapter:
    return Chapter(
        path=row["path"],
        mtime_ns=row["mtime_ns"],
        size=row["size"],
        status=row["status"],
        attempts=row["attempts"],
        last_error=row["last_error"],
    )
