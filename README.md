# LearnGraph — Learning Management & Prerequisite Tracking Platform

A capstone project implementing a full course-prerequisite management
system: course catalog (create / update / delete), a cycle-safe
prerequisite graph, enrollment validation, assignment grading,
learning-path recommendation, analytics, and a role-based desktop GUI
(Administrator / Instructor / Learner / Analyst) — all backed by SQLite.

This document explains not just *how to run* the project, but *how it is
built*: every layer, every class, the database schema behind it, and the
reasoning for the design choices, so it can be read on its own without
needing to open the source first.

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [Requirements](#2-requirements)
3. [Running the application](#3-running-the-application)
4. [Logging in and roles](#4-logging-in-and-roles)
5. [Running the tests](#5-running-the-tests)
6. [Architecture, layer by layer](#6-architecture-layer-by-layer)
7. [The domain layer (`core/`) in detail](#7-the-domain-layer-core-in-detail)
8. [The data layer (`data/`) in detail](#8-the-data-layer-data-in-detail)
9. [The service layer (`services/`) in detail](#9-the-service-layer-services-in-detail)
10. [The GUI layer (`gui/`) in detail](#10-the-gui-layer-gui-in-detail)
11. [Design patterns used, and why](#11-design-patterns-used-and-why)
12. [Error-handling strategy](#12-error-handling-strategy)
13. [Database schema](#13-database-schema)
14. [Database & migrations](#14-database--migrations)
15. [Project structure](#15-project-structure)
16. [Extensibility (swapping components)](#16-extensibility-swapping-components)
17. [Known scope limitations](#17-known-scope-limitations)

---

## 1. What this project is

LearnGraph is a small Learning Management + Prerequisite Tracking System
(LMPTS). The core idea is: courses can depend on other courses (you can't
take "Machine Learning" before "Data Structures"), and the app needs to
guarantee that dependency graph is always valid — no course can (directly
or indirectly) require itself. On top of that graph, the app layers
enrollment rules, grading, progress tracking, learning-path suggestions,
and reporting, and exposes all of it through a desktop GUI where what you
can see and do depends on who you're logged in as.

It was built as an OOP/data-structures/algorithms capstone, so the code is
deliberately organized to *demonstrate* specific concepts (encapsulation,
inheritance, polymorphism, abstraction, composition, several classic
design patterns, and a couple of non-trivial data structures/algorithms)
rather than just to be the shortest possible implementation. Sections 6–12
below walk through exactly where each of those concepts shows up.

---

## 2. Requirements

- **Python 3.10+** — the code uses `sqlite3` and `tkinter`, both part of
  the Python standard library, so there is no heavy external GUI or DB
  dependency to install for the app itself.
- On some Linux distributions Tkinter is packaged separately from Python:
  ```bash
  sudo apt-get install python3-tk
  ```
- To run the automated test suite, install the (small) dev dependency
  list:
  ```bash
  pip install -r requirements.txt
  ```
  which currently pins `pytest>=7.4` and `pytest-cov>=4.1` — nothing else.
  The application itself needs no third-party packages at all.

---

## 3. Running the application

```bash
cd learn_graph_project
python main.py
```

What happens on startup (`main.py`):

1. `build_services()` wires the object graph bottom-up: a
   `DatabaseManager` singleton opens (and if necessary creates)
   `lmpts.db` next to `main.py`; six repositories (`CourseRepository`,
   `LearnerRepository`, `EnrollmentRepository`, `UserRepository`,
   `AssignmentRepository`, `AssignmentGradeRepository`) are constructed
   around that connection; a `PrerequisiteGraph` is built in memory; and
   the service objects (`CourseService`, `LearnerService`,
   `AssignmentService`, `AnalyticsService`, `LearningPathService`,
   `AuthService`, `AccountService`) are constructed on top of the
   repositories and each other.
2. `seed_sample_data()` checks whether the course catalog is empty and,
   if so, inserts six sample courses (`CSE101` → `CSE601`) and chains them
   together as prerequisites (`CSE101` unlocks `CSE201`, which unlocks
   `CSE301`, and so on) purely so the UI isn't a blank screen on first
   launch. On every subsequent run this is a no-op because the catalog is
   already populated.
3. A single `tkinter.Tk()` root window is created, and `Application`
   shows the `LoginWindow` first; a successful login swaps it out for
   `MainApp`, the sidebar + page-switching shell.

A local `lmpts.db` SQLite file is created automatically the first time you
run the app — you don't need to run any setup or migration script before
first use.

---

## 4. Logging in and roles

The login screen has one-click **"continue as"** buttons for **Admin**,
**Instructor**, **Learner**, and **Analyst** — no email or password is
ever displayed on screen, including for the fixed administrator account
(its credentials live only inside `AuthService` in
`services/lmpts_service.py`, and are used internally the moment the Admin
button is pressed; they never reach the GUI layer as visible text).

The role you log in with determines what you can see, and this is decided
by *polymorphism*, not by conditional branching in the GUI — see
[Section 11](#11-design-patterns-used-and-why) for how that works
mechanically. The current mapping:

| Role | Pages you get |
|---|---|
| **Administrator** | Dashboard, Learners (full CRUD), Courses (add / edit / delete), Enrollments, Instructors, Reports, Analytics, Settings |
| **Instructor** | Dashboard, Enrollments, Reports, Instructor Portal (assignment grading) |
| **Analyst** | Analytics, Reports |
| **Learner** | Learner Portal: a "Continue Learning" panel that drops you straight back into your in-progress course, a list of courses you're eligible to enroll in, and a tracker of your own progress and grades |

Two things worth calling out about how this table is actually implemented:

- Every concrete `User` subclass (`Administrator`, `Instructor`,
  `Analyst`, `Learner`) overrides `dashboard_permissions()` and returns
  the *set* of page keys it's allowed to see. `gui/main.py` builds the
  sidebar by intersecting `NAV_ITEMS` with `user.dashboard_permissions()`
  — there is no `if role == "Administrator": show(...)` chain anywhere.
- A small extra set, `ADMIN_ONLY_EXTRA_NAV_KEYS = {"instructors"}`, is
  layered on top in the GUI for pages that are admin-only but don't
  conceptually belong in the domain model's permission set — this keeps
  `core/models.py` free of GUI-specific concerns while still letting the
  Administrator see the Instructors page.

---

## 5. Running the tests

```bash
pip install -r requirements.txt
pytest
```

`pytest.ini` configures the run with
`--cov=core --cov=data --cov=services --cov-report=term-missing`, so every
test run prints a coverage table showing exactly which lines in those
three layers aren't exercised. The GUI layer is intentionally excluded
from coverage — Tkinter UI code is not meaningfully unit-testable without
a display, so it's covered by manual testing instead.

The suite is organized by test pyramid layer:

| Layer | File | What it exercises |
|---|---|---|
| Unit (≈60%) | `tests/test_models.py` | `Course` validation and mutators, the `User` subclass hierarchy, enum values — single class in isolation, no database, no I/O |
| Unit (≈60%) | `tests/test_algorithms.py` | `PrerequisiteGraph` (add/remove edges, cycle rejection, `level()` memoisation, transitive `all_prerequisites()`), and both `PathFinder` strategies |
| Integration (≈30%) | `tests/test_data_access.py` | Every repository's CRUD methods run against a real (temporary, on-disk) SQLite database — not mocks — so schema mistakes and SQL bugs are actually caught |
| Integration (≈30%) | `tests/test_services.py` | End-to-end workflows: create course → enroll learner → submit/grade assignment → mark complete → confirm the next course in the chain unlocks; also covers `ProgressObserver` notifications and `AuthService` login/failure paths |
| Edge cases (≈10%) | spread across the above | Empty prerequisite sets, a course being its own prerequisite (rejected immediately), a 3-node indirect cycle (`A→B→C→A`, rejected on the third edge), duplicate enrollment, wrong password / unknown email at login |

---

## 6. Architecture, layer by layer

Four layers, each depending only on the layer strictly below it:

```
GUI (Tkinter)  →  Services (business rules)  →  Repositories (SQL)  →  SQLite
                         ↓
                  core/ (domain models + algorithms, depends on nothing)
```

The dependency direction is the whole point: `core/` imports nothing from
`data/` or `gui/`, which is what makes it possible to unit-test the
domain models and the graph algorithms completely in isolation — no
database connection, no Tkinter window, no mocking required. Each layer
above it only knows about the layer immediately below through a narrow
interface (an abstract base class where one exists), which is what makes
the three swap-out scenarios in
[Section 16](#16-extensibility-swapping-components) actually work in
practice rather than just being a diagram.

---

## 7. The domain layer (`core/`) in detail

### `core/models.py`

- **Enums** — `DifficultyLevel` (Beginner/Intermediate/Advanced),
  `CourseStatus` (Draft/Published/Archived), `EnrollmentStatus`
  (In Progress/Completed), `UserRole` (Administrator/Instructor/
  Learner/Analyst). Using enums instead of raw strings means a typo like
  `"publised"` fails immediately with a `ValueError` instead of silently
  creating a course nobody can find by status.
- **`Course`** — the central entity. Validates everything at construction
  time (non-empty code/name, non-negative duration, at least one level) so
  an invalid `Course` object can never exist anywhere in the program —
  this is the "fail fast" philosophy mentioned in
  [Section 12](#12-error-handling-strategy). `code` has no setter (it's
  the primary key and immutable once created); `name`, `description`,
  `difficulty`, `duration_hours`, `instructor`, `status`, and
  `total_levels` are all properties with validating setters.
  `_prerequisites` is a private `set[str]`, exposed only via a
  **copy-returning** `prerequisites` property plus
  `add_prerequisite()` / `remove_prerequisite()` / `has_prerequisite()` —
  callers can never reach in and mutate the set directly, and membership
  checks are O(1) instead of scanning a list.
- **`Enrollment`** (a `@dataclass`) — tracks a learner's relationship to
  one course: status, score, enrollment/completion timestamps, which
  level they're currently on, their latest graded score, and how many
  attempts they've made. `mark_completed()` flips status to `COMPLETED`
  and stamps the completion date in one call so callers can't forget one
  of the two fields.
- **`Assignment`** and **`AssignmentGrade`** (also dataclasses) — an
  assignment belongs to a specific level of a specific course; a grade
  belongs to one learner's one attempt at one assignment.
  `__post_init__` validation on both (non-empty title, level ≥ 1, score
  between 0 and 100, attempt number ≥ 1) means, again, invalid objects
  simply cannot be constructed.
- **`User` (ABC) → `Administrator` / `Instructor` / `Analyst` /
  `Learner`** — the inheritance hierarchy. The base class owns the
  shared fields (`user_id`, `name`, `email`, and a password check
  method) and declares two `@abstractmethod`s, `role` and
  `dashboard_permissions()`, that every subclass must implement. This is
  both **inheritance** (shared state/behaviour lives once, in the base
  class) and **polymorphism** (each subclass answers "what's my role?"
  and "what can I see?" differently, and calling code never needs to
  know which subclass it's holding).

### `core/exceptions.py`

A flat hierarchy under a single `LMPTSError` base class:
`EntityValidationError`, `CourseNotFoundError`, `LearnerNotFoundError`,
`UserNotFoundError`, `DuplicateEntityError`, `DuplicateEnrollmentError`,
`PrerequisiteNotMetError`, `CircularDependencyError`,
`AuthenticationError`. See [Section 12](#12-error-handling-strategy) for
why they're structured this way.

### `core/algorithms.py`

- **`PrerequisiteGraph`** — a directed graph where an edge
  `prereq → dependent` means "`prereq` must be completed before
  `dependent`." It's stored as **two adjacency dictionaries of sets**
  (`_prereqs_of` and `_dependents_of`, i.e. the graph is indexed in both
  directions), which gives O(1) lookup of a course's direct prerequisites
  *or* its direct dependents, at the cost of a small amount of duplicate
  bookkeeping on every edge add/remove.
  - `add_edge(prereq, dependent)` is the safety-critical method: before
    mutating anything, it runs `_is_reachable(dependent, prereq)` — an
    iterative DFS (explicit stack, not recursion, so it can't blow the
    call stack on a deep graph) that asks "can I already get from
    `dependent` back to `prereq` by following existing edges?" If yes,
    adding this new edge would close a cycle, so it raises
    `CircularDependencyError` **before** touching either adjacency dict.
    The graph is therefore never left in a partially-updated, invalid
    state — there's no rollback needed because the mutation simply never
    starts.
  - `all_prerequisites(code)` computes the **transitive closure** of a
    course's prerequisites (every course it directly or indirectly
    depends on) using BFS with a `visited` set, so a diamond-shaped
    dependency graph doesn't get walked twice.
  - `level(code)` computes how "deep" a course sits in the prerequisite
    tree (`level = 1 + max(level of its direct prerequisites)`, or `0` if
    it has none) via **recursive traversal with dict-based
    memoisation** (`_memo`). Without memoisation this recursion is
    exponential on a graph with shared prerequisites (the same sub-path
    gets recomputed once per course that depends on it); with it, each
    course's level is computed exactly once, giving O(V+E) overall.
- **`PathFinder` (ABC)** — the Strategy-pattern interface; anything that
  implements `find_path(graph, start, target) -> List[str]` can be
  plugged into `LearningPathService`.
  - **`BFSShortestPathFinder`** — classic BFS using a
    `collections.deque` as the FIFO frontier, tracking whole paths (not
    just distances) in the queue so it can return the actual sequence of
    course codes. Guarantees the *shortest* possible number of courses
    from `start` to `target`.
  - **`DifficultyProgressivePathFinder`** — a different notion of "path":
    instead of the shortest route, it returns *every* prerequisite the
    target needs (via `all_prerequisites`), sorted by `graph.level(...)`
    ascending, so foundational/easy courses come first. This is the
    "recommended study order" rather than the "minimum number of
    courses" answer — the two strategies deliberately optimize for
    different things, which is the point of having Strategy be
    swappable rather than one "correct" algorithm.

---

## 8. The data layer (`data/`) in detail

### `data/database.py`

`DatabaseManager` is a thread-safe **Singleton** (guarded by a
`threading.Lock`) wrapping one `sqlite3.Connection`, opened with
`PRAGMA foreign_keys = ON` and `row_factory = sqlite3.Row` (so query
results can be accessed by column name, not just position). On first
construction it runs `_create_schema()`, which:

1. Executes an idempotent `CREATE TABLE IF NOT EXISTS` script for every
   table (see [Section 13](#13-database-schema) for the full schema).
2. Runs a small set of `ALTER TABLE ... ADD COLUMN` guards (checking
   `PRAGMA table_info` first) for columns that were added after the
   original schema — `total_levels` on `courses`, and `current_level` /
   `latest_score_percent` / `attempt_count` on `enrollments`. This means
   an old `lmpts.db` created before those columns existed gets
   automatically upgraded in place the next time the app opens it,
   without needing a separate migration step.

`reset_instance()` exists purely so the test suite can force a fresh
singleton pointed at a new temporary database file per test, instead of
every test sharing one process-wide connection.

### `data/repository.py`

Implements the **Repository pattern**: a `Repository` ABC defines
`create` / `read` / `update` / `delete`, and six concrete classes
implement it against specific tables — `CourseRepository`,
`AssignmentRepository`, `AssignmentGradeRepository`, `LearnerRepository`,
`EnrollmentRepository`, `UserRepository`. Every hand-written SQL
statement in the entire project lives in this one file (plus
`database.py`'s schema). `services/` never imports `sqlite3` and never
writes a `SELECT`/`INSERT`/`UPDATE` — it only calls repository methods —
which is what makes "swap SQLite for PostgreSQL" a one-file change in
principle (see [Section 16](#16-extensibility-swapping-components)).

### `data/settings.py`

A small key-value store on top of the `settings` table
(`get_setting` / `set_setting` / `delete_setting` / `get_all_settings` /
`clear_all_settings`), currently used to remember the enrollments-table
sort order and a "remembered email" between GUI sessions. It's a
dictionary-like convenience layer rather than a full repository class,
since `settings` has no domain model of its own.

---

## 9. The service layer (`services/`) in detail

This is where business rules live — the layer the GUI actually talks to.

- **`CourseFactory.create(...)`** — the **Factory pattern**: the single
  place that turns raw primitive arguments (strings, floats) into a
  validated `Course` object, converting `difficulty`/`status` strings
  into their enum values along the way. Nothing else in the codebase
  constructs a `Course` directly.
- **`CourseService`** — CRUD for courses, plus everything to do with the
  prerequisite graph: `add_prerequisite()` / `remove_prerequisite()`
  (which delegate the cycle check to `PrerequisiteGraph.add_edge()`),
  `get_direct_prerequisites()`, `get_all_prerequisites()`, and
  `get_course_level()`. On construction it calls `_rebuild_graph()`,
  which loads every course and every prerequisite link from the database
  and replays them into a fresh in-memory `PrerequisiteGraph` — the graph
  itself is not persisted as a graph, it's derived from the relational
  `prerequisites` table every time the service layer starts up.
- **`AssignmentService`** — creates assignments per course/level, records
  grades (`AssignmentGrade`), and enforces `DEFAULT_PASS_CUTOFF = 65.0`
  when deciding whether a submitted score advances a learner to the next
  level or completes the course outright.
- **`LearnerService`** — owns enrollment: `enroll()` checks (a) the
  learner isn't already enrolled in that course
  (`DuplicateEnrollmentError`) and (b) every direct prerequisite is
  already completed (`PrerequisiteNotMetError`), using set operations
  (`required.issubset(completed)`) rather than looping and checking one
  at a time. It also holds the list of `ProgressObserver`s and fires
  `on_enrollment_created` / `on_course_completed` at the right moments
  (see the Observer entry in [Section 11](#11-design-patterns-used-and-why)).
- **`AnalyticsService`** — read-only aggregate queries: enrollment counts
  per course, completion rates, and the numbers behind the
  Dashboard/Analytics/Reports pages.
- **`LearningPathService`** — thin wrapper around a `PathFinder`
  strategy; `set_strategy(finder)` swaps `BFSShortestPathFinder` for
  `DifficultyProgressivePathFinder` (or a new one you write) at runtime
  with zero changes anywhere else.

---

## 12. Error-handling strategy

Every domain-specific exception inherits from `LMPTSError`
(`core/exceptions.py`), which gives two things at once:

- The **GUI** can catch broadly — `except LMPTSError as e:
  messagebox.showerror("Error", str(e))` — and correctly handle *any*
  domain failure with one code path, without needing to know every
  specific exception type in advance.
- **Tests** can assert narrowly — `pytest.raises(CircularDependencyError)`
  — to confirm the *specific* rule that was violated, not just that
  "something went wrong."

Validation happens in two places, deliberately:

1. **At construction time**, inside `Course.__init__`, `User.__init__`,
   and the dataclasses' `__post_init__` — this is the "fail fast"
   philosophy: a `Course` with a negative duration or an `Assignment`
   with a score of 150% simply cannot exist as an object, anywhere, ever.
2. **In the service layer**, for rules that need to see more than one
   object at once and so can't be enforced by any single class's
   constructor — e.g. "are all of this course's prerequisites complete
   for this specific learner?" requires looking at both the
   `PrerequisiteGraph` and that learner's `Enrollment` records, so it
   lives in `LearnerService.enroll()`, not in `Course` or `Enrollment`.

---

## 13. Database schema

The app uses one SQLite file (`lmpts.db`) with seven tables, created by
`DatabaseManager._create_schema()`:

```sql
courses (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    difficulty TEXT NOT NULL,
    duration_hours REAL NOT NULL,
    instructor TEXT,
    status TEXT NOT NULL,
    total_levels INTEGER NOT NULL DEFAULT 1
)

prerequisites (
    prereq_code TEXT NOT NULL,
    dependent_code TEXT NOT NULL,
    PRIMARY KEY (prereq_code, dependent_code),
    FOREIGN KEY (prereq_code) REFERENCES courses(code) ON DELETE CASCADE,
    FOREIGN KEY (dependent_code) REFERENCES courses(code) ON DELETE CASCADE
)

learners (
    learner_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    date_registered TEXT
)

enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id TEXT NOT NULL,
    course_code TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    enrolled_date TEXT,
    completed_date TEXT,
    current_level INTEGER NOT NULL DEFAULT 1,
    latest_score_percent REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(learner_id, course_code),
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id) ON DELETE CASCADE,
    FOREIGN KEY (course_code) REFERENCES courses(code) ON DELETE CASCADE
)

assignments (
    assignment_id TEXT PRIMARY KEY,
    course_code TEXT NOT NULL,
    level_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    due_date TEXT,
    FOREIGN KEY (course_code) REFERENCES courses(code) ON DELETE CASCADE
)

assignment_grades (
    assignment_id TEXT NOT NULL,
    learner_id TEXT NOT NULL,
    score_percent REAL NOT NULL,
    graded_at TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    PRIMARY KEY (assignment_id, learner_id, attempt_number),
    FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id) ON DELETE CASCADE,
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id) ON DELETE CASCADE
)

users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL
)

settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
```

A few schema decisions worth explaining:

- `prerequisites` uses a **composite primary key**
  `(prereq_code, dependent_code)` instead of a surrogate `id` column,
  since the pair itself is naturally unique and this makes duplicate
  edges impossible at the database level, not just in application code.
- `enrollments` has `UNIQUE(learner_id, course_code)` — the database
  itself enforces "a learner can't enroll in the same course twice,"
  which is a second line of defense behind `LearnerService`'s own
  `DuplicateEnrollmentError` check.
- Every foreign key uses `ON DELETE CASCADE`, so deleting a course or a
  learner cleans up its prerequisites/enrollments/grades automatically
  instead of leaving orphaned rows.
- `total_levels`, `current_level`, `latest_score_percent`, and
  `attempt_count` were added to the schema after the original design
  (to support the level-by-level grading feature) and are added via
  `ALTER TABLE ... ADD COLUMN` guards rather than being baked into the
  original `CREATE TABLE`, which is why `_create_schema()` runs those
  extra checks every time the app starts (see
  [Section 8](#8-the-data-layer-data-in-detail)).

---

## 14. Database & migrations

The `migrations/` folder holds one-time, idempotent maintenance scripts
for `lmpts.db`, separate from the automatic schema upgrades described
above. Currently there's one: a learner-ID renumbering migration.

```bash
# Preview changes without touching the database
python migrations/renumber_learner_ids.py lmpts.db --dry-run

# Apply the migration (creates a timestamped backup first)
python migrations/renumber_learner_ids.py lmpts.db
```

What it does:

1. Backs up `lmpts.db` to a timestamped copy before touching anything.
2. Auto-discovers every table with a `learner_id`-shaped column
   (currently `learners` and `enrollments`).
3. Orders learners by `date_registered` (falling back to row insertion
   order if that column is empty).
4. Rewrites every learner ID to a clean `L001, L002, L003, ...`
   sequence, using a three-phase transaction (child tables → temporary
   IDs, parent table → final IDs, child tables → final IDs) specifically
   so that PRIMARY KEY and UNIQUE constraints are never violated at any
   intermediate step.
5. Verifies the result and writes an old→new ID mapping log for audit
   purposes.

It's safe to re-run: if the IDs are already sequential, the script
detects that and exits immediately as a no-op. Full details — including
the exact constraint-handling strategy and troubleshooting steps — are in
`migrations/README.md`.

> **Note:** the migration's own README documents one specific historical
> run (22 learners) against a particular backup snapshot. If you run the
> migration again against the current `lmpts.db`, check
> `migrations_logs/` for the *latest* log and mapping file rather than
> assuming the numbers written in `migrations/README.md` still describe
> whatever is in the live database today.

---

## 15. Project structure

```
learn_graph_project/
├── core/                    # Domain layer — depends on nothing else in the app
│   ├── models.py                # Course, Enrollment, Assignment/Grade, User hierarchy, enums
│   ├── exceptions.py            # LMPTSError hierarchy
│   └── algorithms.py            # PrerequisiteGraph, cycle detection, BFS/difficulty path finders
├── data/                    # Data access layer (Repository pattern over SQLite)
│   ├── database.py              # Singleton connection manager + schema (+ auto column upgrades)
│   ├── repository.py            # Course/Assignment/Learner/Enrollment/User repositories
│   └── settings.py              # Key-value app settings persisted in the `settings` table
├── services/                # Business logic / orchestration
│   ├── lmpts_service.py         # CourseFactory, CourseService, AssignmentService, LearnerService,
│   │                             # AnalyticsService, LearningPathService, AuthService, AccountService,
│   │                             # ProgressObserver / ConsoleNotifier
│   └── admin_service.py         # LearnerAdminService, AccountAdminService, CourseAdminService
├── gui/                     # Presentation layer (Tkinter)
│   ├── theme.py                 # Shared colors/fonts
│   ├── login.py                 # Login screen, role-based routing
│   ├── main.py                  # Sidebar + pages (Dashboard, Courses, Analytics, ...), GUIRefreshObserver
│   └── admin_learners.py        # Admin Learners page (full CRUD)
├── migrations/              # One-time, idempotent database migrations
│   ├── renumber_learner_ids.py  # Renumbers learner IDs to sequential L001, L002, ...
│   └── README.md                # Migration usage, safety strategy, and status
├── migrations_logs/         # Auto-generated migration run logs & ID mapping audit trail
├── scripts/                 # One-off developer/maintenance scripts (not part of the shipped app)
├── tests/                   # pytest suite: unit (models, algorithms) + integration (data, services)
├── main.py                  # Application entry point — wires DB → repositories → services → GUI
├── requirements.txt         # pytest, pytest-cov (dev/test only — the app itself needs nothing extra)
├── pytest.ini                # Test discovery + coverage configuration
├── DESIGN.md                 # Architecture write-up (this README's Sections 6-12 summarize it)
└── README.md
```

---

## 16. Extensibility (swapping components)

- **New pathfinding strategy** — implement `PathFinder` (in
  `core/algorithms.py`) and pass an instance to
  `LearningPathService.set_strategy(...)`; no existing code needs to
  change, because everything upstream only ever calls the abstract
  `find_path(...)` method.
- **New database engine** — only `data/database.py` (connection/schema)
  and the SQL inside `data/repository.py` would need to change;
  `services/` and `gui/` are completely untouched, because they only ever
  call repository methods, never raw SQL.
- **New GUI framework** — `services/` has zero imports from `tkinter`
  anywhere, so a Flask API or a React front-end could call exactly the
  same `CourseService` / `LearnerService` / etc. classes directly,
  without duplicating any business logic.

---

## 17. Known scope limitations

These are deliberate simplifications made for the capstone's scope, not
oversights:

- **Password reset** (`AccountService.reset_password`) validates only the
  account's email address, with no verification token or second factor —
  the code comments this explicitly as an intentional self-service
  simplification, not something to copy into a production system.
- **Passwords are stored in plaintext** on the `User` object
  (`core/models.py` comments this too) — acceptable for a local desktop
  capstone demo, not for anything internet-facing.
- **Single shared SQLite connection** via the `DatabaseManager` singleton
  — appropriate for a single-user desktop app, not designed for
  concurrent multi-process writers.
- **The fixed Administrator account** is a constant inside `AuthService`,
  not a row in the `users` table, so it intentionally never appears in
  `AccountService.list_accounts()`.
