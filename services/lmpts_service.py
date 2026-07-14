"""
Service layer: orchestrates repositories + algorithms and enforces business
rules. GUI code should only ever call into these services, never touch
repositories or the graph directly.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from core.algorithms import PrerequisiteGraph, PathFinder, BFSShortestPathFinder
from core.exceptions import (
    CourseNotFoundError,
    LearnerNotFoundError,
    UserNotFoundError,
    DuplicateEntityError,
    DuplicateEnrollmentError,
    PrerequisiteNotMetError,
    EntityValidationError,
    AuthenticationError,
)
from core.models import (
    Assignment,
    AssignmentGrade,
    Course,
    DifficultyLevel,
    CourseStatus,
    Enrollment,
    EnrollmentStatus,
    UserRole,
    Administrator,
    Instructor,
    Analyst,
    Learner,
)
from data.database import DatabaseManager
from data.repository import (
    AssignmentGradeRepository,
    AssignmentRepository,
    CourseRepository,
    LearnerRepository,
    EnrollmentRepository,
    UserRepository,
)
from core.id_generator import generate_next_learner_id, is_valid_learner_id_format


# --------------------------------------------------------------------------- #
# Factory pattern
# --------------------------------------------------------------------------- #
class CourseFactory:
    """Centralizes course creation with validation, so callers can't bypass rules."""

    @staticmethod
    def create(
        code: str,
        name: str,
        description: str = "",
        difficulty: str = "Beginner",
        duration_hours: float = 0.0,
        instructor: str = "",
        status: str = "Draft",
        total_levels: int = 1,
    ) -> Course:
        course = Course(
            code=code,
            name=name,
            description=description,
            difficulty=DifficultyLevel(difficulty),
            duration_hours=duration_hours,
            instructor=instructor,
            status=CourseStatus(status),
            total_levels=total_levels,
        )
        is_valid, msg = course.validate()
        if not is_valid:
            raise EntityValidationError(msg)
        return course


# --------------------------------------------------------------------------- #
# Observer pattern
# --------------------------------------------------------------------------- #
class ProgressObserver(ABC):
    @abstractmethod
    def on_enrollment_created(self, learner_id: str, course_code: str):
        raise NotImplementedError

    @abstractmethod
    def on_course_completed(
        self, learner_id: str, course_code: str, score: Optional[float]
    ):
        raise NotImplementedError


class ConsoleNotifier(ProgressObserver):
    """Simple built-in observer: logs events to stdout."""

    def on_enrollment_created(self, learner_id: str, course_code: str):
        print(f"[event] learner {learner_id} enrolled in {course_code}")

    def on_course_completed(self, learner_id: str, course_code: str, score):
        print(f"[event] learner {learner_id} completed {course_code} (score={score})")


# --------------------------------------------------------------------------- #
# CourseService
# --------------------------------------------------------------------------- #
class CourseService:
    def __init__(self, repository: CourseRepository, graph: PrerequisiteGraph):
        self.repository = repository
        self.graph = graph
        self._rebuild_graph()

    def _rebuild_graph(self):
        for course in self.repository.list_all():
            self.graph.add_course(course.code)
        for prereq, dependent in self.repository.get_all_prerequisite_links():
            self.graph._prereqs_of.setdefault(dependent, set()).add(prereq)
            self.graph._dependents_of.setdefault(prereq, set()).add(dependent)

    def create_course(
        self,
        code,
        name,
        description="",
        difficulty="Beginner",
        duration_hours=0.0,
        instructor="",
        status="Draft",
        total_levels=1,
    ) -> Course:
        if self.repository.read(code):
            raise DuplicateEntityError(f"Course {code} already exists")
        course = CourseFactory.create(
            code,
            name,
            description,
            difficulty,
            duration_hours,
            instructor,
            status,
            total_levels,
        )
        self.repository.create(course)
        self.graph.add_course(course.code)
        return course

    def update_course(self, code: str, **fields) -> Course:
        course = self.get_course(code)
        for key, value in fields.items():
            if key == "difficulty" and value is not None:
                value = DifficultyLevel(value)
            if key == "status" and value is not None:
                value = CourseStatus(value)
            if value is not None and hasattr(course, key):
                setattr(course, key, value)
        self.repository.update(course)
        return course

    def delete_course(self, code: str) -> None:
        self.get_course(code)  # raises if missing
        self.repository.delete(code)
        self.graph.remove_course(code.upper())

    def get_course(self, code: str) -> Course:
        course = self.repository.read(code)
        if not course:
            raise CourseNotFoundError(f"Course {code} not found")
        return course

    def list_courses(self) -> List[Course]:
        return self.repository.list_all()

    def list_courses_by_instructor(self, instructor_name: str) -> List[Course]:
        target = (instructor_name or "").strip().casefold()
        return [
            course
            for course in self.repository.list_all()
            if (getattr(course, "instructor", "") or "").strip().casefold() == target
        ]

    def add_prerequisite(self, prereq_code: str, dependent_code: str) -> None:
        prereq = self.get_course(prereq_code)
        dependent = self.get_course(dependent_code)
        self.graph.add_edge(
            prereq.code, dependent.code
        )  # raises CircularDependencyError
        self.repository.add_prerequisite_link(prereq.code, dependent.code)

    def remove_prerequisite(self, prereq_code: str, dependent_code: str) -> None:
        self.graph.remove_edge(prereq_code.upper(), dependent_code.upper())
        self.repository.remove_prerequisite_link(prereq_code, dependent_code)

    def get_direct_prerequisites(self, code: str) -> set:
        return self.graph.direct_prerequisites(code.upper())

    def get_all_prerequisites(self, code: str) -> set:
        return self.graph.all_prerequisites(code.upper())

    def get_course_level(self, code: str) -> int:
        return self.graph.level(code.upper())


