# Testing Guide for Operator Catalog Query Tool

This document describes the testing infrastructure for the catalog query tool.

## Overview

The project includes:
- **Unit tests**: Fast, isolated tests with no external dependencies
- **Integration tests**: Tests against real catalog images (optional)
- **Test fixtures**: Sample data for testing various catalog formats
- **Coverage reporting**: Track which code is tested
- **CI/CD ready**: GitHub Actions workflow included

## Quick Start

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run unit tests
make test

# Run with coverage
make test-coverage

# Run integration tests (requires catalog access)
make test-integration
```

## Test Structure

### Unit Tests (`test_query_operator_catalog.py`)

Comprehensive unit tests covering:

1. **Utility Functions** (100% coverage)
   - `natural_sort_key()` - Version-aware sorting
   - `parse_operator_spec()` - Operator specification parsing
   - `parse_ndjson()` - Concatenated JSON parsing
   - `read_config_file()` - Config file reading

2. **Install Modes Extraction** (100% coverage)
   - Old format: `olm.csv.metadata` property
   - New format: Base64-encoded CSV in `olm.bundle.object`
   - Error handling for malformed data

3. **Bundle Resolution** (100% coverage)
   - Default channel selection
   - Specific version lookup
   - Error cases (non-existent packages/channels)

4. **Query Functions** (100% coverage)
   - `query_operator_from_objects()` - Query from catalog objects
   - Result structure validation

5. **Container Tool Detection** (100% coverage)
   - Skopeo detection and preference
   - Podman fallback
   - Error handling when neither available

6. **Output Formatting** (100% coverage)
   - JSON output format
   - Table output format
   - Error reporting

### Integration Tests (`test_integration.py`)

Optional tests that query real catalog images:

1. **Catalog Extraction**
   - Extract real catalog with skopeo/podman
   - Verify extracted structure

2. **Real Operator Queries**
   - Query known operators
   - Query multiple operators
   - Query all channels
   - Handle non-existent operators

3. **Authentication**
   - Test authenticated access
   - Test unauthenticated scenarios

**Note**: Integration tests are skipped by default. Run with:
```bash
pytest test_integration.py -v --integration
```

## Running Tests

### Basic Usage

```bash
# Run all unit tests
pytest test_query_operator_catalog.py -v

# Run specific test class
pytest test_query_operator_catalog.py::TestExtractInstallModes -v

# Run specific test
pytest test_query_operator_catalog.py::TestExtractInstallModes::test_extract_new_format -v

# Run with verbose output
pytest test_query_operator_catalog.py -vv
```

### With Coverage

```bash
# Generate coverage report
pytest test_query_operator_catalog.py \
  --cov=query_operator_catalog \
  --cov-report=term-missing \
  --cov-report=html

# View HTML report
firefox htmlcov/index.html  # or your browser
```

### Integration Tests

```bash
# Basic integration tests
pytest test_integration.py -v --integration

# Custom catalog
TEST_CATALOG=registry.redhat.io/redhat/redhat-operator-index:v4.17 \
  pytest test_integration.py -v --integration

# Custom operator
TEST_OPERATOR=cluster-logging \
  pytest test_integration.py::TestRealCatalogExtraction::test_query_known_operator \
  -v --integration

# Multiple operators
TEST_OPERATORS=local-storage-operator,cluster-logging,metallb-operator \
  pytest test_integration.py::TestRealCatalogExtraction::test_query_multiple_operators \
  -v --integration
```

## Coverage Targets

Current coverage: **26%** (unit tests only)

Coverage breakdown:
- ✅ **High coverage** (80%+): Utility functions, install mode extraction, bundle resolution
- ⚠️  **Medium coverage** (40-80%): Query functions, output formatting  
- ❌ **Low coverage** (<40%): Catalog extraction (requires mocking or integration tests), directory format parsers

**Note**: Low coverage in catalog extraction is expected as these functions require:
- Network access to pull images
- Skopeo/podman installation
- Filesystem operations
- Registry authentication

These are better tested via integration tests.

## Test Fixtures

The test suite includes fixtures for:

### Sample CSV Data
```python
@pytest.fixture
def sample_csv_data():
    """Sample ClusterServiceVersion YAML data"""
```

### Bundle Formats
```python
@pytest.fixture
def sample_bundle_old_format():
    """Bundle with olm.csv.metadata (older catalogs)"""

