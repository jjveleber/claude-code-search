import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval.unit import parse_search_output, score_entry, aggregate_unit_metrics


def test_parse_search_output_extracts_paths():
    output = (
        "MATCH 1: llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp (lines 120-180)\n"
        "----------------------------------------\n"
        "some code\n\n"
        "MATCH 2: llvm/lib/Target/X86/X86ISelLowering.cpp (lines 3200-3260)\n"
        "----------------------------------------\n"
        "more code\n\n"
    )
    paths = parse_search_output(output)
    assert paths == [
        "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp",
        "llvm/lib/Target/X86/X86ISelLowering.cpp",
    ]


def test_parse_search_output_empty():
    assert parse_search_output("No results found.\n") == []
    assert parse_search_output("") == []


def test_score_entry_hit_at_rank_1():
    result = score_entry(
        results=["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp", "other.cpp"],
        expected=["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"],
        acceptable=[],
        k=5,
    )
    assert result["hit"] is True
    assert result["recall_at_k"] == 1.0
    assert result["reciprocal_rank"] == 1.0
    assert result["precision_at_k"] == pytest.approx(1.0 / 5)


def test_score_entry_miss():
    result = score_entry(
        results=["other.cpp", "another.cpp"],
        expected=["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"],
        acceptable=[],
        k=5,
    )
    assert result["hit"] is False
    assert result["recall_at_k"] == 0.0
    assert result["reciprocal_rank"] == 0.0
    assert result["precision_at_k"] == 0.0


def test_score_entry_acceptable_partial_credit():
    result = score_entry(
        results=["acceptable.cpp"],
        expected=["expected.cpp"],
        acceptable=["acceptable.cpp"],
        k=5,
    )
    assert result["hit"] is False
    assert result["precision_at_k"] == pytest.approx(0.5 / 5)


def test_score_entry_hit_at_rank_3():
    result = score_entry(
        results=["a.cpp", "b.cpp", "llvm/target.cpp"],
        expected=["llvm/target.cpp"],
        acceptable=[],
        k=5,
    )
    assert result["hit"] is True
    assert result["reciprocal_rank"] == pytest.approx(1.0 / 3)


def test_aggregate_unit_metrics():
    task_results = [
        {"hit": True, "recall_at_k": 1.0, "reciprocal_rank": 1.0, "precision_at_k": 0.2},
        {"hit": False, "recall_at_k": 0.0, "reciprocal_rank": 0.0, "precision_at_k": 0.0},
    ]
    summary = aggregate_unit_metrics(task_results)
    assert summary["hit_rate"] == pytest.approx(0.5)
    assert summary["recall_at_k"] == pytest.approx(0.5)
    assert summary["MRR"] == pytest.approx(0.5)
    assert summary["precision_at_k"] == pytest.approx(0.1)
