"""
Domain models for LMPTS.

Demonstrates:
- Enums for categorical data
- Encapsulation (private attributes + properties)
- Validation at construction time (fail fast)
- Inheritance & polymorphism (User hierarchy)
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Set

from core.exceptions import EntityValidationError


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class DifficultyLevel(Enum):
    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"


class CourseStatus(Enum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    ARCHIVED = "Archived"


class EnrollmentStatus(Enum):
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"


class UserRole(Enum):
    ADMINISTRATOR = "Administrator"
    INSTRUCTOR = "Instructor"
    LEARNER = "Learner"
    ANALYST = "Analyst"


# --------------------------------------------------------------------------- #
# Course
# --------------------------------------------------------------------------- #
class Course:
    """A single course in the catalog. Code is immutable once set."""

    def __init__(
        self,
        code: str,
        name: str,
        description: str = "",
        difficulty: DifficultyLevel = DifficultyLevel.BEGINNER,
        duration_hours: float = 0.0,
        instructor: str = "",
        status: CourseStatus = CourseStatus.DRAFT,
        total_levels: int = 1,
    ):
        if not code or not code.strip():
            raise EntityValidationError("Course code cannot be empty")
        if not name or not name.strip():
            raise EntityValidationError("Course name cannot be empty")
        if duration_hours < 0:
            raise EntityValidationError("Duration cannot be negative")
        if total_levels < 1:
            raise EntityValidationError("Course must have at least one level")

        self._code = code.strip().upper()
        self._name = name.strip()
        self._description = description or ""
        self._difficulty = difficulty
        self._duration_hours = float(duration_hours)
        self._instructor = instructor or ""
        self._status = status
        self._total_levels = int(total_levels)
        self._prerequisites: Set[str] = set()  # O(1) membership testing

    # ---- read-only ----
    @property
    def code(self) -> str:
        return self._code

    # ---- controlled read/write ----
    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        if not value or not value.strip():
            raise EntityValidationError("Course name cannot be empty")
        self._name = value.strip()

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str):
        self._description = value or ""

    @property
    def difficulty(self) -> DifficultyLevel:
        return self._difficulty

    @difficulty.setter
    def difficulty(self, value: DifficultyLevel):
        self._difficulty = value

    @property
    def duration_hours(self) -> float:
        return self._duration_hours

    @duration_hours.setter
    def duration_hours(self, value: float):
        if value < 0:
            raise EntityValidationError("Duration cannot be negative")
        self._duration_hours = float(value)

    @property
    def instructor(self) -> str:
        return self._instructor

    @instructor.setter
    def instructor(self, value: str):
        self._instructor = value or ""

    @property
    def status(self) -> CourseStatus:
        return self._status

    @status.setter
    def status(self, value: CourseStatus):
        self._status = value

    @property
    def total_levels(self) -> int:
        return self._total_levels

    @total_levels.setter
    def total_levels(self, value: int):
        if value < 1:
            raise EntityValidationError("Course must have at least one level")
        self._total_levels = int(value)

    @property
    def prerequisites(self) -> Set[str]:
        """Return a copy to prevent external mutation of internal state."""
        return self._prerequisites.copy()

    def add_prerequisite(self, code: str) -> None:
        code = code.strip().upper()
        if code == self._code:
            raise EntityValidationError("A course cannot be a prerequisite of itself")
        self._prerequisites.add(code)

    def remove_prerequisite(self, code: str) -> None:
        self._prerequisites.discard(code.strip().upper())

    def has_prerequisite(self, code: str) -> bool:
        return code.strip().upper() in self._prerequisites  # O(1)

    def validate(self) -> tuple[bool, str]:
        if not self._code:
            return False, "Code cannot be empty"
        if not self._name:
            return False, "Name cannot be empty"
        if self._duration_hours < 0:
            return False, "Duration cannot be negative"
        if self._total_levels < 1:
            return False, "Course must have at least one level"
        return True, ""

    def __repr__(self) -> str:
        return f"Course({self._code}, {self._name}, {self._difficulty.value})"

    def __eq__(self, other):
        return isinstance(other, Course) and self._code == other._code

    def __hash__(self):
        return hash(self._code)


# --------------------------------------------------------------------------- #
# Enrollment
# --------------------------------------------------------------------------- #
@dataclass
class Enrollment:
    learner_id: str
    course_code: str
    status: EnrollmentStatus = EnrollmentStatus.IN_PROGRESS
    score: Optional[float] = None
    enrolled_date: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_date: Optional[str] = None
    current_level: int = 1
    latest_score_percent: Optional[float] = None
    attempt_count: int = 0

    def mark_completed(self, score: Optional[float] = None) -> None:
        self.status = EnrollmentStatus.COMPLETED
        self.score = score
        self.latest_score_percent = score
        self.completed_date = datetime.now().isoformat()


@dataclass
class Assignment:
    assignment_id: str
    course_code: str
    level_number: int
    title: str
    description: str = ""
    due_date: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.course_code or not self.course_code.strip():
            raise EntityValidationError("Assignment course code cannot be empty")
        if not self.title or not self.title.strip():
            raise EntityValidationError("Assignment title cannot be empty")
        if self.level_number < 1:
            raise EntityValidationError("Assignment level must be at least 1")


@dataclass
class AssignmentGrade:
    assignment_id: Optional[str]
    learner_id: str
    score_percent: float
    graded_at: str = field(default_factory=lambda: datetime.now().isoformat())
    attempt_number: int = 1

    def __post_init__(self) -> None:
        if self.score_percent < 0 or self.score_percent > 100:
            raise EntityValidationError("Score must be between 0 and 100")
        if self.attempt_number < 1:
            raise EntityValidationError("Attempt number must be at least 1")


# --------------------------------------------------------------------------- #
# User hierarchy (Inheritance + Polymorphism + Abstraction)
# --------------------------------------------------------------------------- #
class User(ABC):
    """Abstract base class for all system actors."""

    def __init__(self, user_id: str, name: str, email: str, password: str):
        if not name or not name.strip():
            raise EntityValidationError("Name cannot be empty")
        if not email or "@" not in email:
            raise EntityValidationError("A valid email is required")
        self._user_id = user_id or str(uuid.uuid4())[:8]
        self._name = name.strip()
        self._email = email.strip().lower()
        self._password = password  # NOTE: plaintext for capstone scope only

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def email(self) -> str:
        return self._email

    def check_password(self, password: str) -> bool:
        return self._password == password

    @property
    @abstractmethod
    def role(self) -> UserRole:
        """Each concrete user type reports its own role (polymorphism)."""
        raise NotImplementedError

    @abstractmethod
    def dashboard_permissions(self) -> Set[str]:
        """Each concrete user type exposes which dashboard sections it may see."""
        raise NotImplementedError

    def __repr__(self):
        return f"{self.__class__.__name__}({self._name}, {self._email})"


class Administrator(User):
    @property
    def role(self) -> UserRole:
        return UserRole.ADMINISTRATOR

    def dashboard_permissions(self) -> Set[str]:
        return {
            "dashboard",
            "learners",
            "courses",
            "enrollments",
            "reports",
            "settings",
            "analytics",
        }


class Instructor(User):
    @property
    def role(self) -> UserRole:
        return UserRole.INSTRUCTOR

    def dashboard_permissions(self) -> Set[str]:
        return {"dashboard", "enrollments", "reports"}


class Analyst(User):
    @property
    def role(self) -> UserRole:
        return UserRole.ANALYST

    def dashboard_permissions(self) -> Set[str]:
        return {"analytics", "reports"}


class Learner(User):
    @property
    def role(self) -> UserRole:
        return UserRole.LEARNER

    def dashboard_permissions(self) -> Set[str]:
        return {"learner_portal"}
