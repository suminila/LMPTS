"""
Settings module: persist and retrieve application settings from the database.

Settings are stored in the `settings` table with a simple key-value structure.
This module provides a dictionary-like interface for getting and setting values.
"""

from data.database import DatabaseManager
from typing import Optional

# Setting keys (constants for type safety and easy refactoring)
KEY_ENROLLMENT_SORT = "enrollment_sort"
KEY_REMEMBERED_EMAIL = "remembered_email"


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a setting value from the database.

    Args:
        key: The setting key to look up
        default: Value to return if key doesn't exist (default: None)

    Returns:
        The setting value, or the default if not found
    """
    db = DatabaseManager()
    cursor = db.connection.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()

    if row:
        return row[0]
    return default


def set_setting(key: str, value: str) -> None:
    """
    Store or update a setting value in the database.

    Args:
        key: The setting key
        value: The value to store
    """
    db = DatabaseManager()
    cursor = db.connection.cursor()

    # Use INSERT OR REPLACE to handle both insert and update
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    db.connection.commit()


def delete_setting(key: str) -> None:
    """
    Delete a setting from the database.

    Args:
        key: The setting key to delete
    """
    db = DatabaseManager()
    cursor = db.connection.cursor()
    cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
    db.connection.commit()


def get_all_settings() -> dict:
    """
    Retrieve all settings from the database.

    Returns:
        Dictionary of all key-value settings
    """
    db = DatabaseManager()
    cursor = db.connection.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()

    return {row[0]: row[1] for row in rows}


def clear_all_settings() -> None:
    """Delete all settings from the database. Use with caution."""
    db = DatabaseManager()
    cursor = db.connection.cursor()
    cursor.execute("DELETE FROM settings")
    db.connection.commit()
