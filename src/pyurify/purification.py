"""
Test Case Purification for Fault Localization

This module implements test case purification as described in the paper.
The main phases are:
1. Test Case Atomization - Create single-assertion tests with try-except
2. Test Case Slicing - Use dynamic slicing to remove irrelevant statements
3. Rank Refinement - Combine original scores with purified test spectra

Classes and Functions:
- AtomizedTest: Represents an atomized test with one target assertion.
- ParameterizeInfo: Information about pytest.mark.parametrize decorators.
- ParameterizeFinder: Finds pytest.mark.parametrize decorators.
- AssertionFinder: Finds all assertions in a test function.
- FunctionFinder: Finds test functions in a module.
- AssertionAtomizer: Transforms tests to neutralize non-target assertions.
- SingleAssertionExtractor: Extracts a single assertion from a test function.
- TestFunctionFilter: Filters AST to keep only the target test function.
- StatementFilter: Filters AST to keep only relevant statements.
- TestDisabler: Renames test functions to disable them.
- rank_refinement: Refines rankings based on purified test spectra.
- purify_tests: Main function to purify failing tests.

Usage:
    from pyurify import purify_tests
    result = purify_tests(src_dir, dst_dir, failing_tests, enable_slicing=True)
"""

import ast
import hashlib
import os
import re
import shutil
import string
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set

from .logger import LOGGER
from .slicer import PytestSlicer


def safe_name(s: str):
    """
    Generate a safe filename from a string by replacing punctuation and spaces.

    :param s: Input string to sanitize.
    :returns: Sanitized string suitable for filenames.
    """
    # Encode to ASCII, ignore non-ASCII characters
    s = s.encode("ascii", "ignore")
    if len(s) > 255:
        # If too long, use MD5 hash
        return hashlib.md5(s).hexdigest()
    s = s.decode("ascii")
    # Replace punctuation with underscores
    for c in string.punctuation:
        if c in s:
            s = s.replace(c, "_")
    # Replace spaces with underscores
    s = s.replace(" ", "_")
    return s


class AtomizedTest:
    """
    Represents an atomized test with one target assertion.

    Atomized tests preserve the original line numbers and state by:
    - Wrapping non-target assertions in try-except to prevent failure
    - Keeping all function calls to preserve side effects
    - Maintaining the exact same line structure as the original test

    :param code: The atomized test code.
    :param assertion_line: Line number of the target assertion (in original file).
    :param test_name: Name of the test function.
    :param class_name: Name of the containing class (None for module-level functions).
    :param failing_line: Line number where the failure actually occurred (may differ from assertion_line).
    """

    def __init__(
        self,
        code: str,
        assertion_line: int,
        test_name: str,
        class_name: Optional[str] = None,
        failing_line: Optional[int] = None,
    ):
        # Store the atomized test code
        self.code = code
        # Line number of the target assertion in the original file
        self.assertion_line = assertion_line
        # Line number where the failure actually occurred (may differ)
        self.failing_line = failing_line if failing_line is not None else assertion_line
        # Name of the test function
        self.test_name = test_name
        # Name of the containing class (if any)
        self.class_name = class_name


# ============================================================================
# Phase 1: Test Case Atomization
# ============================================================================


class ParameterizeInfo:
    """
    Information about a pytest.mark.parametrize decorator.

    :param param_names: List of parameter names.
    :param param_values: List of parameter values (extracted later).
    """

    def __init__(self, param_names: list[str], param_values: list):
        # Store parameter names
        self.param_names = param_names
        # Store parameter values (to be filled later)
        self.param_values = param_values


class ParameterizeFinder(ast.NodeVisitor):
    """
    Find pytest.mark.parametrize decorators on a test function.

    :param parametrize_info: Information about the parametrize decorator found.
    """

    def __init__(self):
        # Initialize to None, will be set if found
        self.parametrize_info: Optional[ParameterizeInfo] = None

    @staticmethod
    def extract_parametrize_info(decorator: ast.expr) -> Optional[ParameterizeInfo]:
        """
        Extract parameter info from @pytest.mark.parametrize decorator.

        :param decorator: The decorator AST node.
        :returns: ParameterizeInfo if found, None otherwise.
        """
        # Check if it's a Call node (function call)
        if not isinstance(decorator, ast.Call):
            return None

        # Check if it's pytest.mark.parametrize
        if isinstance(decorator.func, ast.Attribute):
            if (
                isinstance(decorator.func.value, ast.Attribute)
                and isinstance(decorator.func.value.value, ast.Name)
                and decorator.func.value.value.id == "pytest"
                and decorator.func.value.attr == "mark"
                and decorator.func.attr == "parametrize"
            ):
                # Extract arguments
                if len(decorator.args) >= 2:
                    # First arg: parameter names (string or tuple of strings)
                    param_names_node = decorator.args[0]
                    if isinstance(param_names_node, ast.Constant):
                        # Single parameter or comma-separated string
                        param_names_str = param_names_node.value
                        param_names = [
                            name.strip() for name in param_names_str.split(",")
                        ]
                    else:
                        return None

                    # Note: Parameter values are extracted from test ID later,
                    # not from the AST decorator arguments
                    return ParameterizeInfo(param_names, [])

        return None


