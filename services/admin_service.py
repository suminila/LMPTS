"""
Admin services layer: business logic for admin CRUD operations on learners, accounts, and courses.

Services handle:
- Input validation and domain error checking
- Business rule enforcement
- Coordination across repositories
- Transaction management
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from datetime import datetime

from core.exceptions import (
    EntityValidationError,
    DuplicateEntityError,
    LearnerNotFoundError,
    CourseNotFoundError,
)
from core.models import (
    Course,
    DifficultyLevel,
    CourseStatus,
    UserRole,
)
from data.repository import (
    LearnerRepository,
    UserRepository,
    CourseRepository,
)
from data.database import DatabaseManager

# --------------------------------------------------------------------------- #
# Validation Utilities
# --------------------------------------------------------------------------- #


def validate_email(email: str) -> Tuple[bool, str]:
    """
    Validate email format.

    Returns:
        (is_valid, error_message)
    """
    if not email or not email.strip():
        return False, "Email cannot be empty"

    # Simple email validation
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email.strip()):
        return False, "Email format is invalid"

    return True, ""


def validate_name(name: str) -> Tuple[bool, str]:
    """
    Validate name field.

    Returns:
        (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Name cannot be empty"

    if len(name.strip()) < 2:
        return False, "Name must be at least 2 characters"

    return True, ""


def validate_learner_id(learner_id: str) -> Tuple[bool, str]:
    """
    Validate learner ID format (L followed by digits).

    Returns:
        (is_valid, error_message)
    """
    if not learner_id or not learner_id.strip():
        return False, "Learner ID cannot be empty"

    learner_id = learner_id.strip().upper()

    if not learner_id.startswith("L") or len(learner_id) < 2:
        return False, "Learner ID must start with 'L' followed by digits"

    if not learner_id[1:].isdigit():
        return False, "Learner ID must contain only digits after 'L'"

    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    """
    Validate password field.

    Returns:
        (is_valid, error_message)
    """
    if not password:
        return False, "Password cannot be empty"

    if len(password) < 4:
        return False, "Password must be at least 4 characters"

    return True, ""


# --------------------------------------------------------------------------- #
# Learner Admin Service
# --------------------------------------------------------------------------- #


class LearnerAdminService:
    """Admin service for learner CRUD operations."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.repo = LearnerRepository(self.db)

    def create_learner(self, name: str, email: str) -> Tuple[bool, str, Optional[str]]:
        """
        Create a new learner with auto-generated ID.

        Args:
            name: Learner name
            email: Learner email

        Returns:
            (success, message, learner_id)
            - success: True if created, False if validation error
            - message: Error message if failed, empty if successful
            - learner_id: Generated ID if successful, None if failed
        """
        # Validate inputs
        is_valid, msg = validate_name(name)
        if not is_valid:
            return False, msg, None

        is_valid, msg = validate_email(email)
        if not is_valid:
            return False, msg, None

        # Check email uniqueness
        if self.repo.check_duplicate_email(email):
            return False, f"Email '{email}' is already in use", None

        try:
            learner_id = self.repo.create_with_auto_id(
                name=name.strip(),
                email=email.strip().lower(),
                date_registered=datetime.now().isoformat(),
            )
            return True, "", learner_id

        except Exception as e:
            return False, f"Failed to create learner: {str(e)}", None

    def update_learner(
        self, learner_id: str, name: str, email: str
    ) -> Tuple[bool, str]:
        """
        Update learner details.

        Args:
            learner_id: Learner ID
            name: New name
            email: New email

        Returns:
            (success, message)
        """
        # Validate inputs
        is_valid, msg = validate_name(name)
        if not is_valid:
            return False, msg

        is_valid, msg = validate_email(email)
        if not is_valid:
            return False, msg

        # Check if learner exists
        existing = self.repo.read(learner_id)
        if not existing:
            return False, f"Learner '{learner_id}' not found"

        # Check email uniqueness (excluding self)
        if self.repo.check_duplicate_email(email, exclude_learner_id=learner_id):
            return False, f"Email '{email}' is already in use by another learner"

        try:
            self.repo.update_with_validation(
                learner_id=learner_id, name=name.strip(), email=email.strip().lower()
            )
            return True, ""

        except Exception as e:
            return False, f"Failed to update learner: {str(e)}"

    def change_learner_id(self, old_id: str, new_id: str) -> Tuple[bool, str]:
        """
        Change a learner's ID (updates all references).

        Args:
            old_id: Current learner ID
            new_id: New learner ID

        Returns:
            (success, message)
        """
        # Validate new ID format
        is_valid, msg = validate_learner_id(new_id)
        if not is_valid:
            return False, msg

        # Validate old ID exists
        existing = self.repo.read(old_id)
        if not existing:
            return False, f"Learner '{old_id}' not found"

        # Check new ID doesn't already exist
        if self.repo.read(new_id):
            return False, f"Learner ID '{new_id}' already exists"

        try:
            self.repo.change_learner_id(old_id, new_id)
            return True, ""

        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Failed to change learner ID: {str(e)}"

    def delete_learner(self, learner_id: str) -> Tuple[bool, str]:
        """
        Delete a learner and cascade-delete all related records.

        Args:
            learner_id: Learner ID to delete

        Returns:
            (success, message)
        """
        # Validate learner exists
        existing = self.repo.read(learner_id)
        if not existing:
            return False, f"Learner '{learner_id}' not found"

        try:
            self.repo.delete_cascade(learner_id)
            return True, ""

        except Exception as e:
            return False, f"Failed to delete learner: {str(e)}"

    def list_all_learners(self) -> List[dict]:
        """Get all learners ordered by registration date."""
        return self.repo.list_all()


# --------------------------------------------------------------------------- #
# Account Admin Service
# --------------------------------------------------------------------------- #


class AccountAdminService:
    """Admin service for user account CRUD operations."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.user_repo = UserRepository(self.db)
        self.learner_repo = LearnerRepository(self.db)

    def create_account(
        self, user_id: str, name: str, email: str, password: str, role: str
    ) -> Tuple[bool, str]:
        """
        Create a new user account.

        If role is "Learner", also creates the learner profile with auto-generated ID.

        Args:
            user_id: User ID (or learner_id if Learner role)
            name: User name
            email: User email
            password: User password
            role: User role

        Returns:
            (success, message)
        """
        # Validate inputs
        is_valid, msg = validate_name(name)
        if not is_valid:
            return False, msg

        is_valid, msg = validate_email(email)
        if not is_valid:
            return False, msg

        is_valid, msg = validate_password(password)
        if not is_valid:
            return False, msg

        if role not in ["Administrator", "Instructor", "Learner", "Analyst"]:
            return False, "Invalid role"

        # Check for duplicate email
        if self.user_repo.check_duplicate_email(email):
            return False, f"Email '{email}' is already in use"

        # Check for duplicate user_id
        if self.user_repo.read(user_id):
            return False, f"User ID '{user_id}' already exists"

        try:
            self.user_repo.create_with_id(
                user_id=user_id,
                name=name.strip(),
                email=email.strip().lower(),
                password=password,
                role=role,
            )
            return True, ""

        except Exception as e:
            return False, f"Failed to create account: {str(e)}"

    def create_learner_account(
        self, name: str, email: str, password: str
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Create a new Learner account with auto-generated learner ID.

        This creates both the user account and the learner profile.

        Args:
            name: Learner name
            email: Learner email
            password: Account password

        Returns:
            (success, message, learner_id)
        """
        # Validate inputs
        is_valid, msg = validate_name(name)
        if not is_valid:
            return False, msg, None

        is_valid, msg = validate_email(email)
        if not is_valid:
            return False, msg, None

        is_valid, msg = validate_password(password)
        if not is_valid:
            return False, msg, None

        # Check email uniqueness (across both learners and users)
        if self.learner_repo.check_duplicate_email(email):
            return False, f"Email '{email}' is already in use", None

        if self.user_repo.check_duplicate_email(email):
            return False, f"Email '{email}' is already in use", None

        try:
            # Generate learner ID and create learner profile
            learner_id = self.learner_repo.create_with_auto_id(
                name=name.strip(),
                email=email.strip().lower(),
                date_registered=datetime.now().isoformat(),
            )

            # Create user account with same ID as learner
            self.user_repo.create_with_id(
                user_id=learner_id,
                name=name.strip(),
                email=email.strip().lower(),
                password=password,
                role="Learner",
            )

            return True, "", learner_id

        except Exception as e:
            return False, f"Failed to create learner account: {str(e)}", None

    def update_account(
        self, user_id: str, name: str, email: str, password: str, role: str
    ) -> Tuple[bool, str]:
        """
        Update user account details.

        Args:
            user_id: User ID
            name: New name
            email: New email
            password: New password
            role: New role

        Returns:
            (success, message)
        """
        # Validate inputs
        is_valid, msg = validate_name(name)
        if not is_valid:
            return False, msg

        is_valid, msg = validate_email(email)
        if not is_valid:
            return False, msg

        is_valid, msg = validate_password(password)
        if not is_valid:
            return False, msg

        # Check user exists
        existing = self.user_repo.read(user_id)
        if not existing:
            return False, f"User '{user_id}' not found"

        # Check email uniqueness (excluding self)
        if self.user_repo.check_duplicate_email(email, exclude_user_id=user_id):
            return False, f"Email '{email}' is already in use by another user"

        try:
            self.user_repo.update_account(
                user_id=user_id,
                name=name.strip(),
                email=email.strip().lower(),
                password=password,
                role=role,
            )
            return True, ""

        except Exception as e:
            return False, f"Failed to update account: {str(e)}"

    def delete_account(self, user_id: str) -> Tuple[bool, str]:
        """
        Delete a user account and cascade-delete related records.

        If the user is a Learner, also deletes the learner profile and enrollments.

        Args:
            user_id: User ID to delete

        Returns:
            (success, message)
        """
        # Check user exists
        existing = self.user_repo.read(user_id)
        if not existing:
            return False, f"User '{user_id}' not found"

        # Prevent deletion of fixed Administrator account
        if existing["user_id"] == "admin" and existing["role"] == "Administrator":
            return False, "Cannot delete the fixed Administrator account"

        try:
            self.user_repo.delete_cascade(user_id)
            return True, ""

        except Exception as e:
            return False, f"Failed to delete account: {str(e)}"

    def list_all_accounts(self) -> List[dict]:
        """Get all user accounts (excluding fixed Administrator)."""
        accounts = self.user_repo.list_all()
        # Could filter out fixed admin if desired
        return accounts


# --------------------------------------------------------------------------- #
# Course Admin Service
# --------------------------------------------------------------------------- #


class CourseAdminService:
    """Admin service for course CRUD operations."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.repo = CourseRepository(self.db)

    def create_course(
        self,
        code: str,
        name: str,
        description: str = "",
        difficulty: str = "Beginner",
        duration_hours: float = 0.0,
        instructor: str = "",
        status: str = "Draft",
    ) -> Tuple[bool, str]:
        """
        Create a new course with validation.

        Args:
            code: Course code
            name: Course name
            description: Course description
            difficulty: Difficulty level
            duration_hours: Duration in hours
            instructor: Instructor name
            status: Course status

        Returns:
            (success, message)
        """
        # Validate code
        if not code or not code.strip():
            return False, "Course code cannot be empty"

        # Validate name
        if not name or not name.strip():
            return False, "Course name cannot be empty"

        # Validate duration
        try:
            duration_hours = float(duration_hours)
            if duration_hours < 0:
                return False, "Duration cannot be negative"
        except (TypeError, ValueError):
            return False, "Duration must be a number"

        # Check for duplicate code
        if self.repo.check_duplicate_code(code):
            return False, f"Course code '{code.upper()}' already exists"

        try:
            course = Course(
                code=code.strip(),
                name=name.strip(),
                description=description or "",
                difficulty=DifficultyLevel(difficulty),
                duration_hours=duration_hours,
                instructor=instructor or "",
                status=CourseStatus(status),
            )
            self.repo.create(course)
            return True, ""

        except ValueError as e:
            return False, f"Invalid input: {str(e)}"
        except Exception as e:
            return False, f"Failed to create course: {str(e)}"

    def update_course(
        self,
        code: str,
        name: str,
        description: str = "",
        difficulty: str = "Beginner",
        duration_hours: float = 0.0,
        instructor: str = "",
        status: str = "Draft",
    ) -> Tuple[bool, str]:
        """
        Update course details.

        Args:
            code: Course code (immutable)
            name: New name
            description: New description
            difficulty: New difficulty level
            duration_hours: New duration
            instructor: New instructor
            status: New status

        Returns:
            (success, message)
        """
        # Validate code exists
        if not self.repo.read(code):
            return False, f"Course '{code.upper()}' not found"

        # Validate name
        if not name or not name.strip():
            return False, "Course name cannot be empty"

        # Validate duration
        try:
            duration_hours = float(duration_hours)
            if duration_hours < 0:
                return False, "Duration cannot be negative"
        except (TypeError, ValueError):
            return False, "Duration must be a number"

        try:
            self.repo.update_course(
                code=code,
                name=name.strip(),
                description=description or "",
                difficulty=difficulty,
                duration_hours=duration_hours,
                instructor=instructor or "",
                status=status,
            )
            return True, ""

        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Failed to update course: {str(e)}"

    def delete_course(self, code: str) -> Tuple[bool, str]:
        """
        Delete a course and cascade-delete related records.

        Args:
            code: Course code to delete

        Returns:
            (success, message)
        """
        # Check course exists
        if not self.repo.read(code):
            return False, f"Course '{code.upper()}' not found"

        try:
            self.repo.delete_cascade(code)
            return True, ""

        except Exception as e:
            return False, f"Failed to delete course: {str(e)}"

    def list_all_courses(self) -> List[Course]:
        """Get all courses."""
        return self.repo.list_all()
