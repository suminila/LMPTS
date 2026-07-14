import pytest
from data.database import DatabaseManager
from data.repository import (
    AssignmentGradeRepository,
    AssignmentRepository,
    CourseRepository,
    LearnerRepository,
    EnrollmentRepository,
    UserRepository,
)
from core.algorithms import PrerequisiteGraph
from core.exceptions import (
    PrerequisiteNotMetError,
    DuplicateEnrollmentError,
    CircularDependencyError,
    AuthenticationError,
    DuplicateEntityError,
)
from core.models import UserRole
from services.lmpts_service import (
    CourseService,
    LearnerService,
    AnalyticsService,
    AuthService,
    AssignmentService,
    ConsoleNotifier,
    FIXED_ADMIN_EMAIL,
    FIXED_ADMIN_PASSWORD,
)


@pytest.fixture
def services(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(str(tmp_path / "svc_test.db"))
    course_service = CourseService(CourseRepository(db), PrerequisiteGraph())
    learner_service = LearnerService(
        LearnerRepository(db), EnrollmentRepository(db), course_service
    )
    analytics = AnalyticsService(
        course_service, learner_service, EnrollmentRepository(db)
    )
    auth = AuthService(UserRepository(db))
    assignment_service = AssignmentService(
        AssignmentRepository(db),
        course_service,
        learner_service,
        EnrollmentRepository(db),
        AssignmentGradeRepository(db),
    )
    yield {
        "course": course_service,
        "learner": learner_service,
        "analytics": analytics,
        "auth": auth,
        "assignment": assignment_service,
    }
    DatabaseManager.reset_instance()


def test_enrollment_blocked_without_prerequisite(services):
    services["course"].create_course("CSE101", "Intro", duration_hours=40)
    services["course"].create_course("CSE201", "Data Structures", duration_hours=60)
    services["course"].add_prerequisite("CSE101", "CSE201")
    services["learner"].register_learner("001", "Aarav Kumar", "aarav@lmpts.com")

    with pytest.raises(PrerequisiteNotMetError):
        services["learner"].enroll("001", "CSE201")


def test_full_enrollment_workflow(services):
    course = services["course"]
    learner = services["learner"]
    course.create_course("CSE101", "Intro", duration_hours=40)
    course.create_course("CSE201", "Data Structures", duration_hours=60)
    course.add_prerequisite("CSE101", "CSE201")
    learner.register_learner("001", "Aarav Kumar", "aarav@lmpts.com")

    learner.enroll("001", "CSE101")
    learner.mark_completed("001", "CSE101", score=90)

    available = [c.code for c in learner.available_courses("001")]
    assert "CSE201" in available

    learner.enroll("001", "CSE201")
    progress = learner.get_progress("001")
    assert progress["total_courses"] == 2
    assert progress["completed"] == 1


def test_duplicate_enrollment_rejected(services):
    services["course"].create_course("CSE101", "Intro", duration_hours=40)
    services["learner"].register_learner("001", "Aarav", "a@lmpts.com")
    services["learner"].enroll("001", "CSE101")
    with pytest.raises(DuplicateEnrollmentError):
        services["learner"].enroll("001", "CSE101")


def test_circular_dependency_prevented_at_service_level(services):
    course = services["course"]
    course.create_course("A", "Course A")
    course.create_course("B", "Course B")
    course.add_prerequisite("A", "B")
    with pytest.raises(CircularDependencyError):
        course.add_prerequisite("B", "A")


def test_observer_notified_on_enrollment(services):
    events = []

    class RecordingObserver(ConsoleNotifier):
        def on_enrollment_created(self, learner_id, course_code):
            events.append((learner_id, course_code))

    services["learner"].register_observer(RecordingObserver())
    services["course"].create_course("CSE101", "Intro")
    services["learner"].register_learner("001", "Aarav", "a@lmpts.com")
    services["learner"].enroll("001", "CSE101")
    assert events == [("001", "CSE101")]


def test_analytics_system_metrics(services):
    services["course"].create_course("CSE101", "Intro")
    services["learner"].register_learner("001", "Aarav", "a@lmpts.com")
    services["learner"].enroll("001", "CSE101")
    metrics = services["analytics"].system_metrics()
    assert metrics["total_courses"] == 1
    assert metrics["total_learners"] == 1
    assert metrics["total_enrollments"] == 1


def test_level_based_manual_grading_progression(services):
    course = services["course"]
    learner = services["learner"]
    assignment_service = services["assignment"]

    course.create_course("C", "Course C", duration_hours=10)
    course.update_course("C", total_levels=3)
    learner.register_learner("L001", "Alex", "alex@example.com")
    learner.enroll("L001", "C")

    assignment_service.create_assignment("C", 1, "Intro Level", "Level 1")
    assignment_service.create_assignment("C", 2, "Intermediate Level", "Level 2")
    assignment_service.create_assignment("C", 3, "Advanced Level", "Level 3")

    progress = assignment_service.submit_grade("L001", "C", 65)
    assert progress["current_level"] == 2
    assert progress["status"] == "In Progress"

    retest = assignment_service.submit_grade("L001", "C", 60)
    assert retest["current_level"] == 2
    assert len(retest["grade_history"]) == 2

    final_pass = assignment_service.submit_grade("L001", "C", 85)
    assert final_pass["current_level"] == 3
    assert final_pass["status"] == "In Progress"

    completed = assignment_service.submit_grade("L001", "C", 90)
    assert completed["current_level"] == 3
    assert completed["status"] == "Completed"


def test_learner_registration_and_login_share_sequential_profile_id(services):
    first = services["auth"].register(
        "Ava", "ava@example.com", "pw123", UserRole.LEARNER
    )
    assert first["user_id"] == "L001"

    second = services["auth"].register(
        "Ben", "ben@example.com", "pw456", UserRole.LEARNER
    )
    assert second["user_id"] == "L002"

    with pytest.raises(DuplicateEntityError):
        services["auth"].register(
            "Ava Again", "ava@example.com", "pw999", UserRole.LEARNER
        )

    signed_in = services["auth"].login("ava@example.com", "pw123")
    assert signed_in.user_id == "L001"
    learner_profile = services["learner"].get_learner("L001")
    assert learner_profile["email"] == "ava@example.com"


def test_fixed_admin_login(services):
    admin = services["auth"].login(FIXED_ADMIN_EMAIL, FIXED_ADMIN_PASSWORD)
    assert admin.role == UserRole.ADMINISTRATOR


def test_invalid_login_rejected(services):
    with pytest.raises(AuthenticationError):
        services["auth"].login("nobody@lmpts.com", "wrong")


def test_role_based_registration_and_login(services):
    services["auth"].register("Ravi", "ravi@lmpts.com", "pw123", UserRole.INSTRUCTOR)
    user = services["auth"].login("ravi@lmpts.com", "pw123")
    assert user.role == UserRole.INSTRUCTOR
    with pytest.raises(DuplicateEntityError):
        services["auth"].register(
            "Ravi 2", "ravi@lmpts.com", "pw999", UserRole.INSTRUCTOR
        )