class AssertionFinder(ast.NodeVisitor):
    """
    Find all assertions in a test function.

    :param assertions: List of (line_number, ast_node) tuples for assertions.
    """

    def __init__(self):
        # List to store found assertions
        self.assertions: list[tuple[int, ast.AST]] = []  # (line_number, node)

    def visit_Assert(self, node: ast.Assert):
        """Visit assert statements."""
        # Add the assertion to the list
        self.assertions.append((node.lineno, node))
        # Continue visiting children
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr):
        """Visit expression statements (for pytest assertions like assert_equal)."""
        # Check if it's a call to an assertion function
        if isinstance(node.value, ast.Call):
            func_name = self._get_func_name(node.value.func)
            if func_name and "assert" in func_name.lower():
                # Add the assertion to the list
                self.assertions.append((node.lineno, node))
        # Continue visiting children
        self.generic_visit(node)

    @staticmethod
    def _get_func_name(node):
        """
        Extract function name from a call node.

        :param node: The function call node.
        :returns: Function name as string or None.
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None


class FunctionFinder(ast.NodeVisitor):
    """
    Find test functions in a module (including methods in test classes).

    :param test_functions: Dictionary of test function names to AST nodes.
    :param test_classes: Dictionary of test class names to AST nodes.
    :param target_test: Optional target test name to filter.
    :param current_class: Current class being visited.
    """

    def __init__(self, target_test: Optional[str] = None):
        # Dictionary to store test functions
        self.test_functions: dict[str, ast.FunctionDef] = {}
        # Dictionary to store test classes
        self.test_classes: dict[str, ast.ClassDef] = {}
        # Optional target test to filter
        self.target_test = target_test
        # Current class context
        self.current_class = None

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definitions to find test classes."""
        # Save the current class context
        old_class = self.current_class
        # Any class can contain test methods, not just those starting with "Test"
        self.current_class = node
        # Store the class
        self.test_classes[node.name] = node

        # Visit children (test methods inside the class)
        self.generic_visit(node)

        # Restore previous class context
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function definitions (including methods)."""
        # Check if it's a test function
        if node.name.startswith("test_"):
            if self.target_test is None or node.name == self.target_test:
                # Store the test function
                self.test_functions[node.name] = node
                # Store reference to parent class if inside a class
                if self.current_class is not None:
                    node._parent_class = self.current_class

                # Check for pytest.mark.parametrize decorator
                param_info = None
                for decorator in node.decorator_list:
                    param_info = ParameterizeFinder.extract_parametrize_info(decorator)
                    if param_info:
                        break
                # Store parametrize info on the node
                node._parametrize_info = param_info

        # Continue visiting children
        self.generic_visit(node)


class AssertionAtomizer(ast.NodeTransformer):
    """
    Transform a test function to neutralize non-target assertions while preserving side effects.

    - Non-target `assert` statements are wrapped in try-except to prevent failures
      while preserving any side effects from function calls in the assertion
    - Non-target assertion method calls (like self.assertEqual) are also wrapped in try-except
    - This ensures line numbers are preserved and test state remains consistent
    - The target assertion runs normally and can fail if it should

    Handles both module-level functions and class methods.

    :param target_assertion_line: Line number of the target assertion.
    :param in_target_function: Flag indicating if we're in the target function.
    :param in_class: Flag indicating if we're in a class.
    """

    def __init__(self, target_assertion_line: int):
        # Line number of the target assertion
        self.target_assertion_line = target_assertion_line
        # Flag for being in the target function
        self.in_target_function = False
        # Flag for being in a class
        self.in_class = False

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definitions."""
        # Any class can contain test methods
        self.in_class = True
        # Visit children
        node = self.generic_visit(node)
        self.in_class = False
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function definitions."""
        # Check if it's a test function
        if node.name.startswith("test_"):
            # Enter the target function
            self.in_target_function = True
            # Visit children
            node = self.generic_visit(node)
            # Exit the target function
            self.in_target_function = False
            return node
        # Keep non-test methods in classes (like setup_method, teardown_method)
        elif self.in_class:
            return self.generic_visit(node)
        return node

    def visit_Assert(self, node: ast.Assert):
        """Wrap non-target assertions in try-except to preserve side effects and prevent failures."""
        if self.in_target_function and node.lineno != self.target_assertion_line:
            # Wrap in try-except to preserve side effects while preventing failure
            # try:
            #     assert condition
            # except:
            #     pass
            try_node = ast.Try(
                body=[node],
                handlers=[
                    ast.ExceptHandler(
                        type=None,  # Catch all exceptions
                        name=None,
                        body=[ast.Pass()],
                    )
                ],
                orelse=[],
                finalbody=[],
            )
            return ast.copy_location(try_node, node)
        return node

    def visit_Expr(self, node: ast.Expr):
        """Wrap non-target assertion method calls in try-except to prevent failures."""
        if self.in_target_function and isinstance(node.value, ast.Call):
            func_name = self._get_func_name(node.value.func)
            if func_name and "assert" in func_name.lower():
                if node.lineno != self.target_assertion_line:
                    # Assertion method calls (like self.assertEqual) need to be wrapped
                    # in try-except to prevent them from failing the test
                    # This preserves any side effects in the arguments
                    try_node = ast.Try(
                        body=[node],
                        handlers=[
                            ast.ExceptHandler(
                                type=None,  # Catch all exceptions
                                name=None,
                                body=[ast.Pass()],
                            )
                        ],
                        orelse=[],
                        finalbody=[],
                    )
                    return ast.copy_location(try_node, node)
        return node

    @staticmethod
    def _get_func_name(node):
        """
        Extract function name from a call node.

        :param node: The function call node.
        :returns: Function name as string or None.
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None