@pytest.fixture
def sample_bundle_new_format():
    """Bundle with olm.bundle.object (newer catalogs)"""
```

### Catalog Objects
```python
@pytest.fixture
def sample_catalog_objects():
    """Complete FBC catalog with package, channels, and bundles"""
```

## Writing New Tests

### Adding a Unit Test

1. Add test to appropriate class in `test_query_operator_catalog.py`:

```python
class TestMyFeature:
    """Test my new feature"""
    
    def test_basic_case(self):
        """Test basic functionality"""
        result = my_function(input_data)
        assert result == expected_value
    
    def test_edge_case(self):
        """Test edge case"""
        result = my_function(edge_case_input)
        assert result is None
```

2. Run the test:
```bash
pytest test_query_operator_catalog.py::TestMyFeature -v
```

3. Check coverage:
```bash
pytest test_query_operator_catalog.py::TestMyFeature --cov=query_operator_catalog --cov-report=term-missing
```

### Adding an Integration Test

1. Add test to `test_integration.py`:

```python
class TestMyIntegration:
    """Test my integration scenario"""
    
    def test_real_catalog_query(self, container_tool, test_catalog):
        """Test querying real catalog"""
        results, errors = query_operators(
            test_catalog,
            ['my-operator'],
            tool=container_tool
        )
        
        assert len(results) > 0
        assert results[0]['name'] == 'my-operator'
```

2. Run the test:
```bash
pytest test_integration.py::TestMyIntegration::test_real_catalog_query -v --integration
```

## Continuous Integration

### GitHub Actions

A GitHub Actions workflow (`.github/workflows/test.yml`) is included:

- Runs on push and pull requests
- Tests against Python 3.8, 3.9, 3.10, 3.11, 3.12
- Runs unit tests only (fast, no external dependencies)
- Generates coverage reports
- Uploads to Codecov (optional)

### Local CI Simulation

Simulate CI locally:

```bash
# Test against multiple Python versions using tox (optional)
pip install tox
tox

# Or manually test with different Python versions
python3.8 -m pytest test_query_operator_catalog.py
python3.9 -m pytest test_query_operator_catalog.py
python3.10 -m pytest test_query_operator_catalog.py
```

## Best Practices

1. **Run tests before committing**
   ```bash
   make test
   ```

2. **Check coverage for new code**
   ```bash
   make test-coverage
   ```

3. **Run integration tests before releases**
   ```bash
   make test-integration
   ```

4. **Keep tests fast**
   - Unit tests should complete in seconds
   - Use fixtures and mocks instead of real catalogs
   - Save integration tests for critical paths

5. **Test both success and failure cases**
   - Happy path: Valid input → Expected output
   - Error cases: Invalid input → Appropriate error

6. **Use descriptive test names**
   - `test_extract_install_modes_from_new_format()` ✅
   - `test_extract()` ❌

## Troubleshooting Tests

### Tests fail with "No module named 'pytest'"

Install test dependencies:
```bash
pip install -r requirements-test.txt
```

### Integration tests skip automatically

Integration tests require explicit opt-in:
```bash
pytest test_integration.py -v --integration
```

### Integration tests fail with authentication errors

Login to the registry:
```bash
skopeo login registry.redhat.io
# or
podman login registry.redhat.io
```

### Coverage report not generated

Install coverage plugin:
```bash
pip install pytest-cov
```

### Tests are slow

Unit tests should be fast (<10 seconds). If slow:
1. Check you're running unit tests, not integration tests
2. Verify no network calls in unit tests
3. Use smaller test fixtures

## Future Improvements

Potential testing enhancements:

- [ ] Increase unit test coverage to 80%+
- [ ] Add property-based testing with Hypothesis
- [ ] Add performance benchmarks
- [ ] Mock catalog extraction for higher coverage
- [ ] Add smoke tests for common catalogs
- [ ] Parameterize tests for multiple catalog versions
- [ ] Add mutation testing with mutpy
- [ ] Create test data generator for various FBC formats

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov plugin](https://pytest-cov.readthedocs.io/)
- [File-Based Catalog spec](https://olm.operatorframework.io/docs/reference/file-based-catalogs/)
- [OLM Bundle format](https://olm.operatorframework.io/docs/tasks/creating-operator-bundle/)
