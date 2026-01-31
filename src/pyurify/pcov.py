"""
Coverage Tracking for Test Cases

This module provides a tracer for tracking line coverage during test execution.
It writes coverage data to a file for further analysis.

Functions:
- main: Entry point for the coverage tracker.
"""

import json
import os
import runpy
import sys
from typing import List, Optional

DEFAULT_COVERAGE_FILENAME = ".tcpcov"
ENV_VAR = "TCP_COVERAGE_FILE"


def main(args: Optional[List[str]] = None):
    """
    Main entry point for the coverage tracker.

    :param args: Command-line arguments for the script.
    :returns: None
    """
    # Parse command-line arguments
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--src",
        type=str,
        default=None,
        help="Set to track coverage of a specific source file (basename only).",
    )
    # Use parse_known_args to allow -m and other options for the target
    parsed, script_args = parser.parse_known_args(args)

    # Extract the source basename
    src_basename = parsed.src
    if not script_args:
        print("No script or module specified to run.", file=sys.stderr)
        sys.exit(1)

    # Prepare coverage data storage
    covered = set()

    def tracer(frame, event, arg):
        """
        Trace function to record executed lines.

        :param frame: The current stack frame.
        :param event: The event type (e.g., 'line').
        :param arg: Additional arguments for the event.
        :returns: The tracer function itself.
        """
        # Check if the event is a line execution
        if event != "line":
            return tracer
        # Get the filename and line number from the frame
        f_filename = frame.f_code.co_filename
        f_lineno = frame.f_lineno
        # If a source basename is specified, only track that file
        if src_basename:
            if os.path.basename(f_filename) == src_basename:
                covered.add((f_filename, f_lineno))
        else:
            # Track all files
            covered.add((f_filename, f_lineno))
        return tracer

    # Set the trace function
    sys.settrace(tracer)

    # Prepare sys.argv for the script/module
    sys.argv = script_args
    try:
        # Check if running as a module
        if script_args[0] == "-m":
            # Run as module
            if len(script_args) < 2:
                print("No module specified after -m.", file=sys.stderr)
                sys.exit(1)
            module_name = script_args[1]
            sys.argv = [module_name] + script_args[2:]
            runpy.run_module(module_name, run_name="__main__")
        else:
            # Run as script
            script_path = script_args[0]
            sys.argv = [script_path] + script_args[1:]
            runpy.run_path(script_path, run_name="__main__")
    finally:
        # Stop tracing
        sys.settrace(None)
        # Write coverage data
        covdata = {}
        for filename, lineno in covered:
            covdata.setdefault(filename, []).append(lineno)
        with open(os.environ.get(ENV_VAR, DEFAULT_COVERAGE_FILENAME), "w") as f:
            json.dump(covdata, f)


if __name__ == "__main__":
    main()