class SingleAssertionExtractor(ast.NodeTransformer):
    """
    Extract a single assertion from a test function.
    This creates a clean test with only one assertion (no try-except).
    Handles both module-level functions and class methods.
    REMOVES all other test functions to keep only the target test.

    :param target_test_name: Name of the target test function.
    :param target_assertion_line: Line number of the target assertion.
    :param target_class_name: Optional name of the containing class.
    :param in_target_function: Flag indicating if we're in the target function.
    :param found_target: Flag indicating if the target assertion was found.
    :param current_class_name: Name of the current class being visited.
    """

    def __init__(
        self,
        target_test_name: str,
        target_assertion_line: int,
        target_class_name: Optional[str] = None,
    ):
        # Name of the target test function
        self.target_test_name = target_test_name
        # Line number of the target assertion
        self.target_assertion_line = target_assertion_line
        # Optional class name
        self.target_class_name = target_class_name
        # Flag for being in the target function
        self.in_target_function = False
        # Flag for finding the target
        self.found_target = False
        # Current class name
        self.current_class_name = None

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definitions and preserve them."""
        # Any class can contain test methods
        old_class_name = self.current_class_name
        self.current_class_name = node.name
        # Visit children
        self.generic_visit(node)
        self.current_class_name = old_class_name
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function definitions."""
        # Check if it's a test function
        if node.name.startswith("test_"):
            # This is a test function
            if (
                self.target_class_name
                and self.current_class_name != self.target_class_name
            ):
                # This is a test function outside the target class
                return None
            if node.name == self.target_test_name:
                # This is the target test in the correct class (or no class filter)
                self.in_target_function = True
                self.found_target = False
                # Visit the body to find and process the target assertion
                new_body = []
                for stmt in node.body:
                    # If we already found the target, stop processing
                    if self.found_target:
                        break
                    # Visit the statement to find assertions (including nested ones)
                    new_stmt = self.visit(stmt)
                    if new_stmt is not None:
                        new_body.append(new_stmt)

                node.body = new_body if new_body else [ast.Pass()]
                self.in_target_function = False
                return node
            else:
                # This is NOT the target test - remove it completely
                return None
        # Keep non-test module-level functions (helpers, fixtures, etc.)
        return node

    def visit_Assert(self, node: ast.Assert):
        """Visit assert statements."""
        if self.in_target_function:
            if node.lineno == self.target_assertion_line:
                # This is the target assertion - keep it
                self.found_target = True
                return node
            else:
                # This is not the target assertion - remove it
                return None
        return node

    def visit_Expr(self, node: ast.Expr):
        """Visit expression statements (for assertion method calls like self.assertEqual)."""
        if self.in_target_function and isinstance(node.value, ast.Call):
            func_name = self._get_func_name(node.value.func)
            if func_name and "assert" in func_name.lower():
                # This is an assertion method call
                if node.lineno == self.target_assertion_line:
                    # This is the target assertion - keep it
                    self.found_target = True
                    return node
                else:
                    # This is not the target assertion - remove it
                    return None
        # Not an assertion, keep it
        return self.generic_visit(node) if self.in_target_function else node

    @staticmethod
    def _get_func_name(node):
        """
        Extract function name from a call node.

        :param node: The function call node.
        :returns: Function name as string or None.
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None


# NOTE: ParameterReplacer is no longer used. We now keep parameterized tests as-is
# and include the parameter suffix in the test pattern when running tests.
# This is simpler and more reliable than trying to de-parameterize tests.
#
# class ParameterReplacer(ast.NodeTransformer):
#     """
#     Replace parameter references with concrete values in a de-parameterized test.
#     Also removes the @pytest.mark.parametrize decorator.
#     """
#     ... (implementation commented out)


# ============================================================================
# Phase 2: Test Case Slicing
# ============================================================================


# ============================================================================
# Phase 3: Rank Refinement
# ============================================================================


def rank_refinement(
    original_scores: dict[str, float],
    purified_spectra: list[dict[str, bool]],
    technique: str = "combined",
) -> dict[str, float]:
    """
    Refine rankings based on purified test spectra.

    :param original_scores: Dictionary mapping statements to suspiciousness scores.
    :param purified_spectra: List of spectra (dicts mapping statements to coverage bools).
    :param technique: "combined", "ratio_only", or "original_only".
    :returns: Dictionary mapping statements to refined scores.
    """
    if not original_scores:
        return {}

    # Remove duplicate spectra
    unique_spectra = []
    seen = set()
    for spectrum in purified_spectra:
        # Convert to frozen set for hashing
        spectrum_key = frozenset(
            (k, v) for k, v in spectrum.items() if k in original_scores
        )
        if spectrum_key not in seen:
            seen.add(spectrum_key)
            unique_spectra.append(spectrum)

    # Calculate ratio for each statement
    ratios = {}
    num_tests = len(unique_spectra)

    for stmt in original_scores:
        if num_tests == 0:
            ratios[stmt] = 0.0
        else:
            covered = sum(1 for spec in unique_spectra if spec.get(stmt, False))
            ratios[stmt] = covered / num_tests

    # Normalize original scores to [0, 1]
    scores = list(original_scores.values())
    min_score = min(scores) if scores else 0
    max_score = max(scores) if scores else 1
    score_range = max_score - min_score

    normalized = {}
    for stmt, score in original_scores.items():
        if score_range == 0:
            normalized[stmt] = 0.5
        else:
            normalized[stmt] = (score - min_score) / score_range

    # Compute final scores based on technique
    refined = {}
    for stmt in original_scores:
        if technique == "ratio_only":
            refined[stmt] = ratios[stmt]
        elif technique == "original_only":
            refined[stmt] = normalized[stmt]
        else:  # combined
            # score(s) = norm(s) × (1 + ratio(s)) / 2
            refined[stmt] = normalized[stmt] * (1 + ratios[stmt]) / 2

    return refined


# ============================================================================
# Complete Pipeline
# ============================================================================