# --------------------------------------------------------------------------- #
# AssignmentService
# --------------------------------------------------------------------------- #
class AssignmentService:
    DEFAULT_PASS_CUTOFF = 65.0

    def __init__(
        self,
        assignment_repo: Optional[AssignmentRepository],
        course_service: CourseService,
        learner_service: LearnerService,
        enrollment_repo: Optional[EnrollmentRepository] = None,
        assignment_grade_repo: Optional[AssignmentGradeRepository] = None,
    ):
        self.assignment_repo = assignment_repo
        self.assignment_grade_repo = assignment_grade_repo
        self.enrollment_repo = enrollment_repo
        self.course_service = course_service
        self.learner_service = learner_service

    def _pass_cutoff(self, course: Course) -> float:
        return self.DEFAULT_PASS_CUTOFF

    def create_assignment(
        self,
        course_code: str,
        level_number: int,
        title: str,
        description: str = "",
        due_date: Optional[str] = None,
    ) -> Assignment:
        course = self.course_service.get_course(course_code)
        if level_number < 1:
            raise EntityValidationError("Level number must be at least 1")
        if level_number > course.total_levels:
            raise EntityValidationError(
                f"Level {level_number} exceeds the course total of {course.total_levels}"
            )
        assignment = Assignment(
            assignment_id=str(uuid.uuid4())[:8],
            course_code=course.code,
            level_number=level_number,
            title=title.strip(),
            description=description or "",
            due_date=due_date,
        )
        self.assignment_repo.create(assignment)
        return assignment

    def update_assignment(self, assignment_id: str, **fields) -> Assignment:
        assignment = self.assignment_repo.read(assignment_id)
        if not assignment:
            raise CourseNotFoundError(f"Assignment {assignment_id} not found")
        for key, value in fields.items():
            if value is not None and hasattr(assignment, key):
                setattr(assignment, key, value)
        self.assignment_repo.update(assignment)
        return assignment

    def delete_assignment(self, assignment_id: str) -> None:
        self.assignment_repo.delete(assignment_id)

    def list_assignments(self, course_code: str) -> List[Assignment]:
        self.course_service.get_course(course_code)
        return self.assignment_repo.list_for_course(course_code)

    def submit_grade(
        self,
        learner_id: str,
        course_code: str,
        score_percent: float,
    ) -> dict:
        self.learner_service.get_learner(learner_id)
        course = self.course_service.get_course(course_code)
        if (
            self.assignment_repo is None
            or self.assignment_grade_repo is None
            or self.enrollment_repo is None
        ):
            raise EntityValidationError(
                "Assignment service dependencies are not configured"
            )
        if not 0 <= float(score_percent) <= 100:
            raise EntityValidationError("Score must be between 0 and 100")

        enrollment = self.enrollment_repo.read((learner_id, course.code.upper()))
        if not enrollment:
            raise LearnerNotFoundError("No such enrollment")

        current_level = enrollment.current_level
        assignment = self.assignment_repo.list_for_level(course.code, current_level)
        if assignment:
            assignment_id = assignment[0].assignment_id
        else:
            # No assignment record exists yet for this level (the instructor
            # never explicitly created one) - auto-create a placeholder so
            # the grade has a real assignment to reference. Without this,
            # the insert below violates the assignment_grades -> assignments
            # foreign key and submitting a score always fails.
            auto_assignment = Assignment(
                assignment_id=str(uuid.uuid4())[:8],
                course_code=course.code,
                level_number=current_level,
                title=f"Level {current_level} Assessment",
            )
            self.assignment_repo.create(auto_assignment)
            assignment_id = auto_assignment.assignment_id
        attempt_number = enrollment.attempt_count + 1
        grade = AssignmentGrade(
            assignment_id=assignment_id,
            learner_id=learner_id,
            score_percent=float(score_percent),
            attempt_number=attempt_number,
        )
        self.assignment_grade_repo.create(grade)

        enrollment.attempt_count = attempt_number
        enrollment.latest_score_percent = float(score_percent)
        enrollment.score = float(score_percent)
        if float(score_percent) >= self._pass_cutoff(course):
            if current_level >= course.total_levels:
                enrollment.status = EnrollmentStatus.COMPLETED
                enrollment.completed_date = datetime.now().isoformat()
            else:
                enrollment.current_level = current_level + 1
        self.enrollment_repo.update(enrollment)
        return self.get_progress(learner_id, course_code)

    def get_progress(self, learner_id: str, course_code: str) -> dict:
        enrollment = self.enrollment_repo.read((learner_id, course_code.upper()))
        if not enrollment:
            raise LearnerNotFoundError("No such enrollment")
        course = self.course_service.get_course(course_code)
        grades = self.assignment_grade_repo.list_for_learner(learner_id)
        course_assignment_ids = {
            assignment.assignment_id
            for assignment in self.assignment_repo.list_for_course(course_code)
        }
        grade_history = [
            {
                "assignment_id": g.assignment_id,
                "score_percent": g.score_percent,
                "attempt_number": g.attempt_number,
                "graded_at": g.graded_at,
            }
            for g in grades
            if g.assignment_id in course_assignment_ids
            or (
                g.assignment_id
                and g.assignment_id.startswith(f"{course_code.upper()}-LEVEL-")
            )
        ]
        if not grade_history and enrollment.latest_score_percent is not None:
            grade_history = [
                {
                    "assignment_id": None,
                    "score_percent": enrollment.latest_score_percent,
                    "attempt_number": enrollment.attempt_count,
                    "graded_at": enrollment.enrolled_date,
                }
            ]
        return {
            "course_code": course_code.upper(),
            "current_level": enrollment.current_level,
            "total_levels": course.total_levels,
            "latest_score_percent": enrollment.latest_score_percent,
            "attempt_count": enrollment.attempt_count,
            "status": enrollment.status.value,
            "grade_history": grade_history,
            "current_assignment": (
                self.assignment_repo.list_for_level(
                    course_code, enrollment.current_level
                )[0].title
                if self.assignment_repo.list_for_level(
                    course_code, enrollment.current_level
                )
                else None
            ),
            "cutoff": self._pass_cutoff(course),
        }


