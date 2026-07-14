#!/usr/bin/env python3
"""
One-time migration: Renumber all learner IDs to sequential format L001, L002, L003, ...

This script:
1. Backs up the database before any modifications
2. Detects if the table is already in clean sequential order (idempotency check)
3. Discovers all tables with learner_id foreign keys
4. Orders learners by registration date (date_registered column)
5. Builds an old -> new ID mapping (e.g., L015 -> L001, L013 -> L002, etc.)
6. Updates learners table and all referencing tables in a safe multi-phase transaction
7. Handles foreign key constraints with deferred mode and pragma settings
8. Logs the full mapping for audit/reversal purposes
9. Provides rollback on any failure

Usage:
    python migrations/renumber_learner_ids.py /path/to/lmpts.db

Optional:
    python migrations/renumber_learner_ids.py /path/to/lmpts.db --dry-run
    python migrations/renumber_learner_ids.py /path/to/lmpts.db --backup-only
"""

import sqlite3
import sys
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import argparse
import re

# ============================================================================
# Logging Configuration
# ============================================================================


def setup_logging(db_path: str) -> logging.Logger:
    """Set up logging to file and console."""
    log_dir = Path(db_path).parent / "migrations_logs"
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"renumber_learner_ids_{timestamp}.log"

    logger = logging.getLogger("learner_id_migration")
    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Migration log: {log_file}")
    return logger


# ============================================================================
# Database Inspection & Discovery
# ============================================================================


def find_learner_id_columns(conn: sqlite3.Connection) -> Dict[str, str]:
    """
    Discover all columns named 'learner_id' or similar across all tables.

    Returns: {table_name: column_name, ...}
    """
    cursor = conn.cursor()
    learner_id_cols = {}

    # List of possible column name patterns for learner references
    patterns = ["learner_id", "learnerID", "learner"]

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = [row[0] for row in cursor.fetchall()]

    for table_name in tables:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]

        for pattern in patterns:
            for col in columns:
                if col.lower() == pattern.lower():
                    learner_id_cols[table_name] = col
                    break

    return learner_id_cols


def get_learner_id_column_name(conn: sqlite3.Connection) -> str:
    """Get the exact column name for learner_id in the learners table."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(learners)")
    for row in cursor.fetchall():
        if row[1].lower() == "learner_id":
            return row[1]
    raise ValueError("No learner_id column found in learners table")


def get_registration_order_column(conn: sqlite3.Connection) -> str:
    """
    Detect the column used to order learners by registration time.
    Priority: date_registered, created_at, registration_date, date_created, rowid
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(learners)")
    columns = [row[1] for row in cursor.fetchall()]

    for col_name in [
        "date_registered",
        "created_at",
        "registration_date",
        "date_created",
    ]:
        if col_name in columns:
            return col_name

    return "rowid"


def get_learners_in_registration_order(
    conn: sqlite3.Connection, learner_id_col: str, order_col: str
) -> List[Tuple[str, any]]:
    """Fetch all learners ordered by registration time."""
    cursor = conn.cursor()

    if order_col == "rowid":
        query = f"SELECT {learner_id_col}, rowid FROM learners ORDER BY rowid ASC"
    else:
        query = f"""
            SELECT {learner_id_col}, {order_col}
            FROM learners
            ORDER BY COALESCE({order_col}, ''), rowid ASC
        """

    cursor.execute(query)
    return cursor.fetchall()


# ============================================================================
# Idempotency Check
# ============================================================================


def is_already_migrated(conn: sqlite3.Connection, learner_id_col: str) -> bool:
    """
    Check if all learner IDs are already in clean sequential format (L001, L002, ...).
    """
    cursor = conn.cursor()
    cursor.execute(f"SELECT {learner_id_col} FROM learners ORDER BY rowid")
    learner_ids = [row[0] for row in cursor.fetchall()]

    if not learner_ids:
        return True

    pattern = re.compile(r"^L(\d+)$")
    extracted_numbers = []

    for lid in learner_ids:
        match = pattern.match(lid)
        if not match:
            return False
        num = int(match.group(1))
        extracted_numbers.append(num)

    expected = list(range(1, len(extracted_numbers) + 1))
    return extracted_numbers == expected


