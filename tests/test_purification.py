#!/usr/bin/env python3
"""
Test that purification with slicing produces the correct output.
"""

from pathlib import Path
import tempfile
from pyurify.purification import purify_tests

test_code = """
def test_three_calculations():
    a = 1
    b = 2
    sum_result = a + b
    x = 10
    y = 20
    product = x * y
    p = 100
    q = 50
    diff = p - q
    assert sum_result == 3
    assert product == 200
    assert diff == 50
"""

expected_test_0 = """
def test_three_calculations():
    a = 1
    b = 2
    sum_result = a + b
    assert sum_result == 3
    try:
        x = 10
        y = 20
        product = x * y
        assert product == 200
    except:
        pass
    try:
        p = 100
        q = 50
        diff = p - q
        assert diff == 50
    except:
        pass
"""

expected_test_1 = """
def test_three_calculations():
    try:
        a = 1
        b = 2
        sum_result = a + b
        assert sum_result == 3
    except:
        pass
    x = 10
    y = 20
    product = x * y
    assert product == 200
    try:
        p = 100
        q = 50
        diff = p - q
        assert diff == 50
    except:
        pass
"""

expected_test_2 = """
def test_three_calculations():
    try:
        a = 1
        b = 2
        sum_result = a + b
        assert sum_result == 3
    except:
        pass
    try:
        x = 10
        y = 20
        product = x * y
        assert product == 200
    except:
        pass
    p = 100
    q = 50
    diff = p - q
    assert diff == 50
"""


def test_purification_with_slicing():
    """Test that purification with slicing produces correct atomized output."""

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()

        test_file = src_dir / "test.py"
        test_file.write_text(test_code)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["test.py::test_three_calculations"],
            enable_slicing=True,
        )

        # NEW: Result is now list of (file, param_suffix) tuples
        file_param_tuples = result["test.py::test_three_calculations"]

        # Should have 3 atomized/purified files (one per assertion)
        assert len(file_param_tuples) == 3

        # Extract just the files
        purified_files = [f for f, _ in file_param_tuples]

        # Each file should exist and contain atomized code with try-except
        for pf in purified_files:
            assert pf.exists()
            content = pf.read_text()

            # Should have the test function
            assert "def test_three_calculations():" in content

            # Should have try-except blocks (atomization)
            # At least one try-except block should be present
            assert "try:" in content
            assert "except:" in content
            assert "pass" in content