# --------------------------------------------------------------------------- #
# LearnerService
# --------------------------------------------------------------------------- #
class LearnerService:
    def __init__(
        self,
        learner_repo: LearnerRepository,
        enrollment_repo: EnrollmentRepository,
        course_service: CourseService,
    ):
        self.learner_repo = learner_repo
        self.enrollment_repo = enrollment_repo
        self.course_service = course_service
        self._observers: List[ProgressObserver] = []

    def register_observer(self, observer: ProgressObserver) -> None:
        self._observers.append(observer)

    def unregister_observer(self, observer: ProgressObserver) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def _resolve_learner_id(self, learner_id: str) -> str:
        if learner_id is None:
            return ""
        value = str(learner_id).strip()
        if not value:
            return ""
        if self.learner_repo.read(value):
            return value
        if value.isdigit():
            candidate = f"L{int(value):03d}"
            if self.learner_repo.read(candidate):
                return candidate
        return value

    def register_learner(self, learner_id: str, name: str, email: str) -> dict:
        if not name or not name.strip():
            raise EntityValidationError("Name is required")
        if not email or "@" not in email:
            raise EntityValidationError("A valid email is required")

        email_norm = email.strip().lower()
        existing = self.learner_repo.find_by_email(email_norm)
        if existing:
            if name.strip() != existing["name"] or email_norm != existing["email"]:
                self.learner_repo.update(
                    {
                        "learner_id": existing["learner_id"],
                        "name": name.strip(),
                        "email": email_norm,
                        "date_registered": existing.get("date_registered"),
                    }
                )
            return existing

        candidate_id = (
            str(learner_id).strip().upper()
            if learner_id and is_valid_learner_id_format(str(learner_id))
            else generate_next_learner_id()
        )
        learner = {
            "learner_id": candidate_id,
            "name": name.strip(),
            "email": email_norm,
        }
        self.learner_repo.create(learner)
        return learner

    def get_learner(self, learner_id: str) -> dict:
        resolved_id = self._resolve_learner_id(learner_id)
        learner = self.learner_repo.read(resolved_id or learner_id)
        if not learner:
            raise LearnerNotFoundError(f"Learner {learner_id} not found")
        return learner

    def list_learners(self) -> List[dict]:
        return self.learner_repo.list_all()

    def get_learner_name(self, learner_id: str) -> str:
        """Return the learner's display name, falling back to the raw ID
        if the learner can't be resolved (e.g. stale/renamed ID)."""
        try:
            return self.get_learner(learner_id).get("name", learner_id)
        except LearnerNotFoundError:
            return learner_id

    def remove_enrollment(self, learner_id: str, course_code: str) -> None:
        """Delete a learner's enrollment in a course outright (used by the
        instructor/admin 'Remove enrollment' action)."""
        resolved_id = self._resolve_learner_id(learner_id)
        canonical_id = resolved_id or learner_id
        key = (canonical_id, course_code.upper())
        if not self.enrollment_repo.read(key):
            raise LearnerNotFoundError("No such enrollment")
        self.enrollment_repo.delete(key)

    # ===== Admin CRUD: update / change ID / delete ===== #

    def update_learner(self, learner_id: str, name: str, email: str) -> dict:
        """Update a learner's name/email (admin edit). Validates inputs and
        email uniqueness before writing through the repository."""
        self.get_learner(learner_id)  # raises LearnerNotFoundError if missing
        if not name or not name.strip():
            raise EntityValidationError("Name is required")
        if not email or "@" not in email:
            raise EntityValidationError("A valid email is required")
        if self.learner_repo.check_duplicate_email(
            email, exclude_learner_id=learner_id
        ):
            raise DuplicateEntityError(f"Email '{email}' is already in use")
        try:
            self.learner_repo.update_with_validation(
                learner_id=learner_id, name=name.strip(), email=email.strip().lower()
            )
        except ValueError as e:
            raise EntityValidationError(str(e))
        return self.get_learner(learner_id)

    def change_learner_id(self, old_id: str, new_id: str) -> dict:
        """Change a learner's ID, cascading the change to enrollments, the
        matching login account, and any other tables that reference
        learner_id, all inside a single transaction (see
        LearnerRepository.change_learner_id)."""
        if not new_id or not new_id.strip():
            raise EntityValidationError("Learner ID is required")
        new_id = new_id.strip().upper()
        self.get_learner(old_id)  # raises LearnerNotFoundError if missing
        if new_id != old_id and self.learner_repo.read(new_id):
            raise DuplicateEntityError(f"Learner ID '{new_id}' already exists")
        if new_id == old_id:
            return self.get_learner(old_id)
        try:
            self.learner_repo.change_learner_id(old_id, new_id)
        except ValueError as e:
            raise EntityValidationError(str(e))
        return self.get_learner(new_id)

    def delete_learner(self, learner_id: str) -> None:
        """Delete a learner and cascade-delete their enrollment/progress
        history and login account (see LearnerRepository.delete_cascade)."""
        self.get_learner(learner_id)  # raises LearnerNotFoundError if missing
        try:
            self.learner_repo.delete_cascade(learner_id)
        except ValueError as e:
            raise EntityValidationError(str(e))

    def completed_courses(self, learner_id: str) -> set:
        resolved_id = self._resolve_learner_id(learner_id)
        enrollments = self.enrollment_repo.list_for_learner(resolved_id or learner_id)
        return {
            e.course_code for e in enrollments if e.status == EnrollmentStatus.COMPLETED
        }

    def enroll(self, learner_id: str, course_code: str) -> Enrollment:
        resolved_id = self._resolve_learner_id(learner_id)
        self.get_learner(resolved_id or learner_id)
        course = self.course_service.get_course(course_code)

        if self.enrollment_repo.read((resolved_id or learner_id, course.code)):
            raise DuplicateEnrollmentError(f"Learner already enrolled in {course.code}")

        required = self.course_service.get_all_prerequisites(course.code)
        completed = self.completed_courses(resolved_id or learner_id)
        missing = required - completed
        if missing:
            raise PrerequisiteNotMetError(
                f"Missing prerequisites for {course.code}: {', '.join(sorted(missing))}"
            )

        canonical_id = resolved_id or learner_id
        enrollment = Enrollment(learner_id=canonical_id, course_code=course.code)
        self.enrollment_repo.create(enrollment)
        observer_id = learner_id if learner_id is not None else canonical_id
        for obs in self._observers:
            obs.on_enrollment_created(observer_id, course.code)
        return enrollment

    def mark_completed(
        self, learner_id: str, course_code: str, score: Optional[float] = None
    ) -> Enrollment:
        resolved_id = self._resolve_learner_id(learner_id)
        canonical_id = resolved_id or learner_id
        enrollment = self.enrollment_repo.read((canonical_id, course_code.upper()))
        if not enrollment:
            raise LearnerNotFoundError("No such enrollment")
        enrollment.mark_completed(score)
        self.enrollment_repo.update(enrollment)
        for obs in self._observers:
            obs.on_course_completed(canonical_id, course_code, score)
        return enrollment

    def get_progress(self, learner_id: str) -> dict:
        resolved_id = self._resolve_learner_id(learner_id)
        self.get_learner(resolved_id or learner_id)
        enrollments = self.enrollment_repo.list_for_learner(resolved_id or learner_id)
        total = len(enrollments)
        completed = [e for e in enrollments if e.status == EnrollmentStatus.COMPLETED]
        rate = (len(completed) / total * 100) if total else 0.0
        return {
            "total_courses": total,
            "completed": len(completed),
            "in_progress": total - len(completed),
            "completion_rate": round(rate, 1),
            "enrollments": enrollments,
        }

    def available_courses(self, learner_id: str) -> List[Course]:
        """Courses whose prerequisites are all completed and not yet enrolled/completed."""
        resolved_id = self._resolve_learner_id(learner_id)
        self.get_learner(resolved_id or learner_id)
        completed = self.completed_courses(resolved_id or learner_id)
        enrolled_codes = {
            e.course_code
            for e in self.enrollment_repo.list_for_learner(resolved_id or learner_id)
        }
        available = []
        for course in self.course_service.list_courses():
            if course.code in enrolled_codes:
                continue
            required = self.course_service.get_all_prerequisites(course.code)
            if required.issubset(completed):
                available.append(course)
        return available


