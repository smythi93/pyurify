# TCP: Test Case Purification for Improving Fault Localization

A Python package for purifying test cases to improve fault localization effectiveness through test case atomization and dynamic program slicing.

## Features

- **Test Case Atomization**: Automatically splits tests with multiple assertions into single-assertion tests
- **Dynamic Slicing**: Removes irrelevant code from tests using execution tracing and dependency analysis
- **Command-Line Interface**: Easy-to-use CLI for quick purification
- **Python API**: Programmatic access for integration into fault localization pipelines

## Installation

```bash
# Install from source
cd test-purification
pip install -e .

# Or with test dependencies
pip install -e ".[test]"
```

## Quick Start

### Command Line

```bash
# Basic purification (atomization only)
tcp --src-dir tests/ --dst-dir purified/ \
    --failing-tests "test_math.py::test_add"

# With dynamic slicing enabled
tcp --src-dir tests/ --dst-dir purified/ \
    --failing-tests "test_math.py::test_add" \
    --enable-slicing

# Multiple tests
tcp --src-dir tests/ --dst-dir purified/ \
    --failing-tests "test_math.py::test_add" "test_math.py::test_subtract" \
    --enable-slicing
```

### Python API

```python
from pathlib import Path
from tcp import purify_tests

# Purify tests
result = purify_tests(
    src_dir=Path("tests"),
    dst_dir=Path("purified"),
    failing_tests=["test_math.py::test_add"],
    enable_slicing=True,
)

# Check results
for test_id, purified_files in result.items():
    print(f"{test_id}: {len(purified_files)} purified file(s)")
```

## How It Works

### 1. Test Case Atomization

Splits tests with multiple assertions into separate tests:

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
# test_math_assertion_5.py
def test_math():
    x = 1
    y = 2
    z = x + y
    assert z == 3

# test_math_assertion_6.py  
def test_math():
    x = 1
    y = 2
    z = x + y
    assert x == 1
```

### 2. Dynamic Slicing (Optional)

Removes code not relevant to each assertion:

**With Slicing:**
```python
# test_math_assertion_5.py
def test_math():
    x = 1
    y = 2
    z = x + y
    assert z == 3

# test_math_assertion_6.py  
def test_math():
    x = 1
    # y and z removed - not needed for this assertion
    assert x == 1
```

## CLI Options

```
--src-dir PATH           Source directory containing tests (required)
--dst-dir PATH           Destination for purified tests (required)
--failing-tests TEST...  Space-separated test identifiers (required)
--enable-slicing         Enable dynamic slicing
--test-base PATH         Base directory for tests (default: src-dir)
--python PATH            Python executable (default: python)
--verbose, -v            Enable verbose output
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
    venv_python: str = "python",
    venv: Optional[dict] = None,
) -> Dict[str, List[Path]]
```

**Parameters:**
- `src_dir`: Source directory containing test files
- `dst_dir`: Destination directory for purified tests
- `failing_tests`: List of test identifiers (e.g., `["test.py::test_func"]`)
- `enable_slicing`: Whether to apply dynamic slicing (default: False)
- `test_base`: Base directory for tests (default: src_dir)
- `venv_python`: Python executable path (default: "python")
- `venv`: Environment variables dict (default: os.environ)

**Returns:**
- Dict mapping test IDs to lists of purified test file paths

### PytestSlicer

```python
from tcp import PytestSlicer

slicer = PytestSlicer(test_file_path)
results = slicer.slice_test("test.py::test_func", target_line=10)
```

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=tcp --cov-report=html

# Run specific test
pytest tests/test_purification.py -v
```

### Code Formatting

```bash
# Format code
black src/tcp tests/

# Check formatting
black --check src/tcp tests/
```

## Use Cases

- **Fault Localization**: Improve FL accuracy by focusing on relevant code
- **Test Debugging**: Isolate failing assertions for easier debugging  
- **Test Optimization**: Reduce test code size and execution time
- **Research**: Study test behavior and dependencies

## Requirements

- Python 3.10+
- pytest 8.3+

## License

MIT License - see LICENSE file for details.
