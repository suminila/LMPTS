"""
Custom exception hierarchy for the LMPTS domain.
All domain-specific errors inherit from LMPTSError so callers can
catch broadly (`except LMPTSError`) or narrowly (`except CourseNotFoundError`).
"""


class LMPTSError(Exception):
    """Base class for all LMPTS domain exceptions."""
    pass


class EntityValidationError(LMPTSError):
    """Raised when an entity fails validation rules at creation/update time."""
    pass


class CourseNotFoundError(LMPTSError):
    """Raised when a referenced course code does not exist."""
    pass


class LearnerNotFoundError(LMPTSError):
    """Raised when a referenced learner id does not exist."""
    pass


class UserNotFoundError(LMPTSError):
    """Raised when a referenced user account does not exist."""
    pass


class DuplicateEntityError(LMPTSError):
    """Raised when trying to create an entity that already exists (e.g. course code)."""
    pass


class DuplicateEnrollmentError(LMPTSError):
    """Raised when a learner tries to enroll twice in the same course."""
    pass


class PrerequisiteNotMetError(LMPTSError):
    """Raised when a learner tries to enroll without completing prerequisites."""
    pass


class CircularDependencyError(LMPTSError):
    """Raised when adding a prerequisite would create a circular dependency."""
    pass


class AuthenticationError(LMPTSError):
    """Raised when login credentials are invalid."""
    pass
