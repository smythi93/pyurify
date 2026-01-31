"""
Dynamic Slicer for Python Test Code

This module implements dynamic slicing using execution tracing and dependency tracking.
It builds a dynamic dependency graph from actual test execution and can slice test code
to include only statements relevant to specific assertions.

Usage:
    python -m pwfl_eval.slicer pytest test.py
    python -m pwfl_eval.slicer pytest test.py::test_function
    python -m pwfl_eval.slicer pytest test.py::TestClass::test_method
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import coverage
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional, Any

from tcp.logger import LOGGER


@dataclass
class Variable:
    """Represents a variable in the program."""

    name: str
    scope: str  # function name or 'global'

    def __hash__(self):
        return hash((self.name, self.scope))

    def __eq__(self, other):
        return (
            isinstance(other, Variable)
            and self.name == other.name
            and self.scope == other.scope
        )


@dataclass
class Statement:
    """Represents a statement with its dependencies."""

    line: int
    code: str
    defines: Set[Variable] = field(default_factory=set)
    uses: Set[Variable] = field(default_factory=set)
    control_deps: Set[int] = field(
        default_factory=set
    )  # lines this depends on for control flow

    def __hash__(self):
        return hash(self.line)


@dataclass
class DependencyGraph:
    """Dynamic dependency graph built from execution trace."""

    statements: Dict[int, Statement] = field(default_factory=dict)
    data_deps: Dict[int, Set[int]] = field(
        default_factory=lambda: defaultdict(set)
    )  # line -> lines it depends on
    control_deps: Dict[int, Set[int]] = field(default_factory=lambda: defaultdict(set))
    executed_lines: Set[int] = field(default_factory=set)

    def add_statement(self, stmt: Statement):
        """Add a statement to the graph."""
        self.statements[stmt.line] = stmt

    def add_data_dependency(self, from_line: int, to_line: int):
        """Add data dependency: from_line depends on to_line."""
        self.data_deps[from_line].add(to_line)

    def add_control_dependency(self, from_line: int, to_line: int):
        """Add control dependency: from_line depends on to_line."""
        self.control_deps[from_line].add(to_line)

    def get_dependencies(self, line: int) -> Set[int]:
        """Get all dependencies (data + control) for a line."""
        return self.data_deps[line] | self.control_deps[line]

    def backward_slice(self, target_line: int) -> Set[int]:
        """
        Compute backward slice for target line.
        Returns set of all lines that influence the target.
        """
        relevant = {target_line}
        worklist = [target_line]

        while worklist:
            line = worklist.pop()
            deps = self.get_dependencies(line)

            for dep in deps:
                if dep not in relevant and dep in self.executed_lines:
                    relevant.add(dep)
                    worklist.append(dep)

        return relevant

    def to_dict(self) -> dict:
        """Export graph as dictionary."""
        return {
            "statements": {
                line: {
                    "code": stmt.code,
                    "defines": [
                        {"name": v.name, "scope": v.scope} for v in stmt.defines
                    ],
                    "uses": [{"name": v.name, "scope": v.scope} for v in stmt.uses],
                }
                for line, stmt in self.statements.items()
            },
            "data_dependencies": {k: list(v) for k, v in self.data_deps.items()},
            "control_dependencies": {k: list(v) for k, v in self.control_deps.items()},
            "executed_lines": list(self.executed_lines),
        }


class VariableTracker(ast.NodeVisitor):
    """
    Static AST visitor to track variable definitions and uses.
    This is STATIC ANALYSIS - done once before tracing, not during execution.

    Simplified approach: just check ast.Store vs ast.Load context on Name nodes.
    No need for separate visit methods for each assignment type!
    """

    def __init__(self):
        self.current_scope = "global"
        self.events = []

    def visit_FunctionDef(self, node):
        """Track function scope changes."""
        old_scope = self.current_scope
        self.current_scope = node.name
        self.generic_visit(node)
        self.current_scope = old_scope

    def visit_AsyncFunctionDef(self, node):
        """Track async function scope changes."""
        old_scope = self.current_scope
        self.current_scope = node.name
        self.generic_visit(node)
        self.current_scope = old_scope

    def visit_Attribute(self, node):
        """Track attribute scope changes."""
        if isinstance(node.ctx, ast.Store):
            self.events.append(
                (node.lineno, "def", ast.unparse(node), self.current_scope)
            )
        elif isinstance(node.ctx, ast.Load):
            self.events.append(
                (node.lineno, "use", ast.unparse(node), self.current_scope)
            )
        self.generic_visit(node)

    def visit_Name(self, node):
        """
        Track all variable accesses based on context.
        - ast.Store: variable is being assigned/defined
        - ast.Load: variable is being read/used
        """
        if isinstance(node.ctx, ast.Store):
            self.events.append((node.lineno, "def", node.id, self.current_scope))
        elif isinstance(node.ctx, ast.Load):
            self.events.append((node.lineno, "use", node.id, self.current_scope))


class DynamicTracer:
    """Traces test execution to build dynamic dependency graph."""

    def __init__(
        self,
        test_file: Path,
        python_executable: str = None,
        env: Optional[Dict[str, str]] = None,
        base_dir: Optional[Path] = None,
    ):
        self.test_file = test_file
        self.base_dir = base_dir or test_file.parent  # Default to test file directory
        self.graph = DependencyGraph()
        self.python_executable = python_executable or sys.executable
        self.env = env
        self.var_definitions: Dict[Variable, int] = (
            {}
        )  # variable -> line where last defined
        self.current_scope = "global"
        self.control_stack: List[int] = []  # stack of controlling conditions

    def trace_execution(self, test_pattern: Optional[str] = None) -> DependencyGraph:
        """
        Execute tests with coverage tracking and build dependency graph.

        Uses pytest-cov to collect coverage data via subprocess (supports venv).

        This performs DYNAMIC ANALYSIS (runtime):
        - Which lines were actually executed (via coverage.py)

        STATIC ANALYSIS is done BEFORE tracing:
        - Variable definitions/uses (from AST)
        - Control dependencies (from AST)

        Args:
            test_pattern: Optional pytest pattern (e.g., "test.py::test_func")
        """
        LOGGER.info(f"Analyzing test file: {self.test_file}")

        # STATIC ANALYSIS - Parse AST once before tracing
        with open(self.test_file) as f:
            source_code = f.read()
            tree = ast.parse(source_code)

        # Extract variable events (static)
        LOGGER.debug("Extracting variable definitions and uses (static analysis)")
        tracker = VariableTracker()
        tracker.visit(tree)
        variable_events = tracker.events
        LOGGER.debug(f"Found {len(variable_events)} variable events")

        # Run pytest with coverage via subprocess (DYNAMIC ANALYSIS)
        # Create coverage data file in SAME DIRECTORY as test file
        # This ensures coverage.py can properly resolve paths
        import uuid

        coverage_filename = f"tmp_coverage_{uuid.uuid4().hex[:8]}"
        coverage_data_file = (self.test_file.parent / coverage_filename).resolve()

        try:
            # Build pytest command with coverage
            # Use absolute path for test file to avoid path resolution issues
            test_file_abs = self.test_file.resolve()

            # Get absolute path for tcpcov file
            tcpcov_py = Path(__file__).parent.absolute() / "tcpcov.py"

            cmd = [
                self.python_executable,
                str(tcpcov_py),
                f"--src={self.test_file.name}",
                "-m",
                "pytest",
                (
                    f"{test_file_abs}::{test_pattern}"
                    if test_pattern
                    else str(test_file_abs)
                ),  # Use absolute path
                "-q",
            ]

            # Set coverage data file location
            env = (self.env or {}).copy()
            env["TCP_COVERAGE_FILE"] = str(coverage_data_file)

            try:
                LOGGER.debug(f"Running coverage: {test_pattern or 'all tests'}")
                LOGGER.debug(f"Working directory: {self.base_dir}")
                LOGGER.debug(f"Test file: {test_file_abs}")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                    cwd=self.base_dir,  # Execute from base directory
                )
                LOGGER.debug(f"Coverage collection completed (rc={result.returncode})")
                if result.returncode != 0:
                    LOGGER.debug(f"stderr: {result.stderr}")
            except subprocess.TimeoutExpired:
                LOGGER.error("Coverage collection timed out")
                raise
            except Exception as e:
                LOGGER.error(f"Coverage collection failed: {e}")
                raise

            # Parse coverage data to get executed lines
            try:
                executed_lines = self._parse_coverage_data(coverage_data_file)
                LOGGER.debug(f"Captured {len(executed_lines)} executed lines")

                trace_data = {"executed_lines": sorted(executed_lines)}
                self._build_graph_from_trace(trace_data, variable_events, source_code)
            except Exception as e:
                LOGGER.error(f"Failed to parse coverage data: {e}")
                raise
        finally:
            # Clean up coverage data file
            coverage_data_file.unlink(missing_ok=True)

        # Add control dependencies (static analysis)
        LOGGER.debug("Adding control dependencies (static analysis)")
        self._add_control_dependencies()
        LOGGER.info(
            f"Dependency graph built: {len(self.graph.statements)} statements, "
            f"{len(self.graph.executed_lines)} executed lines"
        )

        return self.graph

    def _parse_coverage_data(self, coverage_file: Path) -> Set[int]:
        """
        Parse coverage.py data file to extract executed lines.

        Args:
            coverage_file: Path to .coverage data file

        Returns:
            Set of executed line numbers for the test file
        """
        if not coverage_file.exists():
            LOGGER.warning(f"Coverage file not found: {coverage_file}")
            return set()

        try:
            with open(coverage_file) as f:
                data = json.load(f)

            for file in data:
                # Match only the filename instead of the entire path
                if Path(file).name == self.test_file.name:
                    return set(data[file])

            LOGGER.warning("Coverage data for test file not found in coverage file")
            return set()
        except Exception as e:
            LOGGER.error(f"Failed to parse coverage data: {e}")
            return set()

    def _build_graph_from_trace(
        self, trace_data: Dict, variable_events: List[Tuple], source_code: str
    ):
        """
        Build dependency graph from trace data and static variable analysis.

        Args:
            trace_data: Dynamic trace data (executed lines)
            variable_events: Static variable analysis (from AST)
            source_code: Source code of the test file
        """
        source_lines = source_code.splitlines()

        # Mark executed lines (DYNAMIC)
        for line in trace_data["executed_lines"]:
            self.graph.executed_lines.add(line)

        # Build statements with variable info (combining STATIC and DYNAMIC)
        var_events_by_line = defaultdict(list)
        for line, event_type, var_name, scope in variable_events:
            var_events_by_line[line].append((event_type, var_name, scope))

        # Create statements for executed lines
        for line in trace_data["executed_lines"]:
            if 0 <= line - 1 < len(source_lines):
                code = source_lines[line - 1].strip()
                stmt = Statement(line=line, code=code)

                # Add variable info from static analysis
                if line in var_events_by_line:
                    for event_type, var_name, scope in var_events_by_line[line]:
                        var = Variable(var_name, scope)
                        if event_type == "def":
                            stmt.defines.add(var)
                            # Track where variable was defined
                            self.var_definitions[var] = line
                        elif event_type == "use":
                            stmt.uses.add(var)
                            # Add data dependency if variable was previously defined
                            if var in self.var_definitions:
                                def_line = self.var_definitions[var]
                                self.graph.add_data_dependency(line, def_line)

                self.graph.add_statement(stmt)

    def _add_control_dependencies(self):
        """
        Add control dependencies by analyzing code structure.
        This is STATIC ANALYSIS - done once at analysis time, not during execution.
        Much more efficient than doing it at runtime.
        """
        with open(self.test_file) as f:
            tree = ast.parse(f.read())

        # Visit AST to find control structures
        visitor = ControlFlowVisitor(self.graph)
        visitor.visit(tree)


class ControlFlowVisitor(ast.NodeVisitor):
    """Visitor to add control dependencies to the graph."""

    def __init__(self, graph: DependencyGraph):
        self.graph = graph
        self.control_stack: List[int] = []

    def visit_If(self, node: ast.If):
        """Add control dependencies for if statements."""
        control_line = node.lineno
        self.control_stack.append(control_line)

        # All statements in body depend on the condition
        for stmt in ast.walk(node):
            if hasattr(stmt, "lineno") and stmt.lineno != control_line:
                self.graph.add_control_dependency(stmt.lineno, control_line)

        self.generic_visit(node)
        self.control_stack.pop()

    def visit_For(self, node: ast.For):
        """Add control dependencies for for loops."""
        control_line = node.lineno
        self.control_stack.append(control_line)

        for stmt in ast.walk(node):
            if hasattr(stmt, "lineno") and stmt.lineno != control_line:
                self.graph.add_control_dependency(stmt.lineno, control_line)

        self.generic_visit(node)
        self.control_stack.pop()

    def visit_While(self, node: ast.While):
        """Add control dependencies for while loops."""
        control_line = node.lineno
        self.control_stack.append(control_line)

        for stmt in ast.walk(node):
            if hasattr(stmt, "lineno") and stmt.lineno != control_line:
                self.graph.add_control_dependency(stmt.lineno, control_line)

        self.generic_visit(node)
        self.control_stack.pop()

    def visit_With(self, node: ast.With):
        """Add control dependencies for with statements."""
        control_line = node.lineno
        self.control_stack.append(control_line)

        for stmt in ast.walk(node):
            if hasattr(stmt, "lineno") and stmt.lineno != control_line:
                self.graph.add_control_dependency(stmt.lineno, control_line)

        self.generic_visit(node)
        self.control_stack.pop()


class PytestSlicer:
    """
    Slices test code based on assertions.

    The test_file parameter can be:
    - Original test file (when used standalone)
    - Atomized test file (when used from purification pipeline)

    When used with atomized tests, the line numbers in the results
    correspond to the original test file since atomization preserves
    line numbers.
    """

    def __init__(
        self,
        test_file: Path,
        python_executable: str = None,
        env: Optional[Dict[str, str]] = None,
        base_dir: Optional[Path] = None,
    ):
        self.test_file = test_file
        self.base_dir = base_dir or test_file.parent  # Default to test file directory
        self.tracer = DynamicTracer(test_file, python_executable, env, base_dir)

    def slice_test(
        self, test_pattern: Optional[str] = None, target_line: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Slice a test to find dependencies.

        Args:
            test_pattern: pytest pattern for specific test
            target_line: specific line to slice (e.g., assertion line)

        Returns:
            Dictionary with slice results
        """
        # Build dependency graph
        LOGGER.info(
            f"Slicing test: {self.test_file}{'::' + test_pattern if test_pattern else ''}"
        )
        graph = self.tracer.trace_execution(test_pattern)

        # Find assertion lines if not specified
        if target_line is None:
            target_lines = self._find_assertions(graph)
        else:
            target_lines = [target_line]

        results = {
            "test_file": str(self.test_file),
            "test_pattern": test_pattern,
            "graph": graph.to_dict(),
            "slices": {},
        }

        # Compute slice for each assertion
        for line in target_lines:
            if line in graph.executed_lines:
                relevant_lines = graph.backward_slice(line)
                results["slices"][line] = {
                    "target": line,
                    "code": (
                        graph.statements[line].code if line in graph.statements else ""
                    ),
                    "relevant_lines": sorted(relevant_lines),
                    "sliced_code": self._extract_sliced_code(relevant_lines),
                }

        return results

    def _find_assertions(self, graph: DependencyGraph) -> List[int]:
        """Find assertion lines in executed code."""
        assertions = []
        for line, stmt in graph.statements.items():
            if "assert" in stmt.code.lower():
                assertions.append(line)
        return assertions

    def _extract_sliced_code(self, relevant_lines: Set[int]) -> str:
        """Extract code for relevant lines."""
        with open(self.test_file) as f:
            source_lines = f.readlines()

        sliced = []
        for i, line in enumerate(source_lines, 1):
            if i in relevant_lines:
                sliced.append(f"{i:4d}: {line.rstrip()}")

        return "\n".join(sliced)
