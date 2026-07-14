"""
Singleton SQLite connection manager.

Keeping schema/connection logic here (and nowhere else) is what lets us
swap SQLite for PostgreSQL later without touching the service layer -
only this file and repository.py's SQL dialect would need to change.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional


class DatabaseManager:
    _instance: Optional["DatabaseManager"] = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = "lmpts.db"):
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init(db_path)
                cls._instance = instance
            return cls._instance

    def _init(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    @classmethod
    def reset_instance(cls):
        """Used by tests to force a fresh singleton against a new db path."""
        if cls._instance is not None:
            cls._instance._conn.close()
        cls._instance = None

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def _create_schema(self):
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS courses (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                difficulty TEXT NOT NULL,
                duration_hours REAL NOT NULL,
                instructor TEXT,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prerequisites (
                prereq_code TEXT NOT NULL,
                dependent_code TEXT NOT NULL,
                PRIMARY KEY (prereq_code, dependent_code),
                FOREIGN KEY (prereq_code) REFERENCES courses(code) ON DELETE CASCADE,
                FOREIGN KEY (dependent_code) REFERENCES courses(code) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS learners (
                learner_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                date_registered TEXT
            );

            CREATE TABLE IF NOT EXISTS enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learner_id TEXT NOT NULL,
                course_code TEXT NOT NULL,
                status TEXT NOT NULL,
                score REAL,
                enrolled_date TEXT,
                completed_date TEXT,
                current_level INTEGER NOT NULL DEFAULT 1,
                latest_score_percent REAL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(learner_id, course_code),
                FOREIGN KEY (learner_id) REFERENCES learners(learner_id) ON DELETE CASCADE,
                FOREIGN KEY (course_code) REFERENCES courses(code) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assignments (
                assignment_id TEXT PRIMARY KEY,
                course_code TEXT NOT NULL,
                level_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT,
                FOREIGN KEY (course_code) REFERENCES courses(code) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assignment_grades (
                assignment_id TEXT NOT NULL,
                learner_id TEXT NOT NULL,
                score_percent REAL NOT NULL,
                graded_at TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id) ON DELETE CASCADE,
                FOREIGN KEY (learner_id) REFERENCES learners(learner_id) ON DELETE CASCADE,
                PRIMARY KEY (assignment_id, learner_id, attempt_number)
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)
        self._conn.commit()

        def _has_column(table_name: str, column_name: str) -> bool:
            cols = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            return any(col[1] == column_name for col in cols)

        if not _has_column("courses", "total_levels"):
            self._conn.execute(
                "ALTER TABLE courses ADD COLUMN total_levels INTEGER NOT NULL DEFAULT 1"
            )
        if not _has_column("enrollments", "current_level"):
            self._conn.execute(
                "ALTER TABLE enrollments ADD COLUMN current_level INTEGER NOT NULL DEFAULT 1"
            )
        if not _has_column("enrollments", "latest_score_percent"):
            self._conn.execute(
                "ALTER TABLE enrollments ADD COLUMN latest_score_percent REAL"
            )
        if not _has_column("enrollments", "attempt_count"):
            self._conn.execute(
                "ALTER TABLE enrollments ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()
