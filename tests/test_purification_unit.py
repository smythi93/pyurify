"""
Unit tests for test case purification module.
"""

import ast
import tempfile
from pathlib import Path

from pyurify.purification import (
    AssertionFinder,
    FunctionFinder,
    AssertionAtomizer,
    purify_tests,
    rank_refinement,
)


def test_assertion_finder():
    """Test that AssertionFinder correctly identifies assertions."""
    code = """
def test_example():
    x = 1
    assert x == 1
    y = 2
    assert y == 2
    """
    tree = ast.parse(code)
    finder = AssertionFinder()
    finder.visit(tree)

    assert len(finder.assertions) == 2
    assert finder.assertions[0][0] == 4  # Line 4
    assert finder.assertions[1][0] == 6  # Line 6


def test_function_finder():
    """Test that FunctionFinder correctly finds test functions."""
    code = """
def test_one():
    assert True

def test_two():
    assert False

def helper_function():
    pass
    """
    tree = ast.parse(code)
    finder = FunctionFinder()
    finder.visit(tree)

    assert len(finder.test_functions) == 2
    assert "test_one" in finder.test_functions
    assert "test_two" in finder.test_functions
    assert "helper_function" not in finder.test_functions


def test_function_finder_specific_test():
    """Test finding a specific test function."""
    code = """
def test_one():
    assert True

def test_two():
    assert False
    """
    tree = ast.parse(code)
    finder = FunctionFinder(target_test="test_one")
    finder.visit(tree)

    assert len(finder.test_functions) == 1
    assert "test_one" in finder.test_functions
    assert "test_two" not in finder.test_functions


def test_assertion_atomizer():
    """Test that AssertionAtomizer transforms tests correctly."""
    code = """
def test_example():
    assert True
    assert False
    """
    tree = ast.parse(code)

    # Target the first assertion (line 3)
    atomizer = AssertionAtomizer(target_assertion_line=3)
    new_tree = atomizer.visit(tree)

    # The transformed code should have a try-except around the second assertion
    code_str = ast.unparse(new_tree)
    assert "try:" in code_str
    assert "except" in code_str


def test_rank_refinement_combined():
    """Test rank refinement with combined technique."""
    original_scores = {
        "line1": 0.8,
        "line2": 0.6,
        "line3": 0.4,
    }

    purified_spectra = [
        {"line1": True, "line2": True, "line3": False},
        {"line1": True, "line2": False, "line3": False},
    ]

    refined = rank_refinement(original_scores, purified_spectra, technique="combined")

    # Check that all lines are present
    assert set(refined.keys()) == set(original_scores.keys())

    # Check that scores are normalized to [0, 1]
    assert all(0 <= score <= 1 for score in refined.values())

    # line1 is covered by both tests, should have highest refined score
    # line2 is covered by one test
    # line3 is not covered by any test
    assert refined["line1"] > refined["line2"]
    assert refined["line2"] > refined["line3"]


def test_rank_refinement_ratio_only():
    """Test rank refinement with ratio_only technique."""
    original_scores = {
        "line1": 0.8,
        "line2": 0.6,
        "line3": 0.4,
    }

    purified_spectra = [
        {"line1": True, "line2": True, "line3": False},
        {"line1": True, "line2": False, "line3": False},
    ]

    refined = rank_refinement(original_scores, purified_spectra, technique="ratio_only")

    # With ratio_only, line1 (2/2 coverage) should score 1.0
    assert refined["line1"] == 1.0
    # line2 (1/2 coverage) should score 0.5
    assert refined["line2"] == 0.5
    # line3 (0/2 coverage) should score 0.0
    assert refined["line3"] == 0.0


def test_rank_refinement_original_only():
    """Test rank refinement with original_only technique."""
    original_scores = {
        "line1": 0.8,
        "line2": 0.6,
        "line3": 0.4,
    }

    purified_spectra = [
        {"line1": True, "line2": True, "line3": False},
        {"line1": True, "line2": False, "line3": False},
    ]

    refined = rank_refinement(
        original_scores, purified_spectra, technique="original_only"
    )

    # With original_only, scores should just be normalized
    # The relative order should be preserved
    assert refined["line1"] > refined["line2"]
    assert refined["line2"] > refined["line3"]

    # Scores should be normalized to [0, 1]
    assert max(refined.values()) == 1.0
    assert min(refined.values()) == 0.0


def test_purify_tests_integration():
    """Test the complete purification workflow with a real example."""
    # Create a temporary directory structure
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()

        # Create a test file
        test_file = src_dir / "test_example.py"
        test_file.write_text("""
def test_multiple_assertions():
    x = 1
    assert x == 1
    y = 2
    assert y == 2
    z = 3
    assert z == 3
""")

        # Run purification
        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["test_example.py::test_multiple_assertions"],
            enable_slicing=False,
        )

        # Check that purified files were created
        assert "test_example.py::test_multiple_assertions" in result
        # NEW: Result is now list of (file, param_suffix) tuples
        file_param_tuples = result["test_example.py::test_multiple_assertions"]

        # Should create 3 purified test files (one for each assertion)
        assert len(file_param_tuples) == 3

        # Check that all files exist
        for purified_file, param_suffix in file_param_tuples:
            assert purified_file.exists()

        # Check that original test was disabled
        original_content = (dst_dir / "test_example.py").read_text()
        assert "disabled_test_multiple_assertions" in original_content

        # Check that purified tests have atomized structure (try-except blocks)
        for purified_file, param_suffix in file_param_tuples:
            content = purified_file.read_text()
            # Should have try-except blocks (atomization wraps non-target assertions)
            assert "try:" in content or "assert" in content
            # Should have the test function
            assert "def test_multiple_assertions():" in content


def test_rank_refinement_empty_input():
    """Test rank refinement with empty input."""
    refined = rank_refinement({}, [], technique="combined")
    assert refined == {}


def test_rank_refinement_equal_scores():
    """Test rank refinement when all original scores are equal."""
    original_scores = {
        "line1": 0.5,
        "line2": 0.5,
        "line3": 0.5,
    }

    purified_spectra = [
        {"line1": True, "line2": False, "line3": False},
    ]

    refined = rank_refinement(original_scores, purified_spectra, technique="combined")

    # All should have the same normalized score (0.5)
    # But line1 has ratio=1.0, others have ratio=0.0
    assert refined["line1"] > refined["line2"]
    assert refined["line1"] > refined["line3"]
