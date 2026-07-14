"""
Repository pattern: services never write SQL directly. Each repository
exposes a small CRUD contract (Repository ABC) so the data source can be
swapped (e.g. SQLite -> PostgreSQL) without touching business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from core.models import (
    Assignment,
    AssignmentGrade,
    Course,
    DifficultyLevel,
    CourseStatus,
    Enrollment,
    EnrollmentStatus,
)
from data.database import DatabaseManager


class Repository(ABC):
    @abstractmethod
    def create(self, entity):
        raise NotImplementedError

    @abstractmethod
    def read(self, entity_id):
        raise NotImplementedError

    @abstractmethod
    def update(self, entity):
        raise NotImplementedError

    @abstractmethod
    def delete(self, entity_id):
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> List:
        raise NotImplementedError


class CourseRepository(Repository):
    def __init__(self, db: DatabaseManager):
        self.conn = db.connection

    def create(self, course: Course) -> None:
        self.conn.execute(
            "INSERT INTO courses (code, name, description, difficulty, duration_hours, "
            "instructor, status, total_levels) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                course.code,
                course.name,
                course.description,
                course.difficulty.value,
                course.duration_hours,
                course.instructor,
                course.status.value,
                course.total_levels,
            ),
        )
        self.conn.commit()

    def read(self, code: str) -> Optional[Course]:
        row = self.conn.execute(
            "SELECT * FROM courses WHERE code = ?", (code.upper(),)
        ).fetchone()
        if not row:
            return None
        return self._row_to_course(row)

    def update(self, course: Course) -> None:
        self.conn.execute(
            "UPDATE courses SET name=?, description=?, difficulty=?, duration_hours=?, "
            "instructor=?, status=?, total_levels=? WHERE code=?",
            (
                course.name,
                course.description,
                course.difficulty.value,
                course.duration_hours,
                course.instructor,
                course.status.value,
                course.total_levels,
                course.code,
            ),
        )
        self.conn.commit()

    def delete(self, code: str) -> None:
        self.conn.execute("DELETE FROM courses WHERE code = ?", (code.upper(),))
        self.conn.commit()

    def list_all(self) -> List[Course]:
        rows = self.conn.execute("SELECT * FROM courses").fetchall()
        return [self._row_to_course(r) for r in rows]

    # ===== Admin course management operations =====

    def check_duplicate_code(self, code: str, exclude_code: str = None) -> bool:
        """
        Check if a course code already exists.

        Args:
            code: Course code to check
            exclude_code: Optionally exclude a code (for updates/renames)

        Returns:
            True if code exists, False if unique
        """
        cursor = self.conn.cursor()
        code_upper = code.upper()

        if exclude_code:
            cursor.execute(
                "SELECT 1 FROM courses WHERE code = ? AND code != ?",
                (code_upper, exclude_code.upper()),
            )
        else:
            cursor.execute("SELECT 1 FROM courses WHERE code = ?", (code_upper,))

        return cursor.fetchone() is not None

    def delete_cascade(self, code: str) -> None:
        """
        Delete a course and cascade-delete all related records.

        Deletes:
        - Course record
        - All enrollments for this course
        - All prerequisite links (both as dependent and as prerequisite)

        Uses a transaction to ensure atomicity.

        Args:
            code: Course code to delete
        """
        code_upper = code.upper()
        cursor = self.conn.cursor()

        try:
            cursor.execute("BEGIN TRANSACTION")

            # Delete enrollments (cascade by FK)
            cursor.execute(
                "DELETE FROM enrollments WHERE course_code = ?", (code_upper,)
            )

            # Delete prerequisite links (both directions)
            cursor.execute(
                "DELETE FROM prerequisites WHERE prereq_code = ? OR dependent_code = ?",
                (code_upper, code_upper),
            )

            # Delete the course
            cursor.execute("DELETE FROM courses WHERE code = ?", (code_upper,))

            cursor.execute("END TRANSACTION")

        except Exception as e:
            cursor.execute("ROLLBACK")
            raise e

    def update_course(
        self,
        code: str,
        name: str,
        description: str,
        difficulty: str,
        duration_hours: float,
        instructor: str,
        status: str,
        total_levels: int = 1,
    ) -> None:
        """
        Update course details with validation.

        Args:
            code: Course code (immutable)
            name: Course name
            description: Course description
            difficulty: Difficulty level
            duration_hours: Duration in hours
            instructor: Instructor name
            status: Course status

        Raises:
            ValueError: If course not found or validation fails
        """
        code_upper = code.upper()

        # Validate course exists
        if not self.read(code_upper):
            raise ValueError(f"Course {code_upper} not found")

        # Validate inputs
        if not name or not name.strip():
            raise ValueError("Course name cannot be empty")
        if duration_hours < 0:
            raise ValueError("Duration cannot be negative")

        self.conn.execute(
            "UPDATE courses SET name=?, description=?, difficulty=?, duration_hours=?, "
            "instructor=?, status=?, total_levels=? WHERE code=?",
            (
                name.strip(),
                description or "",
                difficulty,
                float(duration_hours),
                instructor or "",
                status,
                1 if total_levels is None else int(total_levels),
                code_upper,
            ),
        )
        self.conn.commit()

    # ---- prerequisites ----
    def add_prerequisite_link(self, prereq_code: str, dependent_code: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO prerequisites (prereq_code, dependent_code) VALUES (?, ?)",
            (prereq_code.upper(), dependent_code.upper()),
        )
        self.conn.commit()

    def remove_prerequisite_link(self, prereq_code: str, dependent_code: str) -> None:
        self.conn.execute(
            "DELETE FROM prerequisites WHERE prereq_code=? AND dependent_code=?",
            (prereq_code.upper(), dependent_code.upper()),
        )
        self.conn.commit()

    def get_direct_prerequisites(self, code: str) -> List[str]:
        rows = self.conn.execute(
            "SELECT prereq_code FROM prerequisites WHERE dependent_code=?",
            (code.upper(),),
        ).fetchall()
        return [r["prereq_code"] for r in rows]

    def get_all_prerequisite_links(self) -> List[tuple]:
        rows = self.conn.execute(
            "SELECT prereq_code, dependent_code FROM prerequisites"
        ).fetchall()
        return [(r["prereq_code"], r["dependent_code"]) for r in rows]

    @staticmethod
    def _row_to_course(row) -> Course:
        c = Course(
            code=row["code"],
            name=row["name"],
            description=row["description"] or "",
            difficulty=DifficultyLevel(row["difficulty"]),
            duration_hours=row["duration_hours"],
            instructor=row["instructor"] or "",
            status=CourseStatus(row["status"]),
            total_levels=row["total_levels"] if "total_levels" in row.keys() else 1,
        )
        return c


class AssignmentRepository(Repository):
    def __init__(self, db: DatabaseManager):
        self.conn = db.connection

    def create(self, assignment: Assignment) -> None:
        self.conn.execute(
            "INSERT INTO assignments (assignment_id, course_code, level_number, title, description, due_date) VALUES (?, ?, ?, ?, ?, ?)",
            (
                assignment.assignment_id,
                assignment.course_code,
                assignment.level_number,
                assignment.title,
                assignment.description,
                assignment.due_date,
            ),
        )
        self.conn.commit()

    def read(self, assignment_id: str) -> Optional[Assignment]:
        row = self.conn.execute(
            "SELECT * FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        return self._row_to_assignment(row) if row else None

    def update(self, assignment: Assignment) -> None:
        self.conn.execute(
            "UPDATE assignments SET course_code=?, level_number=?, title=?, description=?, due_date=? WHERE assignment_id=?",
            (
                assignment.course_code,
                assignment.level_number,
                assignment.title,
                assignment.description,
                assignment.due_date,
                assignment.assignment_id,
            ),
        )
        self.conn.commit()

    def delete(self, assignment_id: str) -> None:
        self.conn.execute(
            "DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,)
        )
        self.conn.commit()

    def list_all(self) -> List[Assignment]:
        rows = self.conn.execute("SELECT * FROM assignments").fetchall()
        return [self._row_to_assignment(r) for r in rows]

    def list_for_course(self, course_code: str) -> List[Assignment]:
        rows = self.conn.execute(
            "SELECT * FROM assignments WHERE course_code=? ORDER BY level_number, assignment_id",
            (course_code.upper(),),
        ).fetchall()
        return [self._row_to_assignment(r) for r in rows]

    def list_for_level(self, course_code: str, level_number: int) -> List[Assignment]:
        rows = self.conn.execute(
            "SELECT * FROM assignments WHERE course_code=? AND level_number=? ORDER BY assignment_id",
            (course_code.upper(), level_number),
        ).fetchall()
        return [self._row_to_assignment(r) for r in rows]

    @staticmethod
    def _row_to_assignment(row) -> Assignment:
        return Assignment(
            assignment_id=row["assignment_id"],
            course_code=row["course_code"],
            level_number=row["level_number"],
            title=row["title"],
            description=row["description"] or "",
            due_date=row["due_date"],
        )


class AssignmentGradeRepository(Repository):
    def __init__(self, db: DatabaseManager):
        self.conn = db.connection

    def create(self, grade: AssignmentGrade) -> None:
        self.conn.execute(
            "INSERT INTO assignment_grades (assignment_id, learner_id, score_percent, graded_at, attempt_number) VALUES (?, ?, ?, ?, ?)",
            (
                grade.assignment_id,
                grade.learner_id,
                grade.score_percent,
                grade.graded_at,
                grade.attempt_number,
            ),
        )
        self.conn.commit()

    def read(self, assignment_id: str, learner_id: str, attempt_number: int):
        row = self.conn.execute(
            "SELECT * FROM assignment_grades WHERE assignment_id=? AND learner_id=? AND attempt_number=?",
            (assignment_id, learner_id, attempt_number),
        ).fetchone()
        return self._row_to_grade(row) if row else None

    def update(self, grade: AssignmentGrade) -> None:
        self.conn.execute(
            "UPDATE assignment_grades SET score_percent=?, graded_at=? WHERE assignment_id=? AND learner_id=? AND attempt_number=?",
            (
                grade.score_percent,
                grade.graded_at,
                grade.assignment_id,
                grade.learner_id,
                grade.attempt_number,
            ),
        )
        self.conn.commit()

    def delete(self, assignment_id: str) -> None:
        self.conn.execute(
            "DELETE FROM assignment_grades WHERE assignment_id = ?", (assignment_id,)
        )
        self.conn.commit()

    def list_all(self) -> List[AssignmentGrade]:
        rows = self.conn.execute("SELECT * FROM assignment_grades").fetchall()
        return [self._row_to_grade(r) for r in rows]

    def list_for_learner(self, learner_id: str) -> List[AssignmentGrade]:
        rows = self.conn.execute(
            "SELECT * FROM assignment_grades WHERE learner_id=? ORDER BY graded_at",
            (learner_id,),
        ).fetchall()
        return [self._row_to_grade(r) for r in rows]

    def list_for_assignment(self, assignment_id: str) -> List[AssignmentGrade]:
        rows = self.conn.execute(
            "SELECT * FROM assignment_grades WHERE assignment_id=? ORDER BY attempt_number",
            (assignment_id,),
        ).fetchall()
        return [self._row_to_grade(r) for r in rows]

    @staticmethod
    def _row_to_grade(row) -> AssignmentGrade:
        return AssignmentGrade(
            assignment_id=row["assignment_id"],
            learner_id=row["learner_id"],
            score_percent=row["score_percent"],
            graded_at=row["graded_at"],
            attempt_number=row["attempt_number"],
        )


class LearnerRepository(Repository):
    def __init__(self, db: DatabaseManager):
        self.conn = db.connection

    def create(self, learner) -> None:
        self.conn.execute(
            "INSERT INTO learners (learner_id, name, email) VALUES (?, ?, ?)",
            (learner["learner_id"], learner["name"], learner["email"]),
        )
        self.conn.commit()

    def find_by_email(self, email: str):
        row = self.conn.execute(
            "SELECT * FROM learners WHERE lower(email)=?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None

    def read(self, learner_id: str):
        row = self.conn.execute(
            "SELECT * FROM learners WHERE learner_id=?", (learner_id,)
        ).fetchone()
        return dict(row) if row else None

    def update(self, learner) -> None:
        self.conn.execute(
            "UPDATE learners SET name=?, email=?, date_registered=? WHERE learner_id=?",
            (
                learner["name"],
                learner["email"],
                learner.get("date_registered"),
                learner["learner_id"],
            ),
        )
        self.conn.commit()

    def delete(self, learner_id: str) -> None:
        self.conn.execute("DELETE FROM learners WHERE learner_id=?", (learner_id,))
        self.conn.commit()

    def list_all(self) -> List[dict]:
        # Order by `date_registered` (new DB column) to reflect registration timeline
        # fall back to rowid if date_registered is NULL for any row
        rows = self.conn.execute(
            "SELECT * FROM learners ORDER BY COALESCE(date_registered, (SELECT datetime(0, 'unixepoch')), rowid)"
        ).fetchall()
        return [dict(r) for r in rows]

    # ===== Admin CRUD operations =====

    def create_with_auto_id(
        self, name: str, email: str, date_registered: str = None
    ) -> str:
        """
        Create a learner with auto-generated ID (L001, L002, etc.).

        Args:
            name: Learner name
            email: Learner email
            date_registered: ISO timestamp (auto-set to now if None)

        Returns:
            The generated learner_id (e.g., "L001")
        """
        from datetime import datetime

        if date_registered is None:
            date_registered = datetime.now().isoformat()

        # Get next ID
        cursor = self.conn.cursor()
        cursor.execute("SELECT learner_id FROM learners")
        rows = cursor.fetchall()

        max_num = 0
        for row in rows:
            learner_id = row[0]
            if learner_id.startswith("L") and learner_id[1:].isdigit():
                num = int(learner_id[1:])
                max_num = max(max_num, num)

        next_id = f"L{max_num + 1:03d}"

        # Create learner
        self.conn.execute(
            "INSERT INTO learners (learner_id, name, email, date_registered) VALUES (?, ?, ?, ?)",
            (next_id, name, email, date_registered),
        )
        self.conn.commit()

        return next_id

    def change_learner_id(self, old_id: str, new_id: str) -> None:
        """
        Change a learner's ID and update all references across all tables.

        This is a transactional operation that:
        1. Updates the learner's ID
        2. Updates all enrollment references
        3. Updates all other referencing tables (if they exist)
        4. Updates the linked user account's ID (if exists)

        Uses defer_foreign_keys to handle constraint checking at transaction end.

        Args:
            old_id: Current learner ID
            new_id: New learner ID

        Raises:
            ValueError: If old_id doesn't exist or new_id already exists
        """
        cursor = self.conn.cursor()

        # Validate
        cursor.execute("SELECT 1 FROM learners WHERE learner_id = ?", (old_id,))
        if not cursor.fetchone():
            raise ValueError(f"Learner {old_id} not found")

        cursor.execute("SELECT 1 FROM learners WHERE learner_id = ?", (new_id,))
        if cursor.fetchone():
            raise ValueError(f"Learner ID {new_id} already exists")

        try:
            cursor.execute("BEGIN TRANSACTION")
            cursor.execute("PRAGMA defer_foreign_keys = ON")

            # Update learners table
            cursor.execute(
                "UPDATE learners SET learner_id = ? WHERE learner_id = ?",
                (new_id, old_id),
            )

            # Update enrollments
            cursor.execute(
                "UPDATE enrollments SET learner_id = ? WHERE learner_id = ?",
                (new_id, old_id),
            )

            # Update users table if linked account exists
            cursor.execute(
                "UPDATE users SET user_id = ? WHERE user_id = ?", (new_id, old_id)
            )

            # Update any other tables that might reference learner_id
            # (This would include progress, certificates, attendance, etc. if they exist)
            tables_to_check = ["progress", "certificates", "attendance"]
            for table in tables_to_check:
                cursor.execute(f"PRAGMA table_info({table})")
                if cursor.fetchone():  # Table exists
                    cursor.execute(
                        f"UPDATE {table} SET learner_id = ? WHERE learner_id = ?",
                        (new_id, old_id),
                    )

            cursor.execute("END TRANSACTION")
            cursor.execute("PRAGMA defer_foreign_keys = OFF")

        except Exception as e:
            cursor.execute("ROLLBACK")
            cursor.execute("PRAGMA defer_foreign_keys = OFF")
            raise e

    def delete_cascade(self, learner_id: str) -> None:
        """
        Delete a learner and cascade-delete all related records.

        Deletes:
        - Learner record
        - All enrollments
        - All related accounts (users with this learner_id)
        - All progress/certificates/attendance records (if tables exist)

        Uses a transaction to ensure atomicity.

        Args:
            learner_id: ID of learner to delete
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("BEGIN TRANSACTION")

            # Delete user account if exists
            cursor.execute("DELETE FROM users WHERE user_id = ?", (learner_id,))

            # Enrollments are cascade-deleted by FK constraint
            # But we can explicitly delete for clarity
            cursor.execute(
                "DELETE FROM enrollments WHERE learner_id = ?", (learner_id,)
            )

            # Delete from related tables if they exist
            tables_to_check = ["progress", "certificates", "attendance"]
            for table in tables_to_check:
                cursor.execute(f"PRAGMA table_info({table})")
                if cursor.fetchone():  # Table exists
                    cursor.execute(
                        f"DELETE FROM {table} WHERE learner_id = ?", (learner_id,)
                    )

            # Finally, delete the learner
            cursor.execute("DELETE FROM learners WHERE learner_id = ?", (learner_id,))

            cursor.execute("END TRANSACTION")

        except Exception as e:
            cursor.execute("ROLLBACK")
            raise e

    def check_duplicate_email(self, email: str, exclude_learner_id: str = None) -> bool:
        """
        Check if an email is already used by another learner.

        Args:
            email: Email to check
            exclude_learner_id: Optionally exclude a learner's email (for updates)

        Returns:
            True if email is duplicate, False if unique
        """
        cursor = self.conn.cursor()

        if exclude_learner_id:
            cursor.execute(
                "SELECT 1 FROM learners WHERE email = ? AND learner_id != ?",
                (email.strip().lower(), exclude_learner_id),
            )
        else:
            cursor.execute(
                "SELECT 1 FROM learners WHERE email = ?", (email.strip().lower(),)
            )

        return cursor.fetchone() is not None

    def update_with_validation(
        self, learner_id: str, name: str, email: str, date_registered: str = None
    ) -> None:
        """
        Update a learner's details with validation.

        Args:
            learner_id: ID of learner to update
            name: New name
            email: New email
            date_registered: New registration date (optional)

        Raises:
            ValueError: If learner not found or email already in use
        """
        cursor = self.conn.cursor()

        # Validate learner exists
        cursor.execute("SELECT 1 FROM learners WHERE learner_id = ?", (learner_id,))
        if not cursor.fetchone():
            raise ValueError(f"Learner {learner_id} not found")

        # Check for duplicate email
        if self.check_duplicate_email(email, exclude_learner_id=learner_id):
            raise ValueError(f"Email {email} is already in use")

        self.conn.execute(
            "UPDATE learners SET name=?, email=?, date_registered=? WHERE learner_id=?",
            (name, email, date_registered, learner_id),
        )
        self.conn.commit()


