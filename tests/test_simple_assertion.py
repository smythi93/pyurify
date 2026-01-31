"""Quick test to verify SingleAssertionExtractor basic functionality."""

import ast
from pyurify.purification import SingleAssertionExtractor


def test_simple_assertion_extraction():
    """Test basic assertion extraction from a simple test."""
    code = """
def test_example(self):
    a = 1
    assert a == 1
    b = 2
    assert b == 2
"""

    tree = ast.parse(code)
    extractor = SingleAssertionExtractor(
        "test_example", target_assertion_line=4, target_class_name=None
    )
    new_tree = extractor.visit(tree)
    result = ast.unparse(new_tree)

    assert (
        result.count("assert") == 1
    ), f"Expected 1 assertion, got {result.count('assert')}"
    assert "a == 1" in result, "Should have first assertion"
    assert "b = 2" not in result, "Should not have code after first assertion"
    assert "b == 2" not in result, "Should not have second assertion"
