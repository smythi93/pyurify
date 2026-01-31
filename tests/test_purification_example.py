"""
Example/Test for Test Case Purification

This demonstrates how to use the purification module with integrated pipeline.
"""

from pyurify.purification import rank_refinement


def test_purification_example():
    """
    Example test showing how to use the purification module.

    To use in practice:
    1. Set up source and destination directories
    2. Identify failing tests using pytest
    3. Run purification
    4. Use sflkit to analyze both original and purified tests
    5. Apply rank refinement
    """

    # Example usage (would need actual project structure):
    # src_dir = Path("./my_project")
    # dst_dir = Path("./my_project_purified")
    # failing_tests = [
    #     "tests/test_calculator.py::test_divide",
    #     "tests/test_math.py::TestMath::test_complex_operation"
    # ]

    # Step 1: Purify tests
    # purified = purify_tests(
    #     src_dir=src_dir,
    #     dst_dir=dst_dir,
    #     failing_tests=failing_tests,
    #     enable_slicing=False  # Set to True to enable dynamic slicing
    # )

    # Step 2: Run sflkit on both original and purified directories
    # This would use sflkit.Analyzer to collect spectra

    # Step 3: Apply rank refinement
    # Assuming you have original scores from sflkit:
    original_scores = {
        "file.py:10": 0.8,
        "file.py:20": 0.6,
        "file.py:30": 0.4,
    }

    # And spectra from purified tests:
    purified_spectra = [
        {"file.py:10": True, "file.py:20": True, "file.py:30": False},
        {"file.py:10": True, "file.py:20": False, "file.py:30": False},
        {"file.py:10": False, "file.py:20": True, "file.py:30": True},
    ]

    # Get refined scores
    refined_scores = rank_refinement(
        original_scores=original_scores,
        purified_spectra=purified_spectra,
        technique="combined",  # or "ratio_only" or "original_only"
    )

    # Verify that scores are normalized and refined
    assert all(0 <= score <= 1 for score in refined_scores.values())
    assert len(refined_scores) == len(original_scores)