class EnrollmentRepository(Repository):
    def __init__(self, db: DatabaseManager):
        self.conn = db.connection

    def create(self, enrollment: Enrollment) -> None:
        self.conn.execute(
            "INSERT INTO enrollments (learner_id, course_code, status, score, "
            "enrolled_date, completed_date, current_level, latest_score_percent, attempt_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                enrollment.learner_id,
                enrollment.course_code,
                enrollment.status.value,
                enrollment.score,
                enrollment.enrolled_date,
                enrollment.completed_date,
                enrollment.current_level,
                enrollment.latest_score_percent,
                enrollment.attempt_count,
            ),
        )
        self.conn.commit()

    def read(self, key: tuple) -> Optional[Enrollment]:
        learner_id, course_code = key
        row = self.conn.execute(
            "SELECT * FROM enrollments WHERE learner_id=? AND course_code=?",
            (learner_id, course_code),
        ).fetchone()
        return self._row_to_enrollment(row) if row else None

    def update(self, enrollment: Enrollment) -> None:
        self.conn.execute(
            "UPDATE enrollments SET status=?, score=?, completed_date=?, current_level=?, latest_score_percent=?, attempt_count=? "
            "WHERE learner_id=? AND course_code=?",
            (
                enrollment.status.value,
                enrollment.score,
                enrollment.completed_date,
                enrollment.current_level,
                enrollment.latest_score_percent,
                enrollment.attempt_count,
                enrollment.learner_id,
                enrollment.course_code,
            ),
        )
        self.conn.commit()

    def delete(self, key: tuple) -> None:
        learner_id, course_code = key
        self.conn.execute(
            "DELETE FROM enrollments WHERE learner_id=? AND course_code=?",
            (learner_id, course_code),
        )
        self.conn.commit()

    def list_all(self) -> List[Enrollment]:
        # Order enrollments by the learner's registration time (learners.date_registered)
        rows = self.conn.execute(
            "SELECT * FROM enrollments ORDER BY (SELECT date_registered FROM learners WHERE learners.learner_id = enrollments.learner_id)"
        ).fetchall()
        return [self._row_to_enrollment(r) for r in rows]

    def list_for_learner(self, learner_id: str) -> List[Enrollment]:
        rows = self.conn.execute(
            "SELECT * FROM enrollments WHERE learner_id=?", (learner_id,)
        ).fetchall()
        return [self._row_to_enrollment(r) for r in rows]

    def list_for_course(self, course_code: str) -> List[Enrollment]:
        # Order by learner registration time so instructor/course views are stable
        rows = self.conn.execute(
            "SELECT * FROM enrollments WHERE course_code=? ORDER BY (SELECT date_registered FROM learners WHERE learners.learner_id = enrollments.learner_id)",
            (course_code,),
        ).fetchall()
        return [self._row_to_enrollment(r) for r in rows]

    @staticmethod
    def _row_to_enrollment(row) -> Enrollment:
        return Enrollment(
            learner_id=row["learner_id"],
            course_code=row["course_code"],
            status=EnrollmentStatus(row["status"]),
            score=row["score"],
            enrolled_date=row["enrolled_date"],
            completed_date=row["completed_date"],
            current_level=row["current_level"],
            latest_score_percent=row["latest_score_percent"],
            attempt_count=row["attempt_count"],
        )


