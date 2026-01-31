# Pyurify: Purifying Python Tests for Precise Fault Localization

[![Python Version](https://img.shields.io/pypi/pyversions/pyurify)](https://pypi.org/project/pyurify/)
[![PyPI](https://img.shields.io/pypi/v/pyurify)](https://pypi.org/project/pyurify/)
[![Build Status](https://img.shields.io/github/actions/workflow/status/smythi93/pyurify/test-pyurify.yml?branch=main)](https://img.shields.io/github/actions/workflow/status/smythi93/pyurify/test-pyurify.yml?branch=main)
[![Coverage Status](https://coveralls.io/repos/github/smythi93/pyurify/badge.svg?branch=main)](https://coveralls.io/github/smythi93/pyurify?branch=main)
[![Licence](https://img.shields.io/github/license/smythi93/pyurify)](https://img.shields.io/github/license/smythi93/pyurify)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A Python package for purifying test cases to improve fault localization effectiveness through test case atomization and dynamic program slicing.

## Features

- **Test Case Atomization**: Automatically splits tests with multiple assertions into single-assertion tests
- **Dynamic Slicing**: Removes irrelevant code from tests using execution tracing and dependency analysis
- **Command-Line Interface**: Easy-to-use CLI for quick purification
- **Python API**: Programmatic access for integration into fault localization pipelines

## Installation

```bash
# Install from PyPI (when published)
pip install pyurify

# Or install from source
git clone https://github.com/smythi93/pyurify.git
cd test-purification
pip install -e .

# With test dependencies
pip install -e ".[test]"
```

## Quick Start

### Command Line

```bash
# Basic purification with slicing (default)
pyurify --src-dir tests/ --dst-dir purified/ \
    --failing-tests "test_math.py::test_add"

# Disable dynamic slicing (atomization only)
pyurify --src-dir tests/ --dst-dir purified/ \
    --failing-tests "test_math.py::test_add" \
    --disable-slicing

# Multiple tests
pyurify --src-dir tests/ --dst-dir purified/ \
    --failing-tests "test_math.py::test_add" "test_math.py::test_subtract"
```

### Python API

```python
from pathlib import Path
from pyurify import purify_tests

# Purify tests
result = purify_tests(
    src_dir=Path("tests"),
    dst_dir=Path("purified"),
    failing_tests=["test_math.py::test_add"],
    enable_slicing=True,
)

# Check results
for test_id, file_param_tuples in result.items():
    print(f"{test_id}:")
    for purified_file, param_suffix in file_param_tuples:
        if param_suffix:
            print(f"  - {purified_file} [params: {param_suffix}]")
        else:
            print(f"  - {purified_file}")
```

## How It Works

### 1. Test Case Atomization

Splits tests with multiple assertions into separate tests. Each atomized test keeps one assertion active and wraps the others in try-except blocks to suppress them:

**Before:**
```python
def test_math():
    x = 1
    y = 2
    z = x + y
    assert z == 3
    assert x == 1
```

**After (2 files):**
```python
# test_math_assertion_5.py - First assertion active
def test_math():
    x = 1
    y = 2
    z = x + y
    assert z == 3
    try:
        assert x == 1
    except AssertionError:
        pass

# test_math_assertion_6.py - Second assertion active
def test_math():
    x = 1
    y = 2
    z = x + y
    try:
        assert z == 3
    except AssertionError:
        pass
    assert x == 1
```

### 2. Dynamic Slicing (Optional)

Removes code not relevant to each assertion. After atomization with try-except blocks, slicing further removes irrelevant statements:

**After Atomization:**
```python
# test_math_assertion_6.py
def test_math():
    x = 1
    y = 2
    z = x + y
    try:
        assert z == 3
    except AssertionError:
        pass
    assert x == 1
```

**After Slicing:**
```python
# test_math_assertion_6.py  
def test_math():
    x = 1
    # y, z, and first assertion removed - not needed for second assertion
    assert x == 1
```

## CLI Options

```
-s, --src-dir PATH           Source directory containing tests (required)
-d, --dst-dir PATH           Destination for purified tests (required)
-f, --failing-tests TEST...  Space-separated test identifiers (required)
--disable-slicing            Disable dynamic slicing (slicing enabled by default)
--test-base PATH             Base directory for tests (default: src-dir)
--python PATH                Python executable (default: python)
-v, --verbose                Enable verbose output
```

## API Reference

### purify_tests()

```python
def purify_tests(
    src_dir: Path,
    dst_dir: Path,
    failing_tests: List[str],
    enable_slicing: bool = False,
    test_base: Optional[Path] = None,
    venv_python: str = None,
    venv: Optional[dict] = None,
) -> Dict[str, List[tuple[Path, Optional[str]]]]
```

**Parameters:**
- `src_dir`: Source directory containing test files
- `dst_dir`: Destination directory for purified tests
- `failing_tests`: List of test identifiers (e.g., `["test.py::test_func"]`)
- `enable_slicing`: Whether to apply dynamic slicing (default: False)
- `test_base`: Base directory for tests (default: src_dir)
- `venv_python`: Python executable path (default: None, uses sys.executable)
- `venv`: Environment variables dict (default: None, uses os.environ)

**Returns:**
- Dict mapping test IDs to lists of (purified_file, param_suffix) tuples
- For parameterized tests, `param_suffix` contains parameter values
- For non-parameterized tests, `param_suffix` is None

### PytestSlicer

```python
from pathlib import Path
from pyurify import PytestSlicer

# Initialize slicer
slicer = PytestSlicer(
    test_file=Path("test.py"),
    python_executable="python",  # Optional
    env=None,  # Optional: environment variables
    base_dir=None,  # Optional: base directory
)

# Slice a test
results = slicer.slice_test(
    test_pattern="test_func",  # Optional: pytest pattern
    target_line=10  # Optional: specific line to slice
)

# Access results
print(f"Test file: {results['test_file']}")
print(f"Slices: {results['slices']}")
```

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=pyurify --cov-report=html

# Run specific test
pytest tests/test_purification.py -v
```

### Code Formatting

```bash
# Format code
black src/pyurify tests/

# Check formatting
black --check src/pyurify tests/
```

## Use Cases

- **Fault Localization**: Improve FL accuracy by focusing on relevant code
- **Test Debugging**: Isolate failing assertions for easier debugging  
- **Test Optimization**: Reduce test code size and execution time
- **Research**: Study test behavior and dependencies

## Requirements

- Python 3.10+
- pytest 9.0+ (for testing)

## License

Apache License 2.0 - see LICENSE file for details.

