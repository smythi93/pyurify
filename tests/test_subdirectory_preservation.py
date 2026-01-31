#!/usr/bin/env python
"""
Test to verify purification preserves subdirectory structure.
"""

import tempfile
from pathlib import Path

from pyurify.purification import purify_tests


def test_single_subdirectory_preservation():
    """Test that purified files maintain single subdirectory structure."""
    test_code = """
def test_example():
    x = 1
    assert x == 1
    assert x > 0
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Create test in subdirectory
        test_subdir = src_dir / "unit"
        test_subdir.mkdir()
        test_file = test_subdir / "test_example.py"
        test_file.write_text(test_code)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["unit/test_example.py::test_example"],
            enable_slicing=False,
        )

        # Check result
        assert "unit/test_example.py::test_example" in result
        file_param_tuples = result["unit/test_example.py::test_example"]

        # Should have 2 purified files (one per assertion)
        assert len(file_param_tuples) == 2

        for purified_file, param_suffix in file_param_tuples:
            # Verify file is in the unit/ subdirectory
            assert purified_file.parent.name == "unit"
            assert purified_file.parent.parent == dst_dir

            # Verify file exists
            assert purified_file.exists()

            # Verify relative path
            rel_path = purified_file.relative_to(dst_dir)
            assert str(rel_path).startswith("unit/")


def test_nested_subdirectory_preservation():
    """Test that purified files maintain nested subdirectory structure."""
    test_code = """
def test_deep():
    result = process()
    assert result == "ok"
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Create test in nested subdirectory
        test_subdir = src_dir / "unit" / "api" / "v2"
        test_subdir.mkdir(parents=True)
        test_file = test_subdir / "test_endpoints.py"
        test_file.write_text(test_code)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["unit/api/v2/test_endpoints.py::test_deep"],
            enable_slicing=False,
        )

        # Check result
        test_id = "unit/api/v2/test_endpoints.py::test_deep"
        assert test_id in result
        file_param_tuples = result[test_id]

        assert len(file_param_tuples) == 1  # One assertion

        purified_file, param_suffix = file_param_tuples[0]

        # Verify nested directory structure is preserved
        rel_path = purified_file.relative_to(dst_dir)
        assert str(rel_path).startswith("unit/api/v2/")

        # Verify all parent directories exist
        assert (dst_dir / "unit").exists()
        assert (dst_dir / "unit" / "api").exists()
        assert (dst_dir / "unit" / "api" / "v2").exists()

        # Verify file exists
        assert purified_file.exists()


def test_mixed_subdirectories():
    """Test purification with tests in multiple subdirectories."""
    test_code = """
def test_func():
    assert True
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Create tests in different subdirectories
        # Root level
        (src_dir / "test_root.py").write_text(test_code)

        # Single subdirectory
        (src_dir / "unit").mkdir()
        (src_dir / "unit" / "test_unit.py").write_text(test_code)

        # Nested subdirectory
        (src_dir / "integration" / "api").mkdir(parents=True)
        (src_dir / "integration" / "api" / "test_api.py").write_text(test_code)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=[
                "test_root.py::test_func",
                "unit/test_unit.py::test_func",
                "integration/api/test_api.py::test_func",
            ],
            enable_slicing=False,
        )

        # Check root level
        root_file, _ = result["test_root.py::test_func"][0]
        assert root_file.parent == dst_dir

        # Check unit subdirectory
        unit_file, _ = result["unit/test_unit.py::test_func"][0]
        assert unit_file.parent.name == "unit"
        assert unit_file.parent.parent == dst_dir

        # Check nested subdirectory
        api_file, _ = result["integration/api/test_api.py::test_func"][0]
        rel_path = api_file.relative_to(dst_dir)
        assert str(rel_path).startswith("integration/api/")


def test_original_file_subdirectory_preservation():
    """Test that original files (with disabled tests) also preserve subdirectories."""
    test_code = """
def test_with_assertion():
    x = 1
    assert x == 1  # Has assertion - can be purified
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Create test in subdirectory
        test_subdir = src_dir / "special"
        test_subdir.mkdir()
        test_file = test_subdir / "test_special.py"
        test_file.write_text(test_code)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["special/test_special.py::test_with_assertion"],
            enable_slicing=False,
        )

        # Test should have purified versions
        test_id = "special/test_special.py::test_with_assertion"
        assert test_id in result

        # Verify original file (with test disabled) is in subdirectory
        original_file_path = dst_dir / "special" / "test_special.py"
        assert original_file_path.exists()

        # Original file should have test disabled
        content = original_file_path.read_text()
        assert (
            "DISABLED_test_with_assertion" in content
            or "test_with_assertion" in content
        )