class UserRepository(Repository):
    """Stores Instructor / Learner / Analyst login accounts (Admin is a fixed constant)."""

    def __init__(self, db: DatabaseManager):
        self.conn = db.connection

    def create(self, user: dict) -> None:
        self.conn.execute(
            "INSERT INTO users (user_id, name, email, password, role) VALUES (?, ?, ?, ?, ?)",
            (
                user["user_id"],
                user["name"],
                user["email"],
                user["password"],
                user["role"],
            ),
        )
        self.conn.commit()

    def read(self, user_id: str):
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_by_email(self, email: str):
        row = self.conn.execute(
            "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None

    def update(self, user: dict) -> None:
        self.conn.execute(
            "UPDATE users SET name=?, email=?, password=?, role=? WHERE user_id=?",
            (
                user["name"],
                user["email"],
                user["password"],
                user["role"],
                user["user_id"],
            ),
        )
        self.conn.commit()

    def delete(self, user_id: str) -> None:
        self.conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        self.conn.commit()

    def list_all(self) -> List[dict]:
        rows = self.conn.execute("SELECT * FROM users").fetchall()
        return [dict(r) for r in rows]

    # ===== Admin account management operations =====

    def create_with_id(
        self, user_id: str, name: str, email: str, password: str, role: str
    ) -> None:
        """
        Create a user account with a specific ID.

        Used for creating Learner accounts where the user_id is the learner_id.

        Args:
            user_id: Explicit user ID
            name: User name
            email: User email
            password: User password (plaintext for now)
            role: User role (Administrator, Instructor, Learner, Analyst)

        Raises:
            ValueError: If user_id or email already exists
        """
        # Check for duplicates
        if self.read(user_id):
            raise ValueError(f"User ID {user_id} already exists")
        if self.find_by_email(email):
            raise ValueError(f"Email {email} is already in use")

        self.conn.execute(
            "INSERT INTO users (user_id, name, email, password, role) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, email.strip().lower(), password, role),
        )
        self.conn.commit()

    def update_account(
        self, user_id: str, name: str, email: str, password: str, role: str
    ) -> None:
        """
        Update a user account.

        Args:
            user_id: User ID
            name: New name
            email: New email
            password: New password
            role: New role

        Raises:
            ValueError: If user not found or email already in use by another user
        """
        # Validate user exists
        if not self.read(user_id):
            raise ValueError(f"User {user_id} not found")

        # Check email uniqueness (excluding self)
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM users WHERE email = ? AND user_id != ?",
            (email.strip().lower(), user_id),
        )
        if cursor.fetchone():
            raise ValueError(f"Email {email} is already in use")

        self.update(
            {
                "user_id": user_id,
                "name": name,
                "email": email.strip().lower(),
                "password": password,
                "role": role,
            }
        )

    def change_user_id(self, old_id: str, new_id: str) -> None:
        """
        Change a user account's ID (primary key) and update any references.

        For Learner accounts this also updates the linked `learners` row and
        every `enrollments` row so the account and its learner profile stay
        in sync; for Instructor/Analyst accounts there is no secondary table
        to update.

        Args:
            old_id: Current user ID
            new_id: New user ID

        Raises:
            ValueError: If old_id doesn't exist or new_id already exists
        """
        cursor = self.conn.cursor()

        row = cursor.execute(
            "SELECT * FROM users WHERE user_id = ?", (old_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"User {old_id} not found")

        if cursor.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (new_id,)
        ).fetchone():
            raise ValueError(f"User ID {new_id} already exists")

        role = row["role"]

        try:
            cursor.execute("BEGIN TRANSACTION")
            cursor.execute("PRAGMA defer_foreign_keys = ON")

            cursor.execute(
                "UPDATE users SET user_id = ? WHERE user_id = ?", (new_id, old_id)
            )

            if role == "Learner":
                cursor.execute(
                    "UPDATE learners SET learner_id = ? WHERE learner_id = ?",
                    (new_id, old_id),
                )
                cursor.execute(
                    "UPDATE enrollments SET learner_id = ? WHERE learner_id = ?",
                    (new_id, old_id),
                )

            cursor.execute("END TRANSACTION")
            cursor.execute("PRAGMA defer_foreign_keys = OFF")

        except Exception as e:
            cursor.execute("ROLLBACK")
            cursor.execute("PRAGMA defer_foreign_keys = OFF")
            raise e

    def delete_cascade(self, user_id: str) -> None:
        """
        Delete a user account and cascade-delete related records.

        If the user is a Learner, also deletes their learner profile and all enrollments.

        Args:
            user_id: User ID to delete
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("BEGIN TRANSACTION")

            # Get user role
            cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"User {user_id} not found")

            role = row[0]

            # If it's a Learner, also delete the learner profile and enrollments
            if role == "Learner":
                cursor.execute(
                    "DELETE FROM enrollments WHERE learner_id = ?", (user_id,)
                )
                cursor.execute("DELETE FROM learners WHERE learner_id = ?", (user_id,))

            # Delete the user account
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

            cursor.execute("END TRANSACTION")

        except Exception as e:
            cursor.execute("ROLLBACK")
            raise e

    def check_duplicate_email(self, email: str, exclude_user_id: str = None) -> bool:
        """
        Check if an email is already used by another user.

        Args:
            email: Email to check
            exclude_user_id: Optionally exclude a user's email (for updates)

        Returns:
            True if email is duplicate, False if unique
        """
        cursor = self.conn.cursor()

        if exclude_user_id:
            cursor.execute(
                "SELECT 1 FROM users WHERE email = ? AND user_id != ?",
                (email.strip().lower(), exclude_user_id),
            )
        else:
            cursor.execute(
                "SELECT 1 FROM users WHERE email = ?", (email.strip().lower(),)
            )

        return cursor.fetchone() is not None
