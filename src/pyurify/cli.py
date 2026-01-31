#!/usr/bin/env python3
"""
Command-line Interface for Test Case Purification

This module provides the command-line interface (CLI) for the Pyurify tool.

The CLI allows users to interact with the Pyurify library to purify test cases
and perform related operations.

Functions:
- main: Entry point for the CLI.

Usage:
    pyurify --help
"""

import argparse
import sys
from pathlib import Path

from pyurify.logger import LOGGER, debug


def main(args: list[str] | None = None) -> int:
    """
    Main entry point for the CLI.

    Parses command-line arguments and invokes the test purification process.
    :param args: Optional list of command-line arguments.
    :returns: Exit code (0 for success, non-zero for failure).
    """
    # Create the argument parser
    parser = argparse.ArgumentParser(
        description="TCP: Test Case Purification for Improving Fault Localization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic purification with slicing
  pyurify --src-dir tests/ --dst-dir purified/ \\
      --failing-tests "test_math.py::test_add"
  
  # With dynamic slicing disabled
  pyurify --src-dir tests/ --dst-dir purified/ \\
      --failing-tests "test_math.py::test_add" \\
      --disable-slicing
  
  # Multiple failing tests
  pyurify --src-dir tests/ --dst-dir purified/ \\
      --failing-tests "test_math.py::test_add" "test_math.py::test_subtract"
  
  # With custom Python executable
  pyurify --src-dir tests/ --dst-dir purified/ \\
      --failing-tests "test_math.py::test_add" \\
      --python /path/to/venv/bin/python
        """,
    )

    # Add source directory argument
    parser.add_argument(
        "-s",
        "--src-dir",
        type=Path,
        required=True,
        help="Source directory containing test files",
    )

    # Add destination directory argument
    parser.add_argument(
        "-d",
        "--dst-dir",
        type=Path,
        required=True,
        help="Destination directory for purified tests",
    )

    # Add failing tests argument
    parser.add_argument(
        "-f",
        "--failing-tests",
        nargs="+",
        required=True,
        help="List of failing test identifiers (e.g., test_file.py::test_name)",
    )

    # Add slicing option
    parser.add_argument(
        "--disable-slicing",
        default=False,
        action="store_true",
        help="Enable dynamic slicing to remove irrelevant code",
    )

    # Add test base directory argument
    parser.add_argument(
        "--test-base", type=Path, help="Base directory for tests (defaults to src-dir)"
    )

    # Add Python executable argument
    parser.add_argument(
        "--python",
        default="python",
        help="Path to Python executable for running tests (default: python)",
    )

    # Add verbose option
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )

    # Parse the arguments
    args = parser.parse_args(args or sys.argv[1:])

    # Import here to avoid circular imports
    from pyurify import purify_tests

    # Configure logging if verbose
    if args.verbose:
        debug()

    # Validate paths
    if not args.src_dir.exists():
        LOGGER.error(f"Source directory does not exist: {args.src_dir}")
        return 1

    # Create destination directory
    args.dst_dir.mkdir(parents=True, exist_ok=True)

    # Run purification
    LOGGER.info(f"Purifying tests from {args.src_dir} to {args.dst_dir}")
    LOGGER.info(f"Failing tests: {', '.join(args.failing_tests)}")
    LOGGER.info(f"Slicing enabled: {not args.disable_slicing}")

    try:
        # Call the purify_tests function
        result = purify_tests(
            src_dir=args.src_dir,
            dst_dir=args.dst_dir,
            failing_tests=args.failing_tests,
            enable_slicing=not args.disable_slicing,
            test_base=args.test_base,
            venv_python=args.python,
        )

        # Print results
        total_purified = 0
        for test_id, file_param_tuples in result.items():
            LOGGER.info(f"Test {test_id}")
            # NEW: Unpack tuples (file, param_suffix)
            for purified_file, param_suffix in file_param_tuples:
                rel_path = purified_file.relative_to(args.dst_dir)
                if param_suffix:
                    LOGGER.info(f"  purified in {rel_path} [params: {param_suffix}]")
                else:
                    LOGGER.info(f"  purified in {rel_path}")
                total_purified += 1

        LOGGER.info(
            f"Successfully purified {len(result)} test(s) into {total_purified} file(s)"
        )
        LOGGER.info(f"Output directory: {args.dst_dir}")
        return 0

    except Exception as e:
        # Handle errors
        LOGGER.error(f"Error during purification: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
