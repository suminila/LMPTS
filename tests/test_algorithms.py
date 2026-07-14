import pytest
from core.algorithms import PrerequisiteGraph, BFSShortestPathFinder, DifficultyProgressivePathFinder
from core.exceptions import CircularDependencyError


def build_chain_graph():
    g = PrerequisiteGraph()
    g.add_edge("CSE101", "CSE201")
    g.add_edge("CSE201", "CSE301")
    g.add_edge("CSE301", "CSE401")
    return g


def test_add_edge_creates_relationship():
    g = PrerequisiteGraph()
    g.add_edge("CSE101", "CSE201")
    assert g.direct_prerequisites("CSE201") == {"CSE101"}


def test_direct_cycle_detected():
    g = PrerequisiteGraph()
    g.add_edge("A", "B")
    with pytest.raises(CircularDependencyError):
        g.add_edge("B", "A")


def test_indirect_cycle_detected():
    g = PrerequisiteGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    with pytest.raises(CircularDependencyError):
        g.add_edge("C", "A")  # would close A->B->C->A


def test_self_loop_rejected():
    g = PrerequisiteGraph()
    with pytest.raises(CircularDependencyError):
        g.add_edge("A", "A")


def test_transitive_prerequisites():
    g = build_chain_graph()
    assert g.all_prerequisites("CSE401") == {"CSE101", "CSE201", "CSE301"}


def test_course_level_calculation():
    g = build_chain_graph()
    assert g.level("CSE101") == 0
    assert g.level("CSE201") == 1
    assert g.level("CSE401") == 3


def test_bfs_shortest_path():
    g = build_chain_graph()
    finder = BFSShortestPathFinder()
    path = finder.find_path(g, "CSE101", "CSE401")
    assert path == ["CSE101", "CSE201", "CSE301", "CSE401"]


def test_bfs_no_path_returns_empty():
    g = build_chain_graph()
    g.add_course("ISOLATED")
    finder = BFSShortestPathFinder()
    assert finder.find_path(g, "ISOLATED", "CSE401") == []


def test_difficulty_progressive_orders_by_level():
    g = build_chain_graph()
    finder = DifficultyProgressivePathFinder()
    path = finder.find_path(g, "CSE101", "CSE401")
    assert path[-1] == "CSE401"
    assert path == sorted(path, key=lambda c: g.level(c))