def _resolve_test_file_path(test_base: Path, test_file_rel: str) -> Path:
    """
    Resolve the actual test file path, handling overlapping paths.

    Examples:
        test_base='tmp/cookiecutter_2/tests', test_file_rel='tests/test_hooks.py'
        -> 'tmp/cookiecutter_2/tests/test_hooks.py'

        test_base='tmp/cookiecutter_2/tests', test_file_rel='test_hooks.py'
        -> 'tmp/cookiecutter_2/tests/test_hooks.py'

        test_base='tmp/cookiecutter_2', test_file_rel='tests/test_hooks.py'
        -> 'tmp/cookiecutter_2/tests/test_hooks.py'

        test_base='tmp/cookiecutter_2/tests/t', test_file_rel='t/test_hooks.py'
        -> 'tmp/cookiecutter_2/tests/t/test_hooks.py'

    :param test_base: Base directory for tests.
    :param test_file_rel: Relative test file path from test identifier.
    :returns: Resolved absolute path to test file.
    """
    test_base = Path(test_base)
    # Fix: If test_base is a file, use its parent directory
    if test_base.is_file():
        test_base = test_base.parent
    test_file_rel = Path(test_file_rel)

    # Try direct concatenation first
    candidate = test_base / test_file_rel
    if candidate.exists():
        return candidate

    # Handle overlapping paths by finding common suffix/prefix
    # Convert to parts for comparison
    base_parts = test_base.parts
    rel_parts = test_file_rel.parts

    # Check if test_file_rel starts with any suffix of test_base
    # e.g., test_base='tmp/cookiecutter_2/tests', test_file_rel='tests/test_hooks.py'
    # Should match on 'tests' and use 'test_hooks.py'
    best_candidate = None
    for i in range(len(base_parts)):
        base_suffix = base_parts[i:]

        # Check if rel_parts starts with this suffix
        if len(rel_parts) > len(base_suffix):
            if rel_parts[: len(base_suffix)] == base_suffix:
                # Found overlap, use the non-overlapping part
                remaining_parts = rel_parts[len(base_suffix) :]
                candidate = test_base / Path(*remaining_parts)
                # Prefer this candidate (whether it exists or not) since we found overlap
                best_candidate = candidate
                if candidate.exists():
                    return candidate

    # If we found an overlap candidate (even if file doesn't exist yet), use it
    if best_candidate:
        return best_candidate

    # If no overlap found, just concatenate
    return test_base / test_file_rel


def _remove_other_test_functions(
    original_code: str,
    test_name: str,
    class_name: Optional[str] = None,
) -> str:
    """
    Remove other test functions from code while keeping the target test.

    This is used when slicing is not available/fails, but we still want to
    remove unnecessary test functions from the file.

    :param original_code: Original test code.
    :param test_name: Name of the test function to keep.
    :param class_name: Optional name of the class containing the test.
    :returns: Code with only the target test function (and necessary imports/fixtures).
    """
    tree = ast.parse(original_code)

    # Use TestFunctionFilter to remove other test functions
    filtered_tree = TestFunctionFilter(test_name, class_name).visit(tree)

    # Unparse and return
    return ast.unparse(filtered_tree)


def _build_sliced_code(
    original_code: str,
    relevant_lines: Set[int],
    test_name: str,
    class_name: Optional[str] = None,
) -> str:
    """
    Build sliced code from original code and relevant lines.

    This function uses AST-based filtering to preserve syntactic correctness
    while removing irrelevant statements.

    :param original_code: Original test code.
    :param relevant_lines: Set of relevant line numbers (from slicer).
    :param test_name: Name of the test function.
    :param class_name: Optional name of the class containing the test.
    :returns: Sliced code as a string.
    """
    tree = ast.parse(original_code)

    # Use StatementFilter to remove irrelevant statements
    filtered_tree = StatementFilter(relevant_lines, test_name, class_name).visit(tree)

    # Unparse and return
    return ast.unparse(filtered_tree)


class TestFunctionFilter(ast.NodeTransformer):
    """
    Filter AST to keep only the target test function while removing other test functions.

    This is used when slicing is not available but we still want to remove
    unnecessary test functions. Unlike StatementFilter, this does NOT filter
    statements within the test function.

    :param test_name: Name of the target test function.
    :param class_name: Optional name of the containing class.
    :param in_target_class: Flag indicating if we're in the target class.
    """

    def __init__(self, test_name: str, class_name: Optional[str] = None):
        # Name of the target test function
        self.test_name = test_name
        # Optional class name
        self.class_name = class_name
        # Flag for being in the target class
        self.in_target_class = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Optional[ast.FunctionDef]:
        """Visit function definitions."""
        if node.name == self.test_name:
            # This is our test function
            return node
        elif node.name.startswith("test_"):
            return None
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> Optional[ast.AsyncFunctionDef]:
        """Visit async function definitions."""
        if node.name == self.test_name:
            return node
        elif node.name.startswith("test_"):
            return None
        return node


