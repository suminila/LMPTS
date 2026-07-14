"""
Learner ID generation utilities: auto-generates sequential L001, L002, etc. IDs.

Never reused, never a gap-fill, always the next sequential number.
"""

from typing import Optional
from data.database import DatabaseManager


def generate_next_learner_id(db: Optional[DatabaseManager] = None) -> str:
    """
    Generate the next learner ID in sequence (L001, L002, L003, ...).

    Queries the database for the highest numeric suffix and returns suffix+1.
    E.g., if L022 exists, returns L023.

    Args:
        db: DatabaseManager instance (uses default singleton if None)

    Returns:
        Next sequential learner ID in format L###
    """
    if db is None:
        db = DatabaseManager()

    cursor = db.connection.cursor()

    # Find all learner IDs that match the pattern L###
    cursor.execute("SELECT learner_id FROM learners")
    rows = cursor.fetchall()

    max_num = 0
    for row in rows:
        learner_id = row[0]
        # Extract numeric suffix from IDs like "L001", "L015", etc.
        if learner_id.startswith("L") and learner_id[1:].isdigit():
            num = int(learner_id[1:])
            max_num = max(max_num, num)

    # Next ID is max + 1, formatted as L###
    next_num = max_num + 1
    return f"L{next_num:03d}"


def extract_learner_id_number(learner_id: str) -> Optional[int]:
    """
    Extract numeric suffix from a learner ID string.

    E.g., "L001" -> 1, "L022" -> 22, "INVALID" -> None

    Args:
        learner_id: The learner ID string

    Returns:
        The numeric suffix, or None if not a valid learner ID
    """
    if not isinstance(learner_id, str):
        return None

    if learner_id.startswith("L") and len(learner_id) > 1:
        try:
            return int(learner_id[1:])
        except ValueError:
            pass

    return None


def is_valid_learner_id_format(learner_id: str) -> bool:
    """
    Check if a string is a valid learner ID format (L followed by digits).

    Args:
        learner_id: The ID string to validate

    Returns:
        True if valid format, False otherwise
    """
    if not isinstance(learner_id, str):
        return False

    if not learner_id.startswith("L") or len(learner_id) < 2:
        return False

    return learner_id[1:].isdigit()