# --------------------------------------------------------------------------- #
# AnalyticsService
# --------------------------------------------------------------------------- #
class AnalyticsService:
    def __init__(
        self,
        course_service: CourseService,
        learner_service: LearnerService,
        enrollment_repo: EnrollmentRepository,
    ):
        self.course_service = course_service
        self.learner_service = learner_service
        self.enrollment_repo = enrollment_repo

    def system_metrics(self) -> dict:
        courses = self.course_service.list_courses()
        learners = self.learner_service.list_learners()
        enrollments = self.enrollment_repo.list_all()
        completed = [e for e in enrollments if e.status == EnrollmentStatus.COMPLETED]
        rate = (len(completed) / len(enrollments) * 100) if enrollments else 0.0
        return {
            "total_courses": len(courses),
            "total_learners": len(learners),
            "total_enrollments": len(enrollments),
            "overall_completion_rate": round(rate, 1),
        }

    def course_completion_stats(self) -> List[dict]:
        stats = []
        for course in self.course_service.list_courses():
            enrollments = self.enrollment_repo.list_for_course(course.code)
            completed = [
                e for e in enrollments if e.status == EnrollmentStatus.COMPLETED
            ]
            rate = (len(completed) / len(enrollments) * 100) if enrollments else 0.0
            stats.append(
                {
                    "code": course.code,
                    "name": course.name,
                    "prereqs": len(
                        self.course_service.get_direct_prerequisites(course.code)
                    ),
                    "enrollments": len(enrollments),
                    "completion_rate": round(rate, 1),
                }
            )
        return stats

    def bottleneck_courses(
        self, min_prereqs: int = 0, max_completion_rate: float = 60.0
    ) -> List[dict]:
        """Courses with relatively many prerequisites and low completion - candidates for redesign."""
        return [
            s
            for s in self.course_completion_stats()
            if s["prereqs"] >= min_prereqs
            and s["enrollments"] > 0
            and s["completion_rate"] <= max_completion_rate
        ] or [s for s in self.course_completion_stats() if s["enrollments"] > 0]