# ============================================================================
# Backup & Logging
# ============================================================================


def backup_database(db_path: str, logger: logging.Logger) -> str:
    """Create a timestamped backup of the database file."""
    db_path_obj = Path(db_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = (
        db_path_obj.parent
        / f"{db_path_obj.stem}_backup_{timestamp}{db_path_obj.suffix}"
    )

    shutil.copy2(db_path, backup_path)
    logger.info(f"Database backed up to: {backup_path}")
    return str(backup_path)


def log_id_mapping(
    mapping: Dict[str, str], db_path: str, logger: logging.Logger
) -> str:
    """Save the old -> new ID mapping to a log file for audit and reversal."""
    log_dir = Path(db_path).parent / "migrations_logs"
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mapping_file = log_dir / f"learner_id_mapping_{timestamp}.txt"

    with open(mapping_file, "w") as f:
        f.write(f"Learner ID Renumbering Mapping\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Database: {db_path}\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"{'OLD ID':<15} -> {'NEW ID':<15}\n")
        f.write(f"{'-'*60}\n")

        sorted_mapping = sorted(mapping.items(), key=lambda x: x[1])
        for old_id, new_id in sorted_mapping:
            f.write(f"{old_id:<15} -> {new_id:<15}\n")

    logger.info(f"ID mapping log: {mapping_file}")
    return str(mapping_file)


# ============================================================================
# Migration Logic
# ============================================================================


def build_id_mapping(
    conn: sqlite3.Connection,
    learner_id_col: str,
    order_col: str,
    logger: logging.Logger,
) -> Dict[str, str]:
    """Build a mapping from old learner IDs to new sequential IDs."""
    learners = get_learners_in_registration_order(conn, learner_id_col, order_col)

    mapping = {}
    for index, (old_id, order_value) in enumerate(learners, start=1):
        new_id = f"L{index:03d}"
        mapping[old_id] = new_id
        logger.debug(f"  {old_id} (registered: {order_value}) -> {new_id}")

    logger.info(f"Built mapping for {len(mapping)} learners")
    return mapping


def execute_migration(
    conn: sqlite3.Connection,
    mapping: Dict[str, str],
    learner_id_tables: Dict[str, str],
    learner_id_col: str,
    logger: logging.Logger,
    dry_run: bool = False,
) -> None:
    """
    Execute the renumbering migration in a three-phase transaction.

    To avoid UNIQUE constraint violations:
    Phase 1: Update child tables (old_id -> temp_id using _TEMP_#### prefix)
    Phase 2: Update parent table (learners) (old_id -> new_id)
    Phase 3: Update child tables (temp_id -> new_id)
    """
    cursor = conn.cursor()

    try:
        logger.info("Starting migration transaction...")

        # Begin explicit transaction
        cursor.execute("BEGIN TRANSACTION")

        # Defer foreign key constraint checks
        cursor.execute("PRAGMA defer_foreign_keys = ON")
        logger.debug("Foreign key constraints deferred until transaction end")

        # Create temp ID mapping (old_id -> _TEMP_0001, etc.)
        temp_mapping = {}
        for idx, old_id in enumerate(sorted(mapping.keys()), start=1):
            temp_mapping[old_id] = f"_TEMP_{idx:04d}"

        # ===== PHASE 1: Update child tables to temp IDs =====
        logger.info("PHASE 1: Updating child tables to temporary IDs...")
        for table_name, column_name in sorted(learner_id_tables.items()):
            if table_name == "learners":
                continue

            logger.info(f"  {table_name}: old_id -> temp_id")
            for old_id, temp_id in temp_mapping.items():
                if dry_run:
                    logger.info(f"    [DRY-RUN] {old_id} -> {temp_id}")
                else:
                    cursor.execute(
                        f"UPDATE {table_name} SET {column_name} = ? WHERE {column_name} = ?",
                        (temp_id, old_id),
                    )
                    rows = cursor.rowcount
                    if rows > 0:
                        logger.debug(f"    {old_id} -> {temp_id}: {rows} row(s)")

        # ===== PHASE 2: Update parent (learners) table =====
        # Also use temp IDs as intermediate to avoid PK constraint violations
        logger.info("PHASE 2a: Updating learners table to temporary IDs...")
        for old_id, temp_id in temp_mapping.items():
            if dry_run:
                logger.info(f"  [DRY-RUN] {old_id} -> {temp_id}")
            else:
                cursor.execute(
                    f"UPDATE learners SET {learner_id_col} = ? WHERE {learner_id_col} = ?",
                    (temp_id, old_id),
                )
                rows = cursor.rowcount
                if rows > 0:
                    logger.debug(f"  {old_id} -> {temp_id}: {rows} learner(s)")

        logger.info("PHASE 2b: Updating learners table from temporary to final IDs...")
        for old_id, temp_id in temp_mapping.items():
            new_id = mapping[old_id]
            if dry_run:
                logger.info(f"  [DRY-RUN] {temp_id} -> {new_id}")
            else:
                cursor.execute(
                    f"UPDATE learners SET {learner_id_col} = ? WHERE {learner_id_col} = ?",
                    (new_id, temp_id),
                )
                rows = cursor.rowcount
                if rows > 0:
                    logger.debug(f"  {temp_id} -> {new_id}: {rows} learner(s)")

        # ===== PHASE 3: Update child tables from temp to new IDs =====
        logger.info("PHASE 3: Updating child tables from temp to final IDs...")
        for table_name, column_name in sorted(learner_id_tables.items()):
            if table_name == "learners":
                continue

            logger.info(f"  {table_name}: temp_id -> new_id")
            for old_id, temp_id in temp_mapping.items():
                new_id = mapping[old_id]
                if dry_run:
                    logger.info(f"    [DRY-RUN] {temp_id} -> {new_id}")
                else:
                    cursor.execute(
                        f"UPDATE {table_name} SET {column_name} = ? WHERE {column_name} = ?",
                        (new_id, temp_id),
                    )
                    rows = cursor.rowcount
                    if rows > 0:
                        logger.debug(f"    {temp_id} -> {new_id}: {rows} row(s)")

        if dry_run:
            logger.info("[DRY-RUN] Rolling back transaction without applying changes")
            cursor.execute("ROLLBACK")
        else:
            # Commit the transaction
            cursor.execute("END TRANSACTION")
            logger.info("Migration transaction committed successfully")

            # Re-enable normal foreign key checking
            cursor.execute("PRAGMA defer_foreign_keys = OFF")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        try:
            cursor.execute("ROLLBACK")
            logger.info("Transaction rolled back; database unchanged")
        except Exception as rollback_error:
            logger.error(f"Rollback failed: {rollback_error}", exc_info=True)
        raise


# ============================================================================
# Verification & Post-Migration
# ============================================================================


def verify_migration(
    conn: sqlite3.Connection,
    mapping: Dict[str, str],
    learner_id_tables: Dict[str, str],
    learner_id_col: str,
    logger: logging.Logger,
) -> bool:
    """Verify that all learner IDs were updated correctly and consistently."""
    cursor = conn.cursor()
    all_passed = True

    # Check 1: Verify learners table has sequential IDs
    logger.info("Verifying learners table...")
    cursor.execute(f"SELECT {learner_id_col} FROM learners ORDER BY rowid")
    learner_ids = [row[0] for row in cursor.fetchall()]

    for i, lid in enumerate(learner_ids, start=1):
        expected = f"L{i:03d}"
        if lid != expected:
            logger.error(
                f"  Learner ID mismatch at position {i}: found '{lid}', expected '{expected}'"
            )
            all_passed = False

    if all_passed:
        logger.info(
            f"  OK: All {len(learner_ids)} learner IDs are sequential and correct"
        )

    # Check 2: Verify all referencing tables have valid foreign key references
    logger.info("Verifying foreign key references...")
    for table_name, column_name in learner_id_tables.items():
        if table_name == "learners":
            continue

        cursor.execute(
            f"SELECT DISTINCT {column_name} FROM {table_name} WHERE {column_name} IS NOT NULL"
        )
        referenced_ids = [row[0] for row in cursor.fetchall()]

        cursor.execute(f"SELECT {learner_id_col} FROM learners")
        valid_ids = set(row[0] for row in cursor.fetchall())

        invalid_refs = [rid for rid in referenced_ids if rid not in valid_ids]
        if invalid_refs:
            logger.error(
                f"  Invalid learner_id references in {table_name}: {invalid_refs}"
            )
            all_passed = False
        else:
            logger.info(
                f"  OK: {table_name}: all {len(referenced_ids)} unique references are valid"
            )

    return all_passed


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Renumber learner IDs to sequential format (L001, L002, ...)"
    )
    parser.add_argument("db_path", help="Path to the SQLite database file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying the database",
    )
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="Create a backup and exit without migrating",
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip post-migration verification (not recommended)",
    )

    args = parser.parse_args()

    db_path = args.db_path

    # Validate database file exists
    if not Path(db_path).exists():
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)

    # Set up logging
    logger = setup_logging(db_path)
    logger.info("=" * 70)
    logger.info("Learner ID Renumbering Migration")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")
    logger.info(f"Dry-run: {args.dry_run}")

    try:
        # Open database connection
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row

        # Step 1: Backup database
        backup_path = backup_database(db_path, logger)
        if args.backup_only:
            logger.info("Backup complete. Exiting (--backup-only flag set).")
            conn.close()
            return 0

        # Step 2: Discover schema
        logger.info("Discovering schema...")
        learner_id_col = get_learner_id_column_name(conn)
        order_col = get_registration_order_column(conn)
        learner_id_tables = find_learner_id_columns(conn)

        logger.info(f"  Learner ID column: {learner_id_col}")
        logger.info(f"  Registration order column: {order_col}")
        logger.info(f"  Tables with learner_id: {list(learner_id_tables.keys())}")

        # Step 3: Idempotency check
        logger.info("Checking if migration is needed...")
        if is_already_migrated(conn, learner_id_col):
            logger.info(
                "OK: Database is already in clean sequential order. No changes needed."
            )
            logger.info("(Idempotency check passed; this script is a no-op)")
            conn.close()
            return 0

        logger.info("  Migration needed: IDs are not in clean sequential order")

        # Step 4: Build mapping
        logger.info("Building learner ID mapping...")
        mapping = build_id_mapping(conn, learner_id_col, order_col, logger)

        # Step 5: Execute migration
        if args.dry_run:
            logger.info("=" * 70)
            logger.info("DRY-RUN MODE: The following changes would be applied:")
            logger.info("=" * 70)

        execute_migration(
            conn, mapping, learner_id_tables, learner_id_col, logger, args.dry_run
        )

        # Step 6: Verify (unless dry-run or skip-verification)
        if not args.dry_run and not args.skip_verification:
            logger.info("Verifying migration...")
            if verify_migration(
                conn, mapping, learner_id_tables, learner_id_col, logger
            ):
                logger.info("OK: Migration verified successfully")
            else:
                logger.error(
                    "ERROR: Migration verification failed; database may be corrupted"
                )
                sys.exit(1)

        # Step 7: Log the mapping
        mapping_log = log_id_mapping(mapping, db_path, logger)

        # Final summary
        logger.info("=" * 70)
        if args.dry_run:
            logger.info("DRY-RUN completed (no changes were applied)")
        else:
            logger.info(f"OK: Migration completed successfully!")
            logger.info(f"  Learners migrated: {len(mapping)}")
            logger.info(f"  Backup: {backup_path}")
            logger.info(f"  Mapping log: {mapping_log}")
        logger.info("=" * 70)

        conn.close()
        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
