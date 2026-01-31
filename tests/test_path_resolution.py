#!/usr/bin/env python
"""
Test to verify path resolution with overlapping paths works correctly.
"""

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from pyurify.purification import _resolve_test_file_path


def test_path_resolution():
    """Test various path resolution scenarios."""
    # Create temporary directory structure
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create directory structure
        test_dir = tmpdir / "cookiecutter_2" / "tests"
        test_dir.mkdir(parents=True)

        # Create test file
        test_file = test_dir / "test_hooks.py"
        test_file.write_text("# test file")

        # Test Case 1: Overlapping 'tests' in both paths
        test_base = tmpdir / "cookiecutter_2" / "tests"
        test_file_rel = "tests/test_hooks.py"
        resolved = _resolve_test_file_path(test_base, test_file_rel)
        expected = tmpdir / "cookiecutter_2" / "tests" / "test_hooks.py"

        assert resolved.exists(), f"Resolved path should exist: {resolved}"
        assert resolved == expected, f"Expected {expected}, got {resolved}"

        # Test Case 2: Simple concatenation
        test_base = tmpdir / "cookiecutter_2" / "tests"
        test_file_rel = "test_hooks.py"
        resolved = _resolve_test_file_path(test_base, test_file_rel)
        expected = tmpdir / "cookiecutter_2" / "tests" / "test_hooks.py"

        assert resolved.exists(), f"Resolved path should exist: {resolved}"
        assert resolved == expected, f"Expected {expected}, got {resolved}"

        # Test Case 3: test_base doesn't include 'tests'
        test_base = tmpdir / "cookiecutter_2"
        test_file_rel = "tests/test_hooks.py"
        resolved = _resolve_test_file_path(test_base, test_file_rel)
        expected = tmpdir / "cookiecutter_2" / "tests" / "test_hooks.py"

        assert resolved.exists(), f"Resolved path should exist: {resolved}"
        assert resolved == expected, f"Expected {expected}, got {resolved}"

        # Test Case 4: Partial overlap in subdirectory
        subdir = test_dir / "t"
        subdir.mkdir()
        sub_test_file = subdir / "test_hooks.py"
        sub_test_file.write_text("# sub test file")

        test_base = tmpdir / "cookiecutter_2" / "tests" / "t"
        test_file_rel = "t/test_hooks.py"
        resolved = _resolve_test_file_path(test_base, test_file_rel)
        expected = tmpdir / "cookiecutter_2" / "tests" / "t" / "test_hooks.py"

        assert resolved.exists(), f"Resolved path should exist: {resolved}"
        assert resolved == expected, f"Expected {expected}, got {resolved}"

        # Test Case 5: No overlap, direct concatenation
        test_base = tmpdir / "cookiecutter_2" / "tests"
        test_file_rel = "subdir/test_file.py"
        resolved = _resolve_test_file_path(test_base, test_file_rel)
        expected = tmpdir / "cookiecutter_2" / "tests" / "subdir" / "test_file.py"

        # This one won't exist, but path should be correct
        assert resolved == expected, f"Expected {expected}, got {resolved}"

        test_base = tmpdir / "cookiecutter_2" / "tests" / "test_hooks.py"
        test_file_rel = "tests/test_hooks.py"
        resolved = _resolve_test_file_path(test_base, test_file_rel)
        expected = tmpdir / "cookiecutter_2" / "tests" / "test_hooks.py"

        assert resolved == expected, f"Expected {expected}, got {resolved}"