# --------------------------------------------------------------------------- #
# LearningPathService (Strategy pattern consumer)
# --------------------------------------------------------------------------- #
class LearningPathService:
    def __init__(self, graph: PrerequisiteGraph, strategy: Optional[PathFinder] = None):
        self.graph = graph
        self.strategy = strategy or BFSShortestPathFinder()

    def set_strategy(self, strategy: PathFinder) -> None:
        self.strategy = strategy

    def find_path(self, start: str, target: str) -> List[str]:
        return self.strategy.find_path(self.graph, start.upper(), target.upper())

    def path_statistics(self, path: List[str], course_service: CourseService) -> dict:
        total_hours = 0.0
        difficulties = []
        for code in path:
            course = course_service.get_course(code)
            total_hours += course.duration_hours
            difficulties.append(course.difficulty.value)
        return {
            "total_hours": total_hours,
            "difficulty_progression": difficulties,
            "steps": len(path),
        }


# --------------------------------------------------------------------------- #
# AuthService
# --------------------------------------------------------------------------- #
FIXED_ADMIN_EMAIL = "msumi0380@gmail.com"
FIXED_ADMIN_PASSWORD = "Sumi@407"


class AuthService:
    """Handles login for all four actor types. Admin credentials are fixed;
    Instructor/Learner/Analyst accounts are stored via UserRepository."""

    def __init__(
        self,
        user_repo: UserRepository,
        learner_repo: Optional[LearnerRepository] = None,
    ):
        self.user_repo = user_repo
        self.learner_repo = learner_repo or LearnerRepository(DatabaseManager())
        self._ensure_learner_profile_consistency()

    def _normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def _is_valid_learner_id(self, learner_id: str) -> bool:
        return bool(learner_id) and is_valid_learner_id_format(str(learner_id))

    def _choose_canonical_learner_id(self, learner_ids: List[str], user_id: str) -> str:
        if user_id and user_id in learner_ids:
            return user_id
        valid_ids = [value for value in learner_ids if self._is_valid_learner_id(value)]
        if valid_ids:
            return valid_ids[0]
        return learner_ids[0]

    def _merge_duplicate_learner_profiles(self, email: str, canonical_id: str) -> None:
        cursor = self.learner_repo.conn.cursor()
        rows = cursor.execute(
            "SELECT learner_id FROM learners WHERE lower(email)=? ORDER BY rowid",
            (email,),
        ).fetchall()
        duplicate_ids = [row[0] for row in rows if row[0] != canonical_id]
        if not duplicate_ids:
            return

        for duplicate_id in duplicate_ids:
            for row in cursor.execute(
                "SELECT course_code FROM enrollments WHERE learner_id=?",
                (duplicate_id,),
            ).fetchall():
                course_code = row["course_code"]
                existing = cursor.execute(
                    "SELECT 1 FROM enrollments WHERE learner_id=? AND course_code=?",
                    (canonical_id, course_code),
                ).fetchone()
                if existing:
                    cursor.execute(
                        "DELETE FROM enrollments WHERE learner_id=? AND course_code=?",
                        (duplicate_id, course_code),
                    )
                else:
                    cursor.execute(
                        "UPDATE enrollments SET learner_id=? WHERE learner_id=? AND course_code=?",
                        (canonical_id, duplicate_id, course_code),
                    )

            for row in cursor.execute(
                "SELECT assignment_id, attempt_number FROM assignment_grades WHERE learner_id=?",
                (duplicate_id,),
            ).fetchall():
                assignment_id = row["assignment_id"]
                attempt_number = row["attempt_number"]
                existing = cursor.execute(
                    "SELECT 1 FROM assignment_grades WHERE learner_id=? AND assignment_id=? AND attempt_number=?",
                    (canonical_id, assignment_id, attempt_number),
                ).fetchone()
                if existing:
                    cursor.execute(
                        "DELETE FROM assignment_grades WHERE learner_id=? AND assignment_id=? AND attempt_number=?",
                        (duplicate_id, assignment_id, attempt_number),
                    )
                else:
                    cursor.execute(
                        "UPDATE assignment_grades SET learner_id=? WHERE learner_id=? AND assignment_id=? AND attempt_number=?",
                        (canonical_id, duplicate_id, assignment_id, attempt_number),
                    )

            cursor.execute(
                "UPDATE users SET user_id=? WHERE user_id=?",
                (canonical_id, duplicate_id),
            )
            cursor.execute("DELETE FROM learners WHERE learner_id=?", (duplicate_id,))

        self.learner_repo.conn.commit()

    def _ensure_learner_profile_for_account(self, account: dict) -> None:
        if not account or account.get("role") != UserRole.LEARNER.value:
            return

        email = self._normalize_email(account.get("email"))
        user_id = str(account.get("user_id") or "")
        if not email:
            return

        learner_profiles = self.learner_repo.conn.execute(
            "SELECT learner_id, name, email, date_registered FROM learners WHERE lower(email)=? ORDER BY rowid",
            (email,),
        ).fetchall()
        if learner_profiles:
            candidate_ids = [row[0] for row in learner_profiles]
            canonical_id = self._choose_canonical_learner_id(candidate_ids, user_id)
            self._merge_duplicate_learner_profiles(email, canonical_id)
            learner_profile = self.learner_repo.read(canonical_id)
            if not learner_profile:
                learner_profile = self.learner_repo.read(candidate_ids[0])
            current_id = learner_profile.get("learner_id")
            if not self._is_valid_learner_id(user_id):
                new_id = generate_next_learner_id()
                self.user_repo.conn.execute(
                    "UPDATE users SET user_id = ? WHERE user_id = ?",
                    (new_id, user_id),
                )
                self.user_repo.conn.commit()
                user_id = new_id
            if current_id != user_id:
                self.learner_repo.change_learner_id(current_id, user_id)

            self.learner_repo.update(
                {
                    "learner_id": user_id,
                    "name": account.get("name", ""),
                    "email": email,
                    "date_registered": learner_profile.get("date_registered"),
                }
            )
            return

        if not self._is_valid_learner_id(user_id):
            new_id = generate_next_learner_id()
            self.user_repo.conn.execute(
                "UPDATE users SET user_id = ? WHERE user_id = ?",
                (new_id, user_id),
            )
            self.user_repo.conn.commit()
            user_id = new_id

        self.learner_repo.create(
            {
                "learner_id": user_id,
                "name": account.get("name", ""),
                "email": email,
            }
        )

    def _cleanup_duplicate_learner_rows(self) -> None:
        cursor = self.learner_repo.conn.cursor()
        rows = cursor.execute("SELECT learner_id, email FROM learners").fetchall()
        grouped = {}
        for row in rows:
            email = (row["email"] or "").strip().lower()
            if not email:
                continue
            grouped.setdefault(email, []).append(row["learner_id"])

        for email, learner_ids in grouped.items():
            if len(learner_ids) <= 1:
                continue
            account = self.user_repo.find_by_email(email)
            if account and self._is_valid_learner_id(account.get("user_id")):
                canonical_id = str(account["user_id"])
            else:
                canonical_id = next(
                    (
                        value
                        for value in learner_ids
                        if self._is_valid_learner_id(value)
                    ),
                    learner_ids[0],
                )
            self._merge_duplicate_learner_profiles(email, canonical_id)

    def _ensure_learner_profile_consistency(self) -> None:
        self._cleanup_duplicate_learner_rows()
        for account in self.user_repo.list_all():
            self._ensure_learner_profile_for_account(account)

    def login(self, email: str, password: str):
        email_norm = (email or "").strip().lower()
        if email_norm == FIXED_ADMIN_EMAIL and password == FIXED_ADMIN_PASSWORD:
            return Administrator(
                user_id="admin-001",
                name="Admin User",
                email=FIXED_ADMIN_EMAIL,
                password=FIXED_ADMIN_PASSWORD,
            )

        record = self.user_repo.find_by_email(email_norm)
        if not record or record["password"] != password:
            raise AuthenticationError("Invalid email or password")

        if record.get("role") == UserRole.LEARNER.value:
            self._ensure_learner_profile_for_account(record)

        role = UserRole(record["role"])
        cls = {
            UserRole.INSTRUCTOR: Instructor,
            UserRole.ANALYST: Analyst,
            UserRole.LEARNER: Learner,
        }[role]
        return cls(
            user_id=record["user_id"],
            name=record["name"],
            email=record["email"],
            password=record["password"],
        )

    def register(self, name: str, email: str, password: str, role: UserRole) -> dict:
        email_norm = self._normalize_email(email)
        if self.user_repo.find_by_email(email_norm):
            raise DuplicateEntityError("An account with this email already exists")

        if role == UserRole.LEARNER:
            user_id = generate_next_learner_id()
        else:
            user_id = str(uuid.uuid4())[:8]

        user = {
            "user_id": user_id,
            "name": name,
            "email": email_norm,
            "password": password,
            "role": role.value,
        }
        self.user_repo.create(user)
        if role == UserRole.LEARNER:
            self._ensure_learner_profile_for_account(user)
        return user

    # def ensure_demo_accounts(self):
    #     """Seed one demo account per non-admin role so the login screen is usable out of the box."""
    #     demo_accounts = [
    #         ("Ravi Instructor", "instructor@lmpts.demo", "Instructor@1", UserRole.INSTRUCTOR),
    #         ("Divya Learner", "learner@lmpts.demo", "Learner@1", UserRole.LEARNER),
    #         ("Kabir Analyst", "analyst@lmpts.demo", "Analyst@1", UserRole.ANALYST),
    #     ]
    #     for name, email, password, role in demo_accounts:
    #         if not self.user_repo.find_by_email(email):
    #             self.register(name, email, password, role)


