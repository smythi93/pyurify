#!/usr/bin/env python
"""
Test to verify purified test files are correctly copied to the directory.
"""

import tempfile
import shutil
from pathlib import Path


def test_recursive_copy():
    """Test that purified files are copied recursively including subdirectories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create source directory structure (simulating purified_tests_dir)
        purified_tests_dir = tmpdir / "purified"
        purified_tests_dir.mkdir()

        # Create purified test files in root
        (purified_tests_dir / "test_simple_test_func_assertion_10.py").write_text(
            "# test 1"
        )
        (purified_tests_dir / "test_simple_test_func_assertion_15.py").write_text(
            "# test 2"
        )

        # Create original test file in subdirectory (disabled)
        tests_subdir = purified_tests_dir / "tests"
        tests_subdir.mkdir()
        (tests_subdir / "test_hooks.py").write_text("# disabled original test")

        # Create destination directory structure (simulating sfl_path/tests)
        test_base_sfl = tmpdir / "sfl" / "tests"
        test_base_sfl.mkdir(parents=True)

        # Simulate the copying logic from tcp.py
        for item in purified_tests_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(purified_tests_dir)
                dst = test_base_sfl / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)

        # Verify all files were copied
        # Check root-level purified files
        file1 = test_base_sfl / "test_simple_test_func_assertion_10.py"
        file2 = test_base_sfl / "test_simple_test_func_assertion_15.py"

        assert file1.exists(), f"File should exist: {file1}"
        assert file2.exists(), f"File should exist: {file2}"

        # Check subdirectory file
        file3 = test_base_sfl / "tests" / "test_hooks.py"
        assert file3.exists(), f"File should exist: {file3}"

        # Count total files
        all_files = list(test_base_sfl.rglob("*.py"))
        assert len(all_files) == 3, f"Expected 3 files, got {len(all_files)}"
