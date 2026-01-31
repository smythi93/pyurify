"""Test to verify class check in SingleAssertionExtractor works correctly."""

import ast
from pyurify.purification import SingleAssertionExtractor

# Test code with multiple classes and same test name
CODE_WITH_MULTIPLE_CLASSES = """
class TestClassA:
    def test_example(self):
        a = 1
        assert a == 1  # Line 5
        
class TestClassB:
    def test_example(self):
        b = 2
        assert b == 2  # Line 10
"""


def test_extract_from_class_a():
    """Test extracting assertion from TestClassA."""
    tree = ast.parse(CODE_WITH_MULTIPLE_CLASSES)
    extractor = SingleAssertionExtractor(
        "test_example", target_assertion_line=5, target_class_name="TestClassA"
    )
    result = ast.unparse(extractor.visit(tree))

    assert (
        result.count("assert") == 1
    ), f"Expected 1 assertion, got {result.count('assert')}"
    assert "a == 1" in result, "Should have assertion from TestClassA"
    assert "b == 2" not in result, "Should NOT have assertion from TestClassB"


def test_extract_from_class_b():
    """Test extracting assertion from TestClassB."""
    tree = ast.parse(CODE_WITH_MULTIPLE_CLASSES)
    extractor = SingleAssertionExtractor(
        "test_example", target_assertion_line=10, target_class_name="TestClassB"
    )
    result = ast.unparse(extractor.visit(tree))

    assert (
        result.count("assert") == 1
    ), f"Expected 1 assertion, got {result.count('assert')}"
    assert "b == 2" in result, "Should have assertion from TestClassB"
    assert "a == 1" not in result, "Should NOT have assertion from TestClassA"


def test_extract_without_class_filter():
    """Test extracting assertion without class filter."""
    tree = ast.parse(CODE_WITH_MULTIPLE_CLASSES)
    extractor = SingleAssertionExtractor(
        "test_example", target_assertion_line=5, target_class_name=None
    )
    result = ast.unparse(extractor.visit(tree))

    assert (
        result.count("assert") == 1
    ), f"Expected 1 assertion, got {result.count('assert')}"
