import pytest
from core.models import Course, DifficultyLevel, CourseStatus, Administrator, Learner, UserRole
from core.exceptions import EntityValidationError


def test_course_validation_empty_code():
    with pytest.raises(EntityValidationError):
        Course("", "Intro to Programming")


def test_course_validation_empty_name():
    with pytest.raises(EntityValidationError):
        Course("CSE101", "")


def test_course_validation_negative_duration():
    with pytest.raises(EntityValidationError):
        Course("CSE101", "Intro", duration_hours=-5)


def test_course_code_is_read_only():
    course = Course("cse101", "Intro to Programming")
    assert course.code == "CSE101"  # normalized upper-case
    with pytest.raises(AttributeError):
        course.code = "CSE999"


def test_self_prerequisite_rejected():
    course = Course("CSE101", "Intro")
    with pytest.raises(EntityValidationError):
        course.add_prerequisite("CSE101")


def test_prerequisites_returns_copy_not_reference():
    course = Course("CSE201", "Data Structures")
    course.add_prerequisite("CSE101")
    prereqs = course.prerequisites
    prereqs.add("HACKED")
    assert "HACKED" not in course.prerequisites


def test_empty_prerequisites_set_by_default():
    course = Course("CSE101", "Intro")
    assert course.prerequisites == set()


def test_has_prerequisite_o1_lookup():
    course = Course("CSE201", "Data Structures")
    course.add_prerequisite("CSE101")
    assert course.has_prerequisite("cse101") is True
    assert course.has_prerequisite("CSE999") is False


def test_administrator_role_and_permissions():
    admin = Administrator("a1", "Admin User", "admin@lmpts.com", "pw")
    assert admin.role == UserRole.ADMINISTRATOR
    assert "settings" in admin.dashboard_permissions()


def test_learner_role_polymorphism():
    learner = Learner("l1", "Priya Singh", "priya@lmpts.com", "pw")
    assert learner.role == UserRole.LEARNER
    assert learner.dashboard_permissions() == {"learner_portal"}


def test_user_requires_valid_email():
    with pytest.raises(EntityValidationError):
        Administrator("a1", "Admin", "not-an-email", "pw")
