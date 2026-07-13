"""
LearnGraph - Learning Management & Prerequisite Tracking Platform
Entry point: wires DatabaseManager -> Repositories -> Services -> GUI.

Run with:  python main.py

The fixed administrator account, and demo Instructor / Learner / Analyst
accounts, are available as one-click "continue as" role buttons on the
login screen - no credentials are shown on screen.
"""

import tkinter as tk

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
from services.lmpts_service import (
    AssignmentService,
    CourseService,
    LearnerService,
    AnalyticsService,
    AuthService,
    AccountService,
    LearningPathService,
)
from gui.login import LoginWindow
from gui.main import MainApp


def build_services():
    db = DatabaseManager("lmpts.db")
    course_repo = CourseRepository(db)
    learner_repo = LearnerRepository(db)
    enrollment_repo = EnrollmentRepository(db)
    user_repo = UserRepository(db)
    assignment_repo = AssignmentRepository(db)
    assignment_grade_repo = AssignmentGradeRepository(db)

    graph = PrerequisiteGraph()
    course_service = CourseService(course_repo, graph)
    learner_service = LearnerService(learner_repo, enrollment_repo, course_service)
    assignment_service = AssignmentService(
        assignment_repo,
        course_service,
        learner_service,
        enrollment_repo,
        assignment_grade_repo,
    )
    analytics_service = AnalyticsService(
        course_service, learner_service, enrollment_repo
    )
    path_service = LearningPathService(graph)
    auth_service = AuthService(user_repo)
    account_service = AccountService(user_repo)
    # auth_service.ensure_demo_accounts()

    return {
        "course": course_service,
        "learner": learner_service,
        "assignment": assignment_service,
        "analytics": analytics_service,
        "path": path_service,
        "auth": auth_service,
        "account": account_service,
        "enrollment_repo": enrollment_repo,
    }


def seed_sample_data(services):
    """Seed a small sample catalog on first run so the UI isn't empty."""
    course_service = services["course"]
    if course_service.list_courses():
        return
    catalog = [
        ("CSE101", "Introduction to programming", "Beginner", 40),
        ("CSE201", "Data structure", "Intermediate", 60),
        ("CSE301", "Database management systems", "Intermediate", 60),
        ("CSE401", "Web Development", "Advanced", 80),
        ("CSE501", "Machine Learning", "Advanced", 80),
        ("CSE601", "Cloud Computing", "Intermediate", 70),
    ]
    for code, name, difficulty, hours in catalog:
        course_service.create_course(
            code, name, difficulty=difficulty, duration_hours=hours, status="Published"
        )
    chain = ["CSE101", "CSE201", "CSE301", "CSE401", "CSE501", "CSE601"]
    for a, b in zip(chain, chain[1:]):
        course_service.add_prerequisite(a, b)


class Application:
    def __init__(self):
        self.services = build_services()
        seed_sample_data(self.services)
        self.root = tk.Tk()
        self._show_login()

    def _show_login(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        LoginWindow(self.root, self.services["auth"], on_success=self._show_main_app)

    def _show_main_app(self, user):
        for widget in self.root.winfo_children():
            widget.destroy()
        MainApp(self.root, user, self.services, on_logout=self._show_login)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Application().run()
