import json
import os
import runpy
import sys
from typing import List, Optional

DEFAULT_COVERAGE_FILENAME = ".tcpcov"
ENV_VAR = "TCP_COVERAGE_FILE"


def main(args: Optional[List[str]] = None):
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

    src_basename = parsed.src
    if not script_args:
        print("No script or module specified to run.", file=sys.stderr)
        sys.exit(1)

    # Prepare coverage data storage
    covered = set()

    def tracer(frame, event, arg):
        if event != "line":
            return tracer
        f_filename = frame.f_code.co_filename
        f_lineno = frame.f_lineno
        if src_basename:
            if os.path.basename(f_filename) == src_basename:
                covered.add((f_filename, f_lineno))
        else:
            covered.add((f_filename, f_lineno))
        return tracer

    sys.settrace(tracer)

    # Prepare sys.argv for the script/module
    sys.argv = script_args
    try:
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
        sys.settrace(None)
        # Write coverage data
        covdata = {}
        for filename, lineno in covered:
            covdata.setdefault(filename, []).append(lineno)
        with open(os.environ.get(ENV_VAR, DEFAULT_COVERAGE_FILENAME), "w") as f:
            json.dump(covdata, f)


if __name__ == "__main__":
    main()
