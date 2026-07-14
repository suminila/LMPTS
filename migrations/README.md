# Learner ID Renumbering Migration

## Overview

This migration script renumbers all learner IDs in the database to a clean sequential format (`L001`, `L002`, `L003`, ...) ordered by learner registration date.

## Status

**Current Status**: ✅ **COMPLETED** (as of 2026-07-09 20:09:43 UTC)

The migration has been successfully applied to the production database:
- **Learners migrated**: 22
- **Database backup**: `lmpts_backup_20260709_200943.db`
- **Mapping log**: `migrations_logs/learner_id_mapping_20260709_200943.txt`
- **Full log**: `migrations_logs/renumber_learner_ids_20260709_200943.log`

## What the Migration Does

1. **Backs up the database** before making any changes (timestamped)
2. **Detects registration order** using the `date_registered` column (ordered by learner's signup date)
3. **Creates a mapping** from old random IDs to new sequential IDs:
   - Example: `L015 -> L001`, `L013 -> L002`, `L011 -> L003`, etc.
4. **Updates all tables** that reference learner IDs:
   - `learners.learner_id` (primary key)
   - `enrollments.learner_id` (foreign key)
   - Any other table with a `learner_id` column (auto-discovered)
5. **Handles constraints safely** using a three-phase transaction strategy to avoid UNIQUE constraint violations
6. **Verifies data integrity** after migration
7. **Logs everything** for audit trail and reversal capability

## How to Use

### Normal Usage

```bash
python migrations/renumber_learner_ids.py /path/to/lmpts.db
```

This will:
- Create a timestamped backup of the database
- Check if already migrated (idempotency)
- Perform the migration if needed
- Verify the results
- Log the mapping

### Dry-Run Mode (Preview Only)

```bash
python migrations/renumber_learner_ids.py /path/to/lmpts.db --dry-run
```

Shows exactly what would be changed without modifying the database. Useful for:
- Reviewing the mapping before applying
- Testing on a copy first
- Understanding the scope of changes

### Backup Only

```bash
python migrations/renumber_learner_ids.py /path/to/lmpts.db --backup-only
```

Creates a backup and exits without migrating. Useful for:
- Pre-migration backups
- Testing backup functionality

### Skip Verification

```bash
python migrations/renumber_learner_ids.py /path/to/lmpts.db --skip-verification
```

Skips the post-migration verification step (not recommended unless you know what you're doing).

## Key Features

### 1. **Idempotent**
Running the script multiple times is safe. It detects if IDs are already sequential and skips migration if not needed.

```bash
# First run: migrates 22 learners
python migrations/renumber_learner_ids.py lmpts.db

# Second run: detects already-migrated state and exits immediately
python migrations/renumber_learner_ids.py lmpts.db
```

### 2. **Transactional Safety**
The entire migration happens in a single database transaction:
- All updates succeed together, or all roll back
- No partial states or orphaned data
- Foreign key constraints verified at end

### 3. **Handles Complex Constraints**
Uses a three-phase update strategy to safely update:
- Primary key constraints (`learners.learner_id PRIMARY KEY`)
- UNIQUE constraints (`enrollments UNIQUE(learner_id, course_code)`)
- Foreign key constraints (all referencing tables)

Strategy:
1. **Phase 1**: Child tables `old_id -> _TEMP_####`
2. **Phase 2**: Parent table `old_id -> new_id` (via temp IDs to avoid PK violation)
3. **Phase 3**: Child tables `_TEMP_#### -> new_id`

### 4. **Comprehensive Logging**
Creates two log files per run:
- **Migration log** (`renumber_learner_ids_YYYYMMDD_HHMMSS.log`): Full debug trace
- **Mapping log** (`learner_id_mapping_YYYYMMDD_HHMMSS.txt`): Old->New ID mapping for audit/reversal

Location: `migrations_logs/`

### 5. **Automatic Schema Discovery**
Discovers all tables with `learner_id` columns automatically:
- `learners` (primary table)
- `enrollments` (referencing table)
- Any future tables added with `learner_id` foreign keys

### 6. **Registration Order Preservation**
Orders learners by registration date (detects column: `date_registered`, `created_at`, `registration_date`, `date_created`, or `rowid`):
- First registered learner gets `L001`
- Second registered learner gets `L002`
- And so on...

## Migration Details

### Before Migration

```
Learners (unsorted by ID):
L015 - Nisha      (registered: 2000-01-01 00:00:00)
L013 - Narmatha   (registered: 2000-01-01 00:00:01)
L011 - joy        (registered: 2000-01-01 00:00:02)
L004 - learn      (registered: 2000-01-01 00:00:03)
L009 - Ram        (registered: 2000-01-01 00:00:04)
... (18 more)
```

### After Migration

```
Learners (sequential by registration time):
L001 - Nisha      (registered: 2000-01-01 00:00:00)
L002 - Narmatha   (registered: 2000-01-01 00:00:01)
L003 - joy        (registered: 2000-01-01 00:00:02)
L004 - learn      (registered: 2000-01-01 00:00:03)
L005 - Ram        (registered: 2000-01-01 00:00:04)
... (17 more, all sequential)
```

All enrollments and other references automatically updated to match.

## Mapping File

The migration log includes a complete old->new mapping:

```
Learner ID Renumbering Mapping
Generated: 2026-07-09T20:09:43.578455
Database: lmpts.db
============================================================

OLD ID          -> NEW ID         
------------------------------------------------------------
L015            -> L001           
L013            -> L002           
L011            -> L003           
L004            -> L004           
L009            -> L005           
...
```

This mapping can be used for:
- Auditing changes
- Reversing the migration (if needed)
- Correlating old and new IDs for external systems

## Requirements

- Python 3.7+
- SQLite3 (included with Python)
- Write access to database file and parent directory
- Sufficient disk space for backup copy

## Error Handling

If the migration fails:
1. Database is automatically rolled back to original state
2. Error message logged with full traceback
3. Backup remains available for manual recovery
4. No partial updates applied

Example error handling:

```bash
# If error occurs:
# - Transaction is rolled back
# - Database file unchanged
# - Backup file preserved
# - Error logged to migrations_logs/renumber_learner_ids_*.log
```

## Backup Recovery

If you need to revert to the pre-migration state:

```bash
# Restore from backup
cp lmpts_backup_20260709_200943.db lmpts.db
```

Then the idempotency check will re-apply the migration when ready.

## Integration Notes

### For CI/CD Pipelines
Run as a one-time setup step before app startup:

```bash
# In deployment script
python migrations/renumber_learner_ids.py ${DB_PATH} || exit 1
```

The script exits with code `0` on success (including no-op when already migrated).

### For Docker/Containers
```dockerfile
RUN python migrations/renumber_learner_ids.py /data/lmpts.db
```

### For Manual Administration
```bash
# Review what will change
python migrations/renumber_learner_ids.py lmpts.db --dry-run

# Apply migration
python migrations/renumber_learner_ids.py lmpts.db

# Verify
sqlite3 lmpts.db "SELECT learner_id FROM learners ORDER BY rowid LIMIT 5;"
```

## Technical Details

### Three-Phase Transaction Strategy

This approach safely handles PRIMARY KEY and UNIQUE constraints:

**Problem**: 
- Can't directly update primary key from L001 to L002 if both rows exist
- UNIQUE(learner_id, course_code) prevents intermediate states

**Solution**:
- Use temporary IDs (`_TEMP_0001`, `_TEMP_0002`, etc.) that don't conflict
- Phase 1: Old IDs in child tables -> Temp IDs (avoids FK violations)
- Phase 2: Old IDs in parent table -> Final IDs (via temp -> final)
- Phase 3: Temp IDs in child tables -> Final IDs (completes the update)

### Foreign Key Handling

```sql
PRAGMA defer_foreign_keys = ON;  -- Check FK at END not per-UPDATE
BEGIN TRANSACTION;
  -- Updates here
  UPDATE enrollments SET learner_id = '_TEMP_0001' WHERE learner_id = 'L015';
  UPDATE learners SET learner_id = 'L001' WHERE learner_id = '_TEMP_0001';
  UPDATE enrollments SET learner_id = 'L001' WHERE learner_id = '_TEMP_0001';
COMMIT;  -- FK constraints verified once at transaction end
```

## Support & Troubleshooting

### Common Issues

**"Database is locked"**
- Close any other connections to the database
- Check for other running processes using the `.db` file

**"UNIQUE constraint failed"** (shouldn't happen with latest version)
- This indicates a two-learner conflict on (learner_id, course_code)
- Check `migrations_logs/*.log` for details
- Restore from backup and retry

**"No learner_id column found"**
- Database schema doesn't match expected structure
- Check `PRAGMA table_info(learners)` in database

### Diagnostics

Check migration status:
```bash
# View last log
tail -50 migrations_logs/renumber_learner_ids_*.log

# View mapping
cat migrations_logs/learner_id_mapping_*.txt

# Verify in database
sqlite3 lmpts.db "SELECT COUNT(*), MIN(learner_id), MAX(learner_id) FROM learners;"
```

## Questions or Issues?

Refer to the detailed log files:
- **Error details**: `migrations_logs/renumber_learner_ids_*.log`
- **ID mapping**: `migrations_logs/learner_id_mapping_*.txt`

Or review the script documentation at the top of `renumber_learner_ids.py`.