# --------------------------------------------------------------------------- #
# AccountService (admin-only account management)
# --------------------------------------------------------------------------- #
class AccountService:
    """Admin-only service for viewing, editing, and deleting every stored
    login account (Instructor / Learner / Analyst). The fixed Administrator
    account is a constant defined in AuthService and never stored in the
    `users` table, so it never appears here."""

    VALID_ROLES = {r.value for r in UserRole if r != UserRole.ADMINISTRATOR}

    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def list_accounts(self) -> List[dict]:
        """All stored accounts (Instructor/Learner/Analyst), newest first."""
        return self.user_repo.list_all()

    def get_account(self, user_id: str) -> dict:
        account = self.user_repo.read(user_id)
        if not account:
            raise UserNotFoundError(f"Account '{user_id}' not found")
        return account

    def get_account_by_email(self, email: str) -> dict:
        account = self.user_repo.find_by_email(email.strip().lower())
        if not account:
            raise UserNotFoundError("Account not found")
        return account

    def reset_password(self, email: str, new_password: str) -> dict:
        normalized = (email or "").strip().lower()
        if normalized == FIXED_ADMIN_EMAIL:
            raise EntityValidationError(
                "Administrator account cannot be reset through this flow"
            )

        # NOTE: This password reset flow intentionally validates only the email.
        # In a production system, this is insecure because knowing an email is
        # sufficient to change the password. This is a deliberate self-service
        # simplification for the capstone scope.
        account = self.get_account_by_email(normalized)
        if not new_password:
            raise EntityValidationError("Password is required")

        self.user_repo.update_account(
            user_id=account["user_id"],
            name=account["name"],
            email=account["email"],
            password=new_password,
            role=account["role"],
        )
        return self.get_account(account["user_id"])

    def update_account(
        self, user_id: str, name: str, email: str, password: str, role: str
    ) -> dict:
        """Update name/email/password/role for a stored account."""
        self.get_account(user_id)  # raises UserNotFoundError if missing
        if not name or not name.strip():
            raise EntityValidationError("Name is required")
        if not email or "@" not in email:
            raise EntityValidationError("A valid email is required")
        if not password:
            raise EntityValidationError("Password is required")
        if role not in self.VALID_ROLES:
            raise EntityValidationError(
                f"Role must be one of: {', '.join(sorted(self.VALID_ROLES))}"
            )
        if self.user_repo.check_duplicate_email(email, exclude_user_id=user_id):
            raise DuplicateEntityError(f"Email '{email}' is already in use")
        try:
            self.user_repo.update_account(
                user_id=user_id,
                name=name.strip(),
                email=email.strip().lower(),
                password=password,
                role=role,
            )
        except ValueError as e:
            raise EntityValidationError(str(e))
        return self.get_account(user_id)

    def delete_account(self, user_id: str) -> None:
        """Delete a stored account. If it's a Learner account, this also
        cascade-deletes the learner profile and their enrollment history
        (see UserRepository.delete_cascade)."""
        self.get_account(user_id)  # raises UserNotFoundError if missing
        try:
            self.user_repo.delete_cascade(user_id)
        except ValueError as e:
            raise EntityValidationError(str(e))

    def change_account_id(self, old_id: str, new_id: str) -> dict:
        """Change a stored account's user ID (e.g. an Instructor's ID).

        For Learner accounts this also updates the linked learner profile
        and every enrollment record (see UserRepository.change_user_id)."""
        self.get_account(old_id)  # raises UserNotFoundError if missing
        new_id = (new_id or "").strip()
        if not new_id:
            raise EntityValidationError("New ID cannot be empty")
        if new_id == old_id:
            return self.get_account(old_id)
        try:
            self.user_repo.change_user_id(old_id, new_id)
        except ValueError as e:
            raise EntityValidationError(str(e))
        return self.get_account(new_id)
