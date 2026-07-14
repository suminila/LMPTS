"""
Standalone algorithms, independent of persistence/UI.

- PrerequisiteGraph: directed graph, adjacency-set representation.
- Cycle detection via DFS reachability check performed BEFORE an edge is added.
- Course "level" via recursive tree traversal with memoisation.
- PathFinder strategies (Strategy pattern): BFS shortest path, and a
  difficulty-progressive variant. New strategies can be added without
  touching existing code (Open/Closed principle).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, List, Optional, Set

from core.exceptions import CircularDependencyError


class PrerequisiteGraph:
    """
    Directed graph where an edge prereq -> dependent means
    `prereq` must be completed before `dependent`.

    Internally stored as dependent -> set(direct prerequisites),
    which gives O(1) prerequisite lookups per course.
    """

    def __init__(self):
        self._prereqs_of: Dict[str, Set[str]] = {}   # course -> its direct prereqs
        self._dependents_of: Dict[str, Set[str]] = {}  # course -> courses that need it

    def add_course(self, code: str) -> None:
        self._prereqs_of.setdefault(code, set())
        self._dependents_of.setdefault(code, set())

    def remove_course(self, code: str) -> None:
        self._prereqs_of.pop(code, None)
        self._dependents_of.pop(code, None)
        for s in self._prereqs_of.values():
            s.discard(code)
        for s in self._dependents_of.values():
            s.discard(code)

    def _is_reachable(self, start: str, target: str) -> bool:
        """DFS: can we reach `target` by walking prereq->dependent edges from `start`?"""
        if start == target:
            return True
        visited = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            stack.extend(self._dependents_of.get(node, ()))
        return False

    def add_edge(self, prereq: str, dependent: str) -> None:
        """Add prereq -> dependent. Raises CircularDependencyError if it would create a cycle."""
        self.add_course(prereq)
        self.add_course(dependent)
        if prereq == dependent:
            raise CircularDependencyError(f"{prereq} cannot be a prerequisite of itself")
        # Adding prereq->dependent creates a cycle iff dependent already reaches prereq.
        if self._is_reachable(dependent, prereq):
            raise CircularDependencyError(
                f"Adding {prereq} -> {dependent} would create a circular dependency"
            )
        self._prereqs_of[dependent].add(prereq)
        self._dependents_of[prereq].add(dependent)

    def remove_edge(self, prereq: str, dependent: str) -> None:
        self._prereqs_of.get(dependent, set()).discard(prereq)
        self._dependents_of.get(prereq, set()).discard(dependent)

    def direct_prerequisites(self, code: str) -> Set[str]:
        return self._prereqs_of.get(code, set()).copy()

    def all_prerequisites(self, code: str) -> Set[str]:
        """Transitive closure of prerequisites via BFS."""
        visited: Set[str] = set()
        queue = deque(self._prereqs_of.get(code, ()))
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self._prereqs_of.get(node, ()))
        return visited

    def level(self, code: str, _memo: Optional[Dict[str, int]] = None) -> int:
        """Recursive tree traversal: level = 1 + max(level of direct prereqs), 0 if none."""
        if _memo is None:
            _memo = {}
        if code in _memo:
            return _memo[code]
        prereqs = self._prereqs_of.get(code, set())
        if not prereqs:
            _memo[code] = 0
            return 0
        lvl = 1 + max(self.level(p, _memo) for p in prereqs)
        _memo[code] = lvl
        return lvl

    def courses(self) -> List[str]:
        return list(self._prereqs_of.keys())


# --------------------------------------------------------------------------- #
# Strategy pattern: pluggable path-finding algorithms
# --------------------------------------------------------------------------- #
class PathFinder(ABC):
    """Common interface so LearningPathService can swap algorithms at runtime."""

    @abstractmethod
    def find_path(self, graph: PrerequisiteGraph, start: str, target: str) -> List[str]:
        raise NotImplementedError


class BFSShortestPathFinder(PathFinder):
    """Finds the shortest learning sequence (fewest courses) using BFS + a queue."""

    def find_path(self, graph: PrerequisiteGraph, start: str, target: str) -> List[str]:
        if start == target:
            return [start]
        queue = deque([[start]])
        visited = {start}
        while queue:
            path = queue.popleft()
            node = path[-1]
            for nxt in graph._dependents_of.get(node, ()):  # forward: node unlocks nxt
                if nxt in visited:
                    continue
                new_path = path + [nxt]
                if nxt == target:
                    return new_path
                visited.add(nxt)
                queue.append(new_path)
        return []


class DifficultyProgressivePathFinder(PathFinder):
    """
    Returns the full prerequisite chain needed to reach `target`, ordered by
    increasing prerequisite level (easiest/foundation courses first), ending
    with the target itself. Useful for "recommended study order".
    """

    def find_path(self, graph: PrerequisiteGraph, start: str, target: str) -> List[str]:
        required = graph.all_prerequisites(target) | {target}
        if start in required:
            required.discard(start)
        ordered = sorted(required, key=lambda c: graph.level(c))
        return ordered
