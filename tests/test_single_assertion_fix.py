"""Test to verify SingleAssertionExtractor only keeps one assertion."""

import ast
from pyurify.purification import SingleAssertionExtractor

TEST_CODE = """
def test_find_hook(self):
    with utils.work_in(self.repo_path):
        expected_pre = os.path.abspath('hooks/pre_gen_project.py')
        actual_hook_path = hooks.find_hook('pre_gen_project')
        assert expected_pre == actual_hook_path[0]  # Line 6
        expected_post = os.path.abspath('hooks/{}'.format(self.post_hook))
        actual_hook_path = hooks.find_hook('post_gen_project')
        assert expected_post == actual_hook_path[0]  # Line 9
"""


def test_extract_first_assertion():
    """Test extracting first assertion stops processing after target."""
    tree = ast.parse(TEST_CODE)
    extractor = SingleAssertionExtractor(
        "test_find_hook", target_assertion_line=6, target_class_name=None
    )
    new_tree = extractor.visit(tree)
    new_code = ast.unparse(new_tree)

    # Verify only one assertion
    assertion_count = new_code.count("assert")
    assert assertion_count == 1, f"Expected 1 assertion, got {assertion_count}"

    # Verify it's the correct assertion
    assert (
        "expected_pre == actual_hook_path[0]" in new_code
    ), "Should have first assertion"
    assert (
        "expected_post == actual_hook_path[0]" not in new_code
    ), "Should not have second assertion"

    # Verify code before assertion is kept
    assert (
        "expected_pre = os.path.abspath" in new_code
    ), "Should have setup code before assertion"
    assert (
        "hooks.find_hook('pre_gen_project')" in new_code
    ), "Should have code before assertion"

    # Verify code after assertion is kept
    assert (
        "expected_post = os.path.abspath" in new_code
    ), "Should have code after assertion"
    assert (
        "hooks.find_hook('post_gen_project')" in new_code
    ), "Should have code after assertion"


def test_extract_second_assertion():
    """Test extracting second assertion keeps all code before it."""
    tree = ast.parse(TEST_CODE)
    extractor = SingleAssertionExtractor(
        "test_find_hook", target_assertion_line=9, target_class_name=None
    )
    new_tree = extractor.visit(tree)
    new_code = ast.unparse(new_tree)

    # Verify only one assertion
    assertion_count = new_code.count("assert")
    assert assertion_count == 1, f"Expected 1 assertion, got {assertion_count}"

    # Verify it's the correct assertion
    assert (
        "expected_post == actual_hook_path[0]" in new_code
    ), "Should have second assertion"
    assert (
        "expected_pre == actual_hook_path[0]" not in new_code
    ), "First assertion should be removed"

    # Verify all code before this assertion is kept
    assert "expected_pre = os.path.abspath" in new_code, "Should have all setup code"
    assert (
        "expected_post = os.path.abspath" in new_code
    ), "Should have setup for second assertion"
