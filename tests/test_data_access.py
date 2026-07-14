import os
import pytest
from data.database import DatabaseManager
from data.repository import CourseRepository, LearnerRepository, EnrollmentRepository
from core.models import Course, Enrollment


@pytest.fixture
def db(tmp_path):
    DatabaseManager.reset_instance()
    path = str(tmp_path / "test.db")
    manager = DatabaseManager(path)
    yield manager
    DatabaseManager.reset_instance()


def test_course_crud(db):
    repo = CourseRepository(db)
    course = Course("CSE101", "Intro to Programming", duration_hours=40)
    repo.create(course)

    fetched = repo.read("cse101")
    assert fetched is not None
    assert fetched.name == "Intro to Programming"

    fetched.name = "Intro to Python"
    repo.update(fetched)
    assert repo.read("CSE101").name == "Intro to Python"

    repo.delete("CSE101")
    assert repo.read("CSE101") is None


def test_prerequisite_links_persist(db):
    repo = CourseRepository(db)
    repo.create(Course("CSE101", "Intro"))
    repo.create(Course("CSE201", "Data Structures"))
    repo.add_prerequisite_link("CSE101", "CSE201")
    assert repo.get_direct_prerequisites("CSE201") == ["CSE101"]
    repo.remove_prerequisite_link("CSE101", "CSE201")
    assert repo.get_direct_prerequisites("CSE201") == []


def test_learner_crud(db):
    repo = LearnerRepository(db)
    repo.create(
        {"learner_id": "001", "name": "Aarav Kumar", "email": "aarav@lmpts.com"}
    )
    learner = repo.read("001")
    assert learner["name"] == "Aarav Kumar"
    assert len(repo.list_all()) == 1


def test_enrollment_crud(db):
    course_repo = CourseRepository(db)
    learner_repo = LearnerRepository(db)
    enroll_repo = EnrollmentRepository(db)

    course_repo.create(Course("CSE101", "Intro"))
    learner_repo.create({"learner_id": "001", "name": "Aarav", "email": "a@lmpts.com"})

    enrollment = Enrollment(learner_id="001", course_code="CSE101")
    enroll_repo.create(enrollment)

    fetched = enroll_repo.read(("001", "CSE101"))
    assert fetched is not None

    fetched.mark_completed(score=95.0)
    enroll_repo.update(fetched)
    updated = enroll_repo.read(("001", "CSE101"))
    assert updated.score == 95.0
