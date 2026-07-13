# LearnGraph — Design Document

This document explains the architecture behind LearnGraph in depth: why
it's layered the way it is, which data structure and algorithm choices
were made and why, where each OOP principle and design pattern actually
lives in the code, how errors flow through the system, and how a typical
operation (like enrolling a learner) moves through every layer. It's
meant to be read alongside — but understandable without — the source
itself.

---

## Table of contents

1. [Architecture](#1-architecture)
2. [OOP principles, where they show up](#2-oop-principles-where-they-show-up)
3. [Data structures](#3-data-structures)
4. [Design patterns](#4-design-patterns)
5. [Cycle detection algorithm](#5-cycle-detection-algorithm)
6. [Error handling strategy](#6-error-handling-strategy)
7. [Learner ID generation and identity resolution](#7-learner-id-generation-and-identity-resolution)
8. [Worked example: what happens when a learner enrolls](#8-worked-example-what-happens-when-a-learner-enrolls)
9. [Testing strategy](#9-testing-strategy)
10. [Non-functional requirements](#10-non-functional-requirements)
11. [Design decisions and trade-offs](#11-design-decisions-and-trade-offs)

---

## 1. Architecture

Four layers, each depending only on the layer below it:

```
GUI (Tkinter)  →  Services (business rules)  →  Repositories (SQL)  →  SQLite
                         ↓
                  core/ (domain models + algorithms, depends on nothing)
```

`core/` has no imports from `data/` or `gui/`, so the domain models and
algorithms can be unit-tested (and reused) completely independently of the
database or the UI.

**Why this specific shape, and not just "MVC"?** A conventional MVC split
would put business rules either in the model or the controller/view, and
in a Tkinter app that tends to leak SQL and validation logic straight
into button-click handlers. Here, the domain (`core/`) is deliberately
pulled out from *both* the database and the UI, so it has no framework
attachments at all — a `Course` object doesn't know it's ever going to be
stored in SQLite or shown in a Tkinter table. That separation is what
lets `core/` be tested with zero setup (no temp file, no display) and
reused unchanged if the persistence or presentation technology ever
changes.

**Direction of dependency, concretely, per import statement:**

- `gui/*.py` imports from `services/` and `core/` (for enums/exceptions),
  never from `data/` directly, and never writes SQL.
- `services/lmpts_service.py` and `services/admin_service.py` import from
  `data/repository.py` and `core/`, never from `gui/`, and never import
  `sqlite3` — `AuthService`, `LearnerService`, etc. only ever call
  repository methods.
- `data/repository.py` and `data/database.py` import from `core/`
  (to construct/return domain objects like `Course` and `Enrollment`) and
  from `sqlite3`, never from `services/` or `gui/`.
- `core/models.py`, `core/exceptions.py`, `core/algorithms.py` import
  only from the standard library and from each other — nothing from
  `data/`, `services/`, or `gui/`.

That last point is what "core/ depends on nothing" means in practice: you
could delete `data/`, `services/`, and `gui/` entirely and every file in
`core/` would still import and run cleanly.

---

## 2. OOP principles, where they show up

| Principle | Where |
|---|---|
| **Encapsulation** | `Course` keeps `_prerequisites` private; only exposed via `prerequisites` (returns a copy) and `add_prerequisite()`/`has_prerequisite()`. `code` is read-only (no setter). |
| **Inheritance** | `User` (ABC) → `Administrator`, `Instructor`, `Analyst`, `Learner`. |
| **Polymorphism** | Each `User` subclass implements `role` and `dashboard_permissions()` differently; the GUI sidebar is built by iterating `user.dashboard_permissions()` — no `if role == "admin"` branching. |
| **Abstraction** | `Repository` and `PathFinder` are ABCs describing a contract; concrete SQLite repositories and BFS/difficulty-progressive finders implement them. |
| **Composition** | `CourseService` *has a* `CourseRepository` and a `PrerequisiteGraph`; `LearnerService` *has a* `CourseService` — services are composed from smaller, focused collaborators rather than inheriting from a "God" base class. |

Expanding on each with the actual mechanics:

### Encapsulation

`Course._prerequisites` is a private `set[str]` attribute (leading
underscore). The only way to read it from outside the class is through
the `prerequisites` property, which returns `self._prerequisites.copy()`
— a **defensive copy**, not the live set. This matters: if it returned
the live set, `course.prerequisites.add("CSE999")` would silently mutate
the course's real prerequisite list, bypassing every validation rule
(like "a course can't be its own prerequisite") that `add_prerequisite()`
enforces. Every other mutable field on `Course` (`name`, `description`,
`difficulty`, `duration_hours`, `instructor`, `status`, `total_levels`)
follows the same property-with-validating-setter pattern; only `code` is
read-only, because it's the primary key and changing it after creation
would silently orphan every prerequisite link and enrollment that
references the old code.

### Inheritance

`User(ABC)` holds everything every account type needs regardless of
role: `user_id`, `name`, `email` (validated for `"@"` at construction),
a password (stored, checked via `check_password()`), and a `__repr__`.
`Administrator`, `Instructor`, `Analyst`, and `Learner` each add nothing
to that shared state — the entire hierarchy exists purely so each
subclass can answer two questions differently (see Polymorphism below).
This is a deliberately *thin* inheritance hierarchy: no subclass overrides
constructor logic or adds new fields, which avoids the classic "deep,
fragile inheritance tree" problem while still getting real behavioural
differentiation per role.

### Polymorphism

`role` and `dashboard_permissions()` are declared `@abstractmethod` on
`User`, so every subclass *must* implement them (Python raises a
`TypeError` at instantiation time if one is missing — you cannot
accidentally end up with a `User` subclass that silently falls back to
some default permission set). `gui/main.py` builds the sidebar as:

```python
visible_keys = set(NAV_ITEMS) & user.dashboard_permissions()
```

— the GUI never asks "is this an Administrator?" anywhere; it just calls
the method and trusts whatever set comes back. This is the practical
payoff of polymorphism here: adding a fifth role later means writing one
new subclass with its own `dashboard_permissions()`, and the sidebar code
does not change at all.

### Abstraction

Two ABCs describe contracts without dictating implementation:

- **`Repository`** (`data/repository.py`) declares `create` / `read` /
  `update` / `delete`. `CourseRepository`, `LearnerRepository`,
  `EnrollmentRepository`, `UserRepository`, `AssignmentRepository`, and
  `AssignmentGradeRepository` each implement it against SQLite, but
  nothing above the repository layer knows or cares that SQLite is the
  backing store — it only knows the four-method contract.
- **`PathFinder`** (`core/algorithms.py`) declares `find_path(graph,
  start, target) -> List[str]`. `BFSShortestPathFinder` and
  `DifficultyProgressivePathFinder` implement it with completely
  different algorithms and different notions of what "the path" even
  means, but `LearningPathService` only ever calls the one abstract
  method.

### Composition

Services are built by *holding references to* other objects, not by
inheriting from them:

- `CourseService` **has a** `CourseRepository` (for persistence) and a
  `PrerequisiteGraph` (for in-memory graph operations) — two unrelated
  collaborators, each doing one job.
- `LearnerService` **has a** `LearnerRepository`, an
  `EnrollmentRepository`, *and* a `CourseService` (so it can ask "what
  are this course's prerequisites?" without duplicating graph logic).
- `AssignmentService` **has a** `AssignmentRepository`, a
  `CourseService`, a `LearnerService`, an `EnrollmentRepository`, *and*
  an `AssignmentGradeRepository` — five collaborators, each narrow.

The alternative — one big service class inheriting shared behaviour from
a base "God" service — would couple every unrelated piece of business
logic together and make it impossible to test, say, course-creation logic
without also dragging in enrollment or grading code. Composition keeps
each class's job small and its test surface small.

---

## 3. Data structures

- **Set** for `Course._prerequisites` → O(1) membership testing (`has_prerequisite`), and set algebra (`required.issubset(completed)`, `required - completed`) for prerequisite validation.
- **Dict of sets (adjacency list)** for `PrerequisiteGraph` → O(1) lookup of a course's direct prerequisites/dependents, O(V+E) traversal.
- **Deque (`collections.deque`)** as the FIFO queue driving BFS in `BFSShortestPathFinder` — guarantees the *shortest* course sequence.
- **Dict/hash map memoisation** in `PrerequisiteGraph.level()` — a recursive tree traversal (level = 1 + max(level of prereqs)) is normally exponential without memoisation; here it's O(V+E).

Each of these deserves the "why not something simpler":

### Why a set, not a list, for prerequisites

A `list[str]` would make `has_prerequisite()` an O(n) linear scan, and
`add_prerequisite()` would need its own duplicate check before appending
(another O(n) scan) to avoid the same prerequisite being stored twice. A
`set[str]` makes membership testing and duplicate-avoidance both O(1) for
free, and set algebra directly expresses the actual business question:
`LearnerService.enroll()` computes `missing = required - completed` in
one operation, where `required` and `completed` are both sets of course
codes — no manual loop needed to find which prerequisites aren't done
yet.

### Why two adjacency dicts, not one, for the graph

`PrerequisiteGraph` stores `_prereqs_of: Dict[str, Set[str]]` (course →
its direct prerequisites) **and** `_dependents_of: Dict[str, Set[str]]`
(course → courses that need it) — the same edges, indexed in both
directions. This costs a small amount of duplicated bookkeeping on every
`add_edge`/`remove_edge` call (both dicts must be updated together), but
it means two very different queries are both O(1) to start:
"what does this course require?" (`_prereqs_of`) and "what does completing
this course unlock?" (`_dependents_of`, used by `BFSShortestPathFinder` to
walk *forward* through the graph). Storing only one direction would force
a full O(V) scan of every course to answer the other direction's
question.

### Why BFS (with a deque), not DFS, for shortest path

`BFSShortestPathFinder` explores the graph level-by-level using a
`collections.deque` as a FIFO queue, storing whole partial paths (not
just node distances) so the final path can be returned directly without
a separate backtracking step. BFS is the right choice specifically
*because* the goal is the shortest course sequence — DFS would find *a*
path but not necessarily the shortest one, since it dives deep before
exploring alternatives. A `deque` is used instead of a plain `list`
because `list.pop(0)` is O(n) (it has to shift every remaining element),
while `deque.popleft()` is O(1) — for a FIFO-driven algorithm like BFS,
that difference matters as the queue grows.

### Why memoisation for `level()`, and what breaks without it

`level(code)` is defined recursively: `level = 1 + max(level(p) for p in
direct_prerequisites)`, or `0` if there are none. Without memoisation,
this recomputes the same sub-course's level once for *every* course that
(directly or indirectly) depends on it — in a graph shaped like a
diamond or a wide fan-in (many advanced courses all sharing the same
foundational prerequisite), that's exponential blowup. The `_memo: Dict[str,
int]` parameter, threaded through the recursive calls, ensures each
course's level is computed exactly once and then reused, bringing the
whole computation down to O(V+E) — proportional to the size of the graph,
not to the number of paths through it.

---

## 4. Design patterns

- **Repository pattern** — `data/repository.py`. Services never write SQL; swapping SQLite → PostgreSQL only touches this file and `database.py`.
- **Factory pattern** — `CourseFactory.create()` centralizes validation so a `Course` object can never exist in an invalid state anywhere in the app.
- **Strategy pattern** — `PathFinder` ABC with `BFSShortestPathFinder` and `DifficultyProgressivePathFinder`. `LearningPathService.set_strategy()` swaps algorithms at runtime; adding a third strategy requires zero changes to existing classes (Open/Closed Principle).
- **Observer pattern** — `ProgressObserver` ABC. `LearnerService` holds a list of observers and notifies them on `on_enrollment_created` / `on_course_completed`. The GUI registers `GUIRefreshObserver` so tables refresh live after an enrollment — the service layer has no idea the GUI exists.
- **Singleton pattern** — `DatabaseManager` ensures a single shared SQLite connection across all repositories.

Deeper look at each:

### Repository

Every hand-written SQL statement in the entire project lives in
`data/repository.py` (and the schema DDL in `data/database.py`) — nowhere
else. `CourseRepository`, `AssignmentRepository`,
`AssignmentGradeRepository`, `LearnerRepository`, `EnrollmentRepository`,
and `UserRepository` all implement the same four-method `Repository`
contract (`create`/`read`/`update`/`delete`), plus whatever extra
query methods their table actually needs (e.g.
`LearnerRepository.find_by_email()`,
`CourseRepository.get_all_prerequisite_links()`). Because services only
ever call these methods, migrating from SQLite to PostgreSQL in principle
means rewriting the SQL dialect inside this one file and the connection
setup in `database.py` — every service class, every GUI page, and every
test that mocks a repository stays untouched.

### Factory

`CourseFactory.create(code, name, description, difficulty, duration_hours,
instructor, status, total_levels)` is the single place in the codebase
that turns raw primitive arguments — plain strings and numbers, exactly
what comes out of a GUI form or a test fixture — into a validated
`Course` domain object, converting the `difficulty` and `status` strings
into their proper enum values along the way (`DifficultyLevel(value)`,
`CourseStatus(value)`). No other code path constructs a `Course` directly;
`CourseService.create_course()` calls the factory rather than
`Course(...)` itself. This guarantees there is exactly one gate a course
has to pass through to exist, so a rule change (say, requiring a
non-empty `instructor`) only needs to be added in one place.

### Strategy

`PathFinder` is the abstract interface; `BFSShortestPathFinder` (fewest
courses) and `DifficultyProgressivePathFinder` (foundational-first study
order) are two genuinely different algorithms answering two genuinely
different questions, both satisfying the same
`find_path(graph, start, target) -> List[str]` signature.
`LearningPathService.set_strategy(finder)` swaps which one is active at
runtime — a GUI toggle between "shortest route" and "recommended study
order" is just calling `set_strategy()` with a different instance, with
zero changes to `LearningPathService` itself, `PrerequisiteGraph`, or the
other strategy class. Adding a third strategy (e.g. one that also
accounts for course duration) means writing one new class that
implements `PathFinder` — the Open/Closed Principle in action: open for
extension (new strategies), closed for modification (nothing existing
has to change).

### Observer

`ProgressObserver` is an ABC with `on_enrollment_created(learner_id,
course_code)` and `on_course_completed(learner_id, course_code, score)`.
`LearnerService` holds a plain `List[ProgressObserver]`
(`register_observer()` / `unregister_observer()`) and loops over it at
exactly two moments: right after `enroll()` successfully creates an
`Enrollment` row, and right after `mark_completed()` updates one. The GUI
registers a `GUIRefreshObserver` (in `gui/main.py`) so that, for example,
grading an assignment causes the Enrollments table to refresh
automatically elsewhere in the app — but `LearnerService` has no import
of `tkinter` and no idea the GUI exists; it just calls whatever
`on_enrollment_created`/`on_course_completed` methods are registered.
There's also a `ConsoleNotifier` observer in `lmpts_service.py`,
demonstrating that a completely different kind of subscriber (one that
just prints to the console) can be attached the same way.

### Singleton

`DatabaseManager.__new__` is guarded by a `threading.Lock` and checks a
class-level `_instance` before constructing anything, so no matter how
many repositories ask for `DatabaseManager("lmpts.db")`, they all get
back the exact same object wrapping the exact same open
`sqlite3.Connection`. This matters because SQLite connections aren't free
to open repeatedly, and having every repository share one connection
(with `PRAGMA foreign_keys = ON` set once) avoids subtle bugs where one
connection has a pending uncommitted transaction another connection can't
see. `reset_instance()` is a test-only escape hatch that closes the
current connection and clears `_instance`, so each test can force a
fresh singleton pointed at its own temporary database file instead of
polluting a shared one.

---

## 5. Cycle detection algorithm

Before adding an edge `prereq → dependent` (meaning "prereq must be completed
before dependent"), the graph runs a DFS from `dependent` looking for a path
back to `prereq`. If one exists, adding the edge would close a cycle, so it's
rejected with `CircularDependencyError` **before** any mutation happens —
the graph is never left in an invalid state.

**Mechanically**, `add_edge(prereq, dependent)` in
`core/algorithms.py`:

1. Ensures both course codes exist in the graph (`add_course` is
   idempotent — calling it on an already-known course is a no-op).
2. Rejects `prereq == dependent` immediately (a course can't be its own
   prerequisite — this is the trivial 1-node cycle case, checked
   separately from the general case for clarity and speed).
3. Calls `_is_reachable(dependent, prereq)` — an **iterative** DFS using
   an explicit Python list as a stack (not Python's own call stack via
   recursion), which asks: starting from `dependent` and walking forward
   along existing `_dependents_of` edges (i.e. "what does `dependent`
   eventually unlock?"), can we reach `prereq`? If yes, then `prereq`
   already (directly or transitively) depends on `dependent` — so adding
   `prereq → dependent` would mean `dependent` needs `prereq`, which
   needs... eventually `dependent` again. That's the cycle.
4. Only if `_is_reachable` returns `False` does the method actually
   mutate `_prereqs_of` and `_dependents_of`.

**Worked example** — suppose the graph already has `A → B → C` (A is a
prerequisite of B, B is a prerequisite of C). Someone tries to add
`C → A` (make C a prerequisite of A):

- `_is_reachable(dependent="A", target="C")` is called — can we walk
  forward from A and reach C? Yes: `A → B → C`. So this call returns
  `True`, and `add_edge("C", "A")` raises `CircularDependencyError`
  *before* touching either adjacency dict. The graph still only contains
  `A → B → C`, untouched.

**Why iterative DFS instead of recursive DFS:** a recursive
implementation would work identically for small graphs, but on a
deep/degenerate prerequisite chain (hundreds of courses each depending on
the last) it risks hitting Python's recursion limit. The explicit-stack
version has no such ceiling — it's bounded only by available memory, the
same as the graph itself.

**Why check *before* mutating, not mutate-then-check-and-rollback:** the
alternative design — add the edge, then check for a cycle, then undo the
edge if one is found — works, but means the graph passes through a
momentarily-invalid state and requires careful, exactly-symmetric
undo logic. Checking first means the mutation step (`self._prereqs_of[dependent].add(prereq)`
and `self._dependents_of[prereq].add(dependent)`) can be trusted to
always leave the graph valid, with no rollback path needed anywhere in
the class.

---

## 6. Error handling strategy

All domain errors inherit from `LMPTSError`, so the GUI can catch broadly
(`except LMPTSError as e: messagebox.showerror(...)`) while tests can assert
on specific subclasses (`PrerequisiteNotMetError`, `CircularDependencyError`,
`DuplicateEnrollmentError`, etc.). Validation happens at construction time in
`Course.__init__` and `User.__init__` (fail fast — an invalid object can
never exist), and again in the service layer for cross-entity rules that a
single object can't know about on its own (e.g. "are all prerequisites
complete?").

**The full exception hierarchy** (`core/exceptions.py`), all inheriting
from `LMPTSError(Exception)`:

| Exception | Raised when |
|---|---|
| `EntityValidationError` | A field fails validation at construction/update time (empty name, negative duration, out-of-range score, etc.) |
| `CourseNotFoundError` | A referenced course code doesn't exist |
| `LearnerNotFoundError` | A referenced learner ID doesn't exist (also reused for "no such enrollment" in `remove_enrollment`/`mark_completed`) |
| `UserNotFoundError` | A referenced login account doesn't exist |
| `DuplicateEntityError` | Creating something that already exists (duplicate course code, duplicate email on learner update) |
| `DuplicateEnrollmentError` | A learner tries to enroll twice in the same course |
| `PrerequisiteNotMetError` | A learner tries to enroll without having completed every prerequisite |
| `CircularDependencyError` | Adding a prerequisite edge would create a cycle |
| `AuthenticationError` | Login credentials don't match |

**Two validation checkpoints, and why both are needed:**

1. **Construction-time, inside the object itself** (`Course.__init__`,
   `User.__init__`, and the `__post_init__` hooks on the `Enrollment`,
   `Assignment`, and `AssignmentGrade` dataclasses). This is "fail fast":
   an object with a negative `duration_hours` or a `score_percent` of
   150 simply cannot be constructed, full stop — there's no code path
   anywhere in the application, present or future, that could end up
   holding an invalid instance.
2. **Service-layer, for rules spanning multiple objects.** A single
   `Course` object has no way to know whether a *specific learner* has
   completed its prerequisites — that requires looking at the
   `PrerequisiteGraph` (which courses does this course need?) *and* that
   learner's `Enrollment` history (which of those has this learner
   finished?) at the same time. That cross-entity check lives in
   `LearnerService.enroll()`, not in `Course` or `Enrollment`, because
   neither of those classes has access to the other information on its
   own.

**Why one broad base class instead of unrelated exception types:**
Tkinter error handling in the GUI is centralized —
`except LMPTSError as e: messagebox.showerror("Error", str(e))` — so
*any* domain rule violation, present or added later, automatically shows
the user a readable message without the GUI needing an `except` clause
per exception type. Tests get the opposite benefit: `pytest.raises(
CircularDependencyError)` proves the *specific* rule fired, not just that
"an error happened."

---

## 7. Learner ID generation and identity resolution

This section isn't in the original design doc but is worth documenting,
since it interacts directly with error handling and the migration tooling
described elsewhere in the project.

`core/id_generator.py` provides three small, focused functions:

- **`generate_next_learner_id()`** — scans every existing `learner_id`,
  extracts the numeric suffix from any that match the `L###` pattern, and
  returns `L{max+1:03d}`. New learners are always assigned the next
  number after the current highest — IDs are never reused and never
  fill a gap left by a deleted learner, so an ID is a stable,
  once-assigned identifier for as long as it exists.
- **`extract_learner_id_number()`** — parses the numeric suffix back out
  (`"L022" → 22`), returning `None` for anything that doesn't match.
- **`is_valid_learner_id_format()`** — a cheap format check (`starts with
  "L"`, rest is digits) used to decide whether a caller-supplied ID
  should be trusted as-is or whether the system should generate a fresh
  one instead.

**Why `LearnerService._resolve_learner_id()` exists:** across the GUI,
learner IDs sometimes arrive as the full `"L007"` string and sometimes as
a bare number typed into a form (`"7"`). Rather than pushing that
ambiguity into every caller, `_resolve_learner_id()` centralizes it:
it tries the value as-is first, and if that doesn't match an existing
learner *and* the value is purely numeric, it retries as a
zero-padded `L{int:03d}` before giving up and returning the original
value unchanged (so the caller still gets a clear
`LearnerNotFoundError` rather than a silent wrong match). Every
learner-facing method (`get_learner`, `enroll`, `mark_completed`,
`completed_courses`, `available_courses`, `remove_enrollment`,
`get_progress`) routes through this resolver first, so this ambiguity is
handled in exactly one place instead of being re-implemented per method.

---

## 8. Worked example: what happens when a learner enrolls

To make the layering concrete, here's the full call path for
`LearnerService.enroll(learner_id, course_code)`, the single most
rule-heavy operation in the app:

1. **Resolve the learner ID** via `_resolve_learner_id()` (Section 7).
2. **Confirm the learner exists** — `get_learner()` raises
   `LearnerNotFoundError` if not, via a lookup through
   `LearnerRepository`.
3. **Confirm the course exists** — `CourseService.get_course()` raises
   `CourseNotFoundError` if not.
4. **Reject duplicate enrollment** — `EnrollmentRepository.read((learner_id,
   course_code))`; if a row already exists, raise
   `DuplicateEnrollmentError`. (The database's own
   `UNIQUE(learner_id, course_code)` constraint is a second line of
   defense behind this application-level check.)
5. **Compute required vs. completed prerequisites as sets** —
   `required = CourseService.get_all_prerequisites(course_code)` (the
   transitive closure, via `PrerequisiteGraph.all_prerequisites()`,
   Section 3) and `completed = LearnerService.completed_courses(learner_id)`
   (every course this learner has an enrollment marked `COMPLETED` for).
   `missing = required - completed` — pure set subtraction. If
   `missing` is non-empty, raise `PrerequisiteNotMetError`, listing
   exactly which courses are still outstanding.
6. **Construct and persist the `Enrollment`** — a new `Enrollment`
   dataclass instance (status defaults to `IN_PROGRESS`, `enrolled_date`
   defaults to now) is handed to `EnrollmentRepository.create()`, which
   is the one place that turns it into an `INSERT` statement.
7. **Notify observers** — every registered `ProgressObserver` gets
   `on_enrollment_created(learner_id, course_code)` called on it. In the
   running app, this is what causes `GUIRefreshObserver` to refresh the
   Enrollments table live, without `LearnerService` needing to know a
   GUI exists.
8. **Return the new `Enrollment`** to the caller (typically a GUI page,
   which uses it to update what's shown immediately without waiting for
   a full reload).

Every step above lives in exactly one layer: steps 1–3 and 5 read
through repositories but decide nothing about SQL; step 6 is the only
step that touches persistence directly (via the repository, never raw
SQL from the service); step 7 is pure Observer-pattern dispatch with no
knowledge of what's listening. This is the practical result of the
architecture in Section 1 — each piece of the enroll workflow sits in the
layer that actually owns that responsibility.

---

## 9. Testing strategy

- **Unit (60%)** — `test_models.py`, `test_algorithms.py`: single class/function in isolation.
- **Integration (30%)** — `test_data_access.py` (repository ↔ real SQLite in a temp file), `test_services.py` (full enroll → complete → unlock-next-course workflow).
- **Edge cases (10%)** — empty prerequisite sets, self-prerequisite rejection, indirect (3-node) cycle detection, duplicate enrollment, invalid login.

**Why integration tests use a real temp SQLite file instead of mocking
the database:** mocking `sqlite3` would let tests pass even if the actual
SQL in `repository.py` were subtly wrong (a typo'd column name, a missing
`FOREIGN KEY`, a schema/query mismatch) — the mock would happily return
whatever the test told it to. Running `test_data_access.py` against a
real (temporary, disposed-of-after-the-test) SQLite database means schema
mistakes and SQL bugs are caught the same way they'd surface in
production, at the cost of tests being slightly slower than pure mocks.

**Why the split is roughly 60/30/10 rather than "test everything
equally":** the domain layer (`core/`) has the highest density of
business rules per line (validation, cycle detection, path-finding) and
zero I/O, so it's cheap to test exhaustively — hence the largest share.
Integration tests are fewer but each one is more expensive (real file
I/O, multi-step workflows) and exist specifically to catch the failure
mode unit tests structurally can't: two correctly-tested pieces (say,
`LearnerService.enroll()` and `EnrollmentRepository.create()`) that don't
actually work together. Edge cases are the smallest slice by design —
they're the "does the boundary actually hold" spot-checks (self-prereq,
indirect 3-node cycles, wrong password) layered on top of the main-path
coverage the first two categories already provide.

---

## 10. Non-functional requirements

- **Performance:** course lookup is a SQLite primary-key read (O(1) expected); prerequisite validation is a set-difference (O(n)); path finding is BFS, O(V+E).
- **Maintainability:** SQL lives only in `data/repository.py`; the GUI never imports `sqlite3`.
- **Extensibility:** see the "Swapping components" section of `README.md`.

To make these concrete for the scale this app is built for (a single
institution's course catalog — tens to low hundreds of courses, not
millions):

- **Performance** is dominated by SQLite's own primary-key B-tree lookups
  (effectively O(log n), rounding to O(1) for catalog sizes this small)
  and in-memory set/graph operations that are already algorithmically
  optimal for this problem size (Section 3) — there's no expectation of
  needing caching, indexing beyond SQLite's defaults, or a different
  database engine at this scale.
- **Maintainability** is measured concretely by "how many files change
  for a given kind of edit": a wording/validation change touches one
  `core/` file; a new query touches one `data/repository.py` method; a
  new business rule touches one `services/` method; a new page touches
  one `gui/` file. The layering in Section 1 is what keeps those blast
  radii small and non-overlapping.
- **Extensibility** is demonstrated, not just claimed, by the three
  concrete swap scenarios in the README (new `PathFinder` strategy, new
  database engine, new GUI framework) — each one requires touching
  exactly one layer, which is the architecture's actual test.

---

## 11. Design decisions and trade-offs

A few choices made deliberately, with their downsides acknowledged rather
than hidden:

- **Passwords are stored in plaintext on `User`**, and the fixed
  Administrator account's credentials live as a constant inside
  `AuthService` rather than a database row. Both are explicitly
  documented as capstone-scope simplifications, not production-grade
  security — see the "Known scope limitations" section of `README.md`.
- **One shared SQLite connection via the `DatabaseManager` singleton**
  is simple and correct for a single-user desktop app, but is a
  deliberate non-goal for concurrent multi-process writers; a
  server-backed multi-user deployment would need a different connection
  strategy (a real connection pool, or a client/server database) — which
  is exactly the kind of change the Repository pattern is meant to
  contain to `data/database.py` and `data/repository.py` alone.
- **The prerequisite graph is rebuilt from the database on every service
  construction** (`CourseService._rebuild_graph()`), rather than being
  persisted as a graph structure itself. This trades a small amount of
  startup work (re-reading every course and prerequisite link) for a
  guarantee that the in-memory graph can never silently drift out of
  sync with what's actually stored — there's exactly one source of
  truth (the `prerequisites` table), and the graph is always a fresh
  derivation of it.
- **Learner IDs are generated by scanning and incrementing, not by an
  autoincrement column** (`generate_next_learner_id()` in
  `core/id_generator.py`), specifically so IDs stay in the human-readable
  `L001` format rather than a raw integer, at the cost of an O(n) scan
  over all learners on every new registration — an acceptable trade-off
  at this scale, and the same reasoning that motivated the
  `renumber_learner_ids.py` migration when that invariant had drifted
  (random IDs had crept in) and needed restoring.
