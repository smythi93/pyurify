"""Test to verify SingleAssertionExtractor works with optional class_name parameter."""

import ast
from pyurify.purification import SingleAssertionExtractor


def test_extractor_with_none_class_name():
    """Test that SingleAssertionExtractor works when class_name=None."""
    code = "def test_x():\n    assert 1 == 1\n"

    tree = ast.parse(code)
    extractor = SingleAssertionExtractor("test_x", 2, None)
    result = extractor.visit(tree)
    output = ast.unparse(result)

    assert "assert 1 == 1" in output, "Should contain the assertion"
    assert "def test_x" in output, "Should contain the test function"