class StatementFilter(ast.NodeTransformer):
    """
    Filter AST to keep only relevant statements based on the line numbers.

    This ensures the sliced code remains syntactically valid by:
    - Keeping function/class definitions that contain relevant statements
    - Keeping import statements (they're usually needed)
    - Removing statements not in the relevant set

    :param relevant_lines: Set of relevant line numbers.
    :param test_name: Name of the test function.
    :param class_name: Optional name of the containing class.
    :param in_target_test: Flag indicating if we're in the target test.
    """

    def __init__(
        self, relevant_lines: Set[int], test_name: str, class_name: Optional[str] = None
    ):
        # Set of relevant line numbers
        self.relevant_lines = relevant_lines
        # Name of the test function
        self.test_name = test_name
        # Optional class name
        self.class_name = class_name
        # Flag for being in the target test
        self.in_target_test = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Optional[ast.FunctionDef]:
        """Visit function definitions."""
        if node.name == self.test_name:
            # This is our test function, filter its body
            self.in_target_test = True
            node.body = self._filter_statements(node.body)
            self.in_target_test = False
            return node
        elif not self.in_target_test and node.name.startswith("test_"):
            return None
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> Optional[ast.AsyncFunctionDef]:
        """Visit async function definitions."""
        if node.name == self.test_name:
            # This is our test function, filter its body
            self.in_target_test = True
            node.body = self._filter_statements(node.body)
            self.in_target_test = False
            return node
        elif not self.in_target_test and node.name.startswith("test_"):
            return None
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> Optional[ast.ClassDef]:
        """Visit class definitions - keep if it's the target class or has relevant content."""
        if self._has_relevant_lines(node):
            # Keep the class and filter its contents
            # noinspection PyTypeChecker
            node = self.generic_visit(node)
            if hasattr(node, "body") and not node.body:
                node.body = [ast.Pass()]
            # noinspection PyTypeChecker
            return node
        return None

    def visit_Import(self, node: ast.Import) -> ast.Import:
        """Always keep import statements."""
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        """Always keep import statements."""
        return node

    def _filter_statements(self, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Filter a list of statements to keep only relevant ones."""
        filtered = []
        for stmt in stmts:
            if self._is_relevant(stmt):
                # For compound statements (if, for, while, etc.),
                # recursively filter their bodies
                if isinstance(stmt, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                    stmt.body = self._filter_statements(stmt.body)
                    if hasattr(stmt, "orelse") and stmt.orelse:
                        stmt.orelse = self._filter_statements(stmt.orelse)
                elif isinstance(stmt, ast.With):
                    stmt.body = self._filter_statements(stmt.body)
                elif isinstance(stmt, ast.Try):
                    stmt.body = self._filter_statements(stmt.body)
                    stmt.handlers = [self._filter_handler(h) for h in stmt.handlers]
                    if hasattr(stmt, "orelse") and stmt.orelse:
                        stmt.orelse = self._filter_statements(stmt.orelse)
                    if hasattr(stmt, "finalbody") and stmt.finalbody:
                        stmt.finalbody = self._filter_statements(stmt.finalbody)

                filtered.append(stmt)

        # If no statements remain, add a pass statement to keep syntax valid
        if not filtered:
            filtered.append(ast.Pass())

        return filtered

    def _filter_handler(self, handler: ast.ExceptHandler) -> ast.ExceptHandler:
        """Filter exception handler body."""
        handler.body = self._filter_statements(handler.body)
        return handler

    def _is_relevant(self, node: ast.AST) -> bool:
        """Check if a node is relevant based on its line number."""
        if not hasattr(node, "lineno"):
            return True  # Keep nodes without line numbers (e.g., arguments)

        # Check if this node's line is in the relevant set
        # noinspection PyUnresolvedReferences
        if node.lineno in self.relevant_lines:
            return True

        # For compound statements, check if any child lines are relevant
        if isinstance(
            node, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.Try)
        ):
            return self._has_relevant_lines(node)

        return False

    def _has_relevant_lines(self, node: ast.AST) -> bool:
        """Check if a node or any of its children have relevant lines."""
        if self.in_target_test:
            for child in ast.walk(node):
                # noinspection PyUnresolvedReferences
                if hasattr(child, "lineno") and child.lineno in self.relevant_lines:
                    return True
            return False
        return True


def _install_and_verify_packages(venv_python: str, venv: dict[str, str]):
    """
    Check if required pytest plugins are installed in the venv and install if not.

    :param venv_python: Path to Python executable in virtual environment.
    :param venv: Environment variables for subprocess.
    """
    # Check if required pytest plugins are installed in the venv and install if not
    if venv_python is None:
        venv_python = "python"
    # get actual python
    result = subprocess.run(
        [venv_python, "-c", "import sys; print(sys.executable)"],
        capture_output=True,
        text=True,
        env=venv,
    )
    if result.returncode != 0:
        LOGGER.error(
            f"Failed to get python executable in virtual environment: {result.stderr}"
        )
        raise RuntimeError("Failed to get python executable in virtual environment")
    venv_python = result.stdout.strip()
    # Check if pytest is installed
    result = subprocess.run(
        [venv_python, "-m", "pytest", "--help"],
        capture_output=True,
        text=True,
        env=venv,
    )
    if result.returncode != 0:
        LOGGER.info("pytest not found in virtual environment, installing...")
        # Install pytest
        install_result = subprocess.run(
            [
                venv_python,
                "-m",
                "pip",
                "install",
                "pytest",
                "--upgrade-strategy",
                "only-if-needed",
            ],
            capture_output=True,
            text=True,
            env=venv,
        )
        if install_result.returncode != 0:
            LOGGER.error(f"Failed to install pytest: {install_result.stderr}")
            raise RuntimeError(
                "Failed to install required packages in virtual environment"
            )
        LOGGER.info("Successfully installed pytest")
        return venv_python
    return venv_python


def purify_tests(
    src_dir: Path,
    dst_dir: Path,
    failing_tests: List[str],
    enable_slicing: bool = False,
    test_base: Optional[Path] = None,
    venv_python: str = None,
    venv: Optional[dict] = None,
) -> Dict[str, List[tuple[Path, Optional[str]]]]:
    """
    Purify failing tests.

    :param src_dir: Source directory containing tests.
    :param dst_dir: Destination directory for purified tests.
    :param failing_tests: List of failing test identifiers (e.g., "test_file.py::test_name[params]").
    :param enable_slicing: Whether to enable dynamic slicing.
    :param test_base: Base directory for tests (defaults to src_dir if None).
    :param venv_python: Path to virtual environment Python (defaults to sys.executable).
    :param venv: Environment variables for subprocesses (defaults to os.environ).
    :returns: Dictionary mapping test identifiers to lists of (purified_file, param_suffix) tuples.
        For parameterized tests, param_suffix contains the parameter values (e.g., "param1-param2").
        For non-parameterized tests, param_suffix is None.
    """
    if venv is None:
        venv_python = sys.executable
    venv = venv or os.environ.copy()

    venv_python = _install_and_verify_packages(venv_python, venv)

    # If test_base is not provided, use src_dir
    if test_base is None:
        test_base = src_dir

    # Create destination directory
    shutil.rmtree(dst_dir, ignore_errors=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    result = {}

    deactivate_tests: dict[str, tuple[ast.AST, list[tuple[Optional[str], str]]]] = {}
    successfully_purified: dict[str, set[tuple[Optional[str], str]]] = (
        {}
    )  # Track which tests were purified

    for test_id in failing_tests:
        # Parse test identifier
        # Format can be:
        #   - file::test_function (2 parts - module-level function)
        #   - file::TestClass::test_method (3 parts - class method)
        #   - file::test_function[param] (2 parts with parameters)
        #   - file::TestClass::test_method[param] (3 parts with parameters)

        # Extract parameter suffix if present (e.g., [1-hello])
        param_suffix = None
        test_id_base = test_id
        if "[" in test_id and test_id.endswith("]"):
            bracket_pos = test_id.rfind("[")
            param_suffix = test_id[bracket_pos + 1 : -1]  # Extract content between [ ]
            test_id_base = test_id[:bracket_pos]  # Remove parameter part

        parts = test_id_base.split("::")
        if len(parts) < 2:
            continue

        # test_file_rel should be relative to test_base
        # e.g., if test_base=/project/tests and test_id=tests/test_foo.py::test_bar
        # then test_file_rel should be "test_foo.py" not "tests/test_foo.py"
        # to avoid copying to dst_dir/tests/test_foo.py when dst_dir already points to tests/
        test_file_rel = parts[0]

        # Determine if this is a class method or module-level function
        if len(parts) == 3:
            # Class method: file::class::method
            class_name = parts[1]
            test_name = parts[2]
            test_pattern = f"{class_name}::{test_name}"
        elif len(parts) == 2:
            # Module-level function: file::function
            class_name = None
            test_name = parts[1]
            test_pattern = test_name
        else:
            # Unknown format, skip
            continue

        if param_suffix is not None:
            test_pattern += f"[{param_suffix}]"
        # Resolve the actual test file path
        # Handle overlapping paths between test_base and test_file_rel
        test_file = _resolve_test_file_path(test_base, test_file_rel)

        if not test_file.exists():
            continue

        # Compute the path relative to test_base for proper copying
        # This ensures we don't get double nesting (e.g., tests/tests/test.py)
        try:
            test_file_rel_to_base = test_file.relative_to(test_base)
        except ValueError:
            # If test_file is not under test_base, use the original test_file_rel
            test_file_rel_to_base = Path(test_file_rel)

        # Read the test file
        with open(test_file) as f:
            source = f.read()
            tree = ast.parse(source)

        # Use the normalized relative path as the key
        test_file_key = str(test_file_rel_to_base)
        if test_file_key not in deactivate_tests:
            deactivate_tests[test_file_key] = (tree, [(class_name, test_name)])
        else:
            deactivate_tests[test_file_key][1].append((class_name, test_name))

        # Find the test function (handles both module-level and class methods)
        finder = FunctionFinder(target_test=test_name)
        finder.visit(tree)

        if test_name not in finder.test_functions:
            continue

        test_func = finder.test_functions[test_name]

        # Check if the test is in the expected class (if class_name is specified)
        if class_name:
            # Verify the test function is inside the expected class
            parent_class = getattr(test_func, "_parent_class", None)
            if parent_class is None or parent_class.name != class_name:
                continue

        # Check if test is parameterized
        param_info = getattr(test_func, "_parametrize_info", None)
        param_values_dict = {}

        if param_info and param_suffix:
            # Parse parameter values from suffix
            # Format can be: "1-hello" for two parameters, or just "1" for one parameter
            param_values_list = param_suffix.split("-")

            # Try to match parameter values
            if len(param_values_list) == len(param_info.param_names):
                for i, param_name in enumerate(param_info.param_names):
                    value_str = param_values_list[i]
                    # Try to convert to appropriate type
                    try:
                        # Try int first
                        param_values_dict[param_name] = int(value_str)
                    except ValueError:
                        # Keep as string
                        param_values_dict[param_name] = value_str

        # Find all assertions
        assertion_finder = AssertionFinder()
        assertion_finder.visit(test_func)

        if not assertion_finder.assertions:
            continue

        # Phase 1: Atomization - Create atomized tests and check which fail
        atomized_tests = _find_failing_assertions(
            test_file,
            assertion_finder.assertions,
            test_pattern,
            src_dir,
            venv_python,
            venv,
        )

        # Phase 2: Process each atomized test (optionally apply slicing)
        purified_files = []

        for assertion_line, atomized_test in atomized_tests.items():
            # Start with atomized code (has correct line numbers)
            code = atomized_test.code

            # Apply slicing if enabled
            if enable_slicing:
                # Write atomized test to temporary file IN THE SAME DIRECTORY
                # This is critical so tests can find relative resources
                # Use absolute path to avoid issues with subprocess cwd
                import uuid

                tmp_filename = f"tmp_slice_{uuid.uuid4().hex[:8]}_{test_file.name}"
                tmp_path = (test_file.parent / tmp_filename).resolve()  # Absolute path
                tmp_path.write_text(code)

                try:
                    # Use PytestSlicer to perform dynamic slicing
                    # IMPORTANT: tmp_path contains the ATOMIZED test code
                    # This ensures the slicer/tracer analyzes the version with:
                    # - Try-except wrapped non-target assertions
                    # - Preserved line numbers matching the original file
                    # - Correct side effects
                    #
                    # Use failing_line for slicing since that's where the test actually fails
                    # (could be the assertion itself or a line before it)
                    slice_target_line = atomized_test.failing_line
                    LOGGER.info(
                        f"Slicing {test_name} at line {slice_target_line} "
                        f"(assertion at line {assertion_line})"
                    )
                    slicer = PytestSlicer(
                        tmp_path,
                        python_executable=venv_python,
                        env=venv,
                        base_dir=src_dir,
                    )

                    # Perform slicing using the failing line
                    slice_results = slicer.slice_test(
                        test_pattern=test_pattern,
                        target_line=slice_target_line,
                    )

                    # Extract sliced code from results
                    if slice_target_line in slice_results.get("slices", {}):
                        relevant_lines = set(
                            slice_results["slices"][slice_target_line]["relevant_lines"]
                        )
                        sliced_code = _build_sliced_code(
                            code, relevant_lines, test_name, class_name
                        )
                    else:
                        LOGGER.warning(
                            f"No slice found for line {slice_target_line}, "
                            "removing other test functions but keeping atomized code"
                        )
                        # Even without slicing, remove other test functions
                        sliced_code = _remove_other_test_functions(
                            code, test_name, class_name
                        )
                except Exception as e:
                    LOGGER.error(f"Error during slicing: {e}")
                    # On error, still remove other test functions
                    sliced_code = _remove_other_test_functions(
                        code, test_name, class_name
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                # Slicing not enabled, but still remove other test functions
                sliced_code = _remove_other_test_functions(code, test_name, class_name)

            # Create purified test file
            # Note: We keep parameterized tests as-is (don't replace parameters)
            # Each parameter combination gets its own file because they may behave differently:
            # - Different assertions may fail
            # - Different execution paths
            # - Different slicing results
            if param_suffix:
                # Include parameter suffix in filename for clarity
                purified_name = (
                    safe_name(
                        f"{test_file.stem}_{test_name}_{param_suffix}"
                        f"_assertion_{assertion_line}"
                    )
                    + f"{test_file.suffix}"
                )
            else:
                purified_name = (
                    safe_name(
                        f"{test_file.stem}_{test_name}_assertion_{assertion_line}"
                    )
                    + f"{test_file.suffix}"
                )

            # Preserve subdirectory structure from original test file
            # e.g., if test_file_key = "t/test_a.py", purified file goes in dst_dir/t/
            test_subdir = Path(test_file_key).parent
            purified_path = dst_dir / test_subdir / purified_name

            # Ensure subdirectory exists
            purified_path.parent.mkdir(parents=True, exist_ok=True)
            purified_path.write_text(sliced_code)

            # Store with test pattern that includes parameter suffix if present
            purified_files.append((purified_path, param_suffix))

        # Mark this test as successfully purified if we created purified files
        if purified_files:
            # Map original test_id to list of (purified_file, param_suffix) tuples
            # This preserves the parameter information for later test execution
            result[test_id] = purified_files
            # Track that this test was successfully purified
            if test_file_key not in successfully_purified:
                successfully_purified[test_file_key] = set()
            successfully_purified[test_file_key].add((class_name, test_name))
        else:
            # Test couldn't be purified - map to original file (will be copied without disabling)
            dst_test_file = dst_dir / test_file_key
            # Store as tuple for consistency (file, param_suffix)
            result[test_id] = [(dst_test_file, param_suffix)]

    # Copy original test files and handle disabling
    for test_file_rel, (tree, tests) in deactivate_tests.items():
        dst_test_file = dst_dir / test_file_rel
        dst_test_file.parent.mkdir(parents=True, exist_ok=True)

        # Determine which tests should be disabled (only those successfully purified)
        tests_to_disable = []
        if test_file_rel in successfully_purified:
            purified_tests = successfully_purified[test_file_rel]
            # Only disable tests that were successfully purified
            tests_to_disable = [test for test in tests if test in purified_tests]

        if tests_to_disable:
            # Disable only the successfully purified tests
            disabler = TestDisabler(tests_to_disable)
            disabled_tree = disabler.visit(tree)
            dst_test_file.write_text(ast.unparse(disabled_tree))
        else:
            # No tests to disable - copy original file as-is
            dst_test_file.write_text(ast.unparse(tree))

    return result


def _extract_failing_line_from_junit_xml(
    junit_xml_path: Path, test_file_path: Path, assertions: list[tuple[int, ast.AST]]
) -> Optional[int]:
    """
    Extract the actual failing line number from pytest JUnit XML report.

    Parses the JUnit XML report to find the line IN THE TEST FILE where the failure occurred.
    If the crash happens in another module, we trace back to find the line in the test
    file that called into that module.

    For multi-line assertions, maps the failing line to the assertion's start line.

    :param junit_xml_path: Path to the JUnit XML report file.
    :param test_file_path: Path to the test file (to filter traceback entries).
    :param assertions: List of (line_number, ast_node) tuples for assertions in original file.
    :returns: Line number (start line) of the failing assertion, or None if not found.
    """

    try:
        tree = ET.parse(junit_xml_path)
        root = tree.getroot()

        for testcase in root.iter("testcase"):
            failure = testcase.find("failure")
            error = testcase.find("error")
            failure_elem = failure if failure is not None else error
            if failure_elem is None:
                continue

            # Try to extract from traceback in message/text (old logic)
            message = failure_elem.get("message", "")
            traceback_text = failure_elem.text or ""
            test_filename = test_file_path.name
            full_text = message + "\n" + traceback_text
            test_file_lines = []
            for line in full_text.split("\n"):
                match = re.search(rf"{re.escape(test_filename)}:(\d+)", line)
                if match:
                    test_file_lines.append(int(match.group(1)))
            if test_file_lines:
                failing_line = test_file_lines[-1]
                return _map_to_assertion_start_line(failing_line, assertions)

            # Fallback: use the line attribute from testcase if file matches
            testcase_file = testcase.get("file")
            testcase_line = testcase.get("line")
            if testcase_file and testcase_line:
                if Path(testcase_file).name == test_filename:
                    return int(testcase_line)

        return None
    except (
        FileNotFoundError,
        ET.ParseError,
        KeyError,
        ValueError,
        AttributeError,
    ):
        return None


def _map_to_assertion_start_line(
    failing_line: int, assertions: list[tuple[int, ast.AST]]
) -> int:
    """
    Map a failing line to the start line of the assertion that contains it.

    This handles multi-line assertions where the failure might occur on any line
    within the assertion, but we need to return the start line for comparison.

    :param failing_line: The line number where the failure occurred.
    :param assertions: List of (start_line, ast_node) tuples.
    :returns: The start line of the assertion containing the failing line, or the failing_line itself.
    """
    for assertion_start, assertion_node in assertions:
        # Get the end line of this assertion
        if hasattr(assertion_node, "end_lineno") and assertion_node.end_lineno:
            assertion_end = assertion_node.end_lineno
        else:
            assertion_end = assertion_start

        # Check if failing_line is within this assertion's range
        if assertion_start <= failing_line <= assertion_end:
            return assertion_start

    # If not found in any assertion range, return the failing line as-is
    # (it might be a non-assertion failure like a function call)
    return failing_line


def _find_failing_assertions(
    test_file: Path,
    assertions: list[tuple[int, ast.AST]],
    test_pattern: str,
    src_dir: Path,
    venv_python: str = "python",
    venv: Optional[dict] = None,
) -> dict[int, AtomizedTest]:
    """
    Find which assertions actually fail and create atomized tests for them.

    Returns atomized tests (with try-except wrapped non-target assertions) that preserve:
    - Original line numbers
    - Side effects from all assertions
    - Ability to run and detect which assertion fails

    :param test_file: Path to the original test file.
    :param assertions: List of (line_number, ast_node) tuples for assertions.
    :param test_pattern: Pytest pattern for the specific test (e.g., "TestClass::test_method").
    :param src_dir: Source directory for running tests.
    :param venv_python: Path to Python executable.
    :param venv: Environment variables for subprocess.
    :returns: Dictionary mapping assertion line numbers to AtomizedTest objects.
        Key = assertion_line (the target assertion being tested)
        Value = AtomizedTest (contains code, assertion_line, failing_line, etc.)
    """
    atomized_tests = {}
    venv = venv or os.environ.copy()

    with open(test_file) as f:
        source = f.read()

    for assertion_line, _ in assertions:
        # Create atomized version (wrap other assertions in try-except)
        atomizer = AssertionAtomizer(assertion_line)
        atomized_tree = atomizer.visit(ast.parse(source))
        atomized_code = ast.unparse(atomized_tree)

        # Write to temp file IN THE SAME DIRECTORY as test file
        # This is critical so tests can find relative resources (data files, configs, etc.)
        # Use absolute paths to avoid issues with subprocess cwd
        import uuid

        tmp_filename = f"tmp_atomized_{uuid.uuid4().hex[:8]}_{test_file.name}"
        tmp_path = (test_file.parent / tmp_filename).resolve()  # Absolute path
        tmp_path.write_text(atomized_code)

        # Create temp file for JUnit XML report (can be anywhere, use absolute path)
        junit_xml_filename = f"tmp_report_{uuid.uuid4().hex[:8]}.xml"
        junit_xml_path = (
            test_file.parent / junit_xml_filename
        ).resolve()  # Absolute path

        try:
            # Run only the specific test with pytest and generate JUnit XML report
            # Use absolute path for test selector
            test_selector = f"{tmp_path}::{test_pattern}"

            result = subprocess.run(
                [
                    venv_python,
                    "-m",
                    "pytest",
                    test_selector,
                    "-q",
                    f"--junitxml={junit_xml_path}",
                ],
                capture_output=True,
                text=True,
                cwd=src_dir,
                env=venv,
            )

            # If test fails, this assertion is failing - create AtomizedTest
            if result.returncode != 0:
                actual_failing_line = _extract_failing_line_from_junit_xml(
                    junit_xml_path, tmp_path, assertions
                )
                if actual_failing_line:
                    # Create AtomizedTest object with the code and line numbers
                    # assertion_line is the target assertion we're testing
                    # failing_line is where the failure actually occurred
                    # Extract test name and class name from test_pattern
                    if "::" in test_pattern:
                        parts = test_pattern.split("::")
                        if len(parts) == 2:
                            class_name, test_name = parts[0], parts[1]
                        else:
                            class_name, test_name = None, parts[0]
                    else:
                        class_name, test_name = None, test_pattern

                    atomized_test = AtomizedTest(
                        code=atomized_code,
                        assertion_line=assertion_line,  # Target assertion line
                        test_name=test_name,
                        class_name=class_name,
                        failing_line=actual_failing_line,  # Actual failure line
                    )
                    # Key by the target assertion line (what we're testing)
                    atomized_tests[assertion_line] = atomized_test
        finally:
            # Clean up temp files
            tmp_path.unlink(missing_ok=True)
            junit_xml_path.unlink(missing_ok=True)

    # If we couldn't determine any failing assertions, create atomized tests for all
    if not atomized_tests:
        for assertion_line, _ in assertions:
            atomizer = AssertionAtomizer(assertion_line)
            atomized_tree = atomizer.visit(ast.parse(source))
            atomized_code = ast.unparse(atomized_tree)

            # Extract test name and class name from test_pattern
            if "::" in test_pattern:
                parts = test_pattern.split("::")
                if len(parts) == 2:
                    class_name, test_name = parts[0], parts[1]
                else:
                    class_name, test_name = None, parts[0]
            else:
                class_name, test_name = None, test_pattern

            atomized_test = AtomizedTest(
                code=atomized_code,
                assertion_line=assertion_line,
                test_name=test_name,
                class_name=class_name,
            )
            atomized_tests[assertion_line] = atomized_test

    return atomized_tests


class TestDisabler(ast.NodeTransformer):
    """
    Rename a test function to disable it (handles both module-level and class methods).

    :param tests: List of (class_name, test_name) tuples to disable.
    :param current_class: Name of the current class being visited.
    """

    def __init__(self, tests: list[tuple[Optional[str], str]]):
        # List of tests to disable
        self.tests = tests
        # Current class context
        self.current_class = None

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definitions."""
        # Check if this class matches any target class in tests
        old_name = self.current_class
        self.current_class = node.name
        node = self.generic_visit(node)
        self.current_class = old_name
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Rename the test function."""
        # If we're looking for a class method, only rename inside the target class
        for class_name, test_name in self.tests:
            if node.name == test_name:
                if class_name is None or class_name == self.current_class:
                    node.name = f"disabled_{node.name}"
                    break
        return node
