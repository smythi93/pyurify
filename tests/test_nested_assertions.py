"""Test to verify SingleAssertionExtractor handles nested assertions correctly."""

import ast
from pyurify.purification import SingleAssertionExtractor

# Test case with nested assertions (like cookiecutter)
CODE_WITH_NESTED_ASSERTIONS = """
def test_find_hook(self):
    with utils.work_in(self.repo_path):
        expected_pre = os.path.abspath('hooks/pre_gen_project.py')
        actual_hook_path = hooks.find_hook('pre_gen_project')
        assert expected_pre == actual_hook_path[0]
        expected_post = os.path.abspath('hooks/{}'.format(self.post_hook))
        actual_hook_path = hooks.find_hook('post_gen_project')
        assert expected_post == actual_hook_path[0]
"""


def test_nested_assertion_first():
    """Test extracting first assertion from within 'with' block."""
    tree = ast.parse(CODE_WITH_NESTED_ASSERTIONS)
    extractor = SingleAssertionExtractor(
        "test_find_hook", target_assertion_line=6, target_class_name=None
    )
    new_tree = extractor.visit(tree)
    result = ast.unparse(new_tree)

    assert (
        result.count("assert") == 1
    ), f"Expected 1 assertion, got {result.count('assert')}"
    assert (
        "expected_pre == actual_hook_path[0]" in result
    ), "Should have first assertion"
    assert (
        "expected_post == actual_hook_path[0]" not in result
    ), "Should NOT have second assertion"
    # Code after first assertion should remain
    assert (
        "expected_post = os.path.abspath" in result
    ), "Should have code after first assertion"
    assert (
        "hooks.find_hook('post_gen_project')" in result
    ), "Should have code after first assertion"


def test_nested_assertion_second():
    """Test extracting second assertion from within 'with' block."""
    tree = ast.parse(CODE_WITH_NESTED_ASSERTIONS)
    extractor = SingleAssertionExtractor(
        "test_find_hook", target_assertion_line=9, target_class_name=None
    )
    new_tree = extractor.visit(tree)
    result = ast.unparse(new_tree)

    assert (
        result.count("assert") == 1
    ), f"Expected 1 assertion, got {result.count('assert')}"
    assert (
        "expected_post == actual_hook_path[0]" in result
    ), "Should have second assertion"
    # First assertion should be removed but setup code before second assertion should remain
    assert (
        "expected_post = os.path.abspath" in result
    ), "Should have setup code for second assertion"
