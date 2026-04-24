# Operator Catalog Query Tool

Query Red Hat operator catalog indices for operator install modes. This tool extracts `installModes` from operator ClusterServiceVersions (CSVs) delivered via File-Based Catalog (FBC) format.

## Requirements

- Python 3.6+
- **podman** OR **skopeo** (automatically detects which is available)
  - For container environments: `dnf install -y skopeo` or `apt-get install -y skopeo`
  - For local development: `podman` works great
- Access to Red Hat registry (may require authentication)
- PyYAML (optional, for catalog.yaml format support): `pip install pyyaml`

## Container Environment Setup

If running in a container where podman is not available (common scenario):

```bash
# Install skopeo (Fedora/RHEL/CentOS)
dnf install -y skopeo

# Install skopeo (Debian/Ubuntu)
apt-get update && apt-get install -y skopeo

# Authenticate with Red Hat registry if needed
skopeo login registry.redhat.io
```

The tool will automatically detect and use skopeo when podman is not available.

## Usage Examples

### Basic Query

Query install modes for specific operators:

```bash
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --operators local-storage-operator,odf-operator
```

### Query with Channel and Version

Specify exact channel and version:

```bash
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --operators 'odf-operator:stable-4.11,acm:release-2.9:2.9.0'
```

### Query All Channels

Get install modes for all channels of an operator:

```bash
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --operators odf-operator \
    --all-channels
```

### Using a Config File

Create a config file `operators.txt`:

```
local-storage-operator
odf-operator:stable
# This is a comment
advanced-cluster-management:release-2.9:2.9.0
```

Then run:

```bash
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --config operators.txt
```

### JSON Output

Get machine-readable JSON output:

```bash
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --operators cluster-logging \
    -o json
```

### Force Specific Tool

Explicitly specify which container tool to use:

```bash
# Force skopeo (useful in container environments)
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --operators local-storage-operator \
    --tool skopeo

# Force podman (if you have it available)
./query_operator_catalog.py \
    --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \
    --operators local-storage-operator \
    --tool podman
```

## Operator Specification Format

Operators can be specified in the format: `name[:channel[:version]]`

- **name**: Operator package name (required)
- **channel**: Channel name (optional, uses defaultChannel if omitted)
- **version**: Bundle version (optional, uses latest if omitted)

Examples:
- `local-storage-operator` - Use default channel and latest version
- `odf-operator:stable` - Use stable channel, latest version
- `acm:release-2.9:2.9.0` - Use release-2.9 channel, version 2.9.0

## Supported Catalog Formats

The tool supports multiple File-Based Catalog (FBC) formats:

- `catalog.json` (concatenated NDJSON)
- `catalog.yaml` (YAML multi-document, requires PyYAML)
- `bundles/channels/package.json` (directory structure)
- `bundle-v*.json/channel.json/package.json` (versioned bundles)
- `bundles.json/channels.json/package.json` (concatenated JSON files)

## How It Works

1. **Extraction**: Downloads the catalog image using skopeo or podman
   - **skopeo**: Downloads to OCI format and extracts tar layers (no daemon required)
   - **podman**: Uses traditional container create/copy method
2. **Parsing**: Parses FBC objects from various format types
3. **Resolution**: Resolves package → channel → bundle hierarchy
4. **Extraction**: Extracts installModes from bundle CSV metadata

## Container-Friendly Design

The tool is designed to work in container environments where:
- No container daemon is running
- Podman is not available or cannot be installed
- Only lightweight tools like skopeo are available

The tool automatically detects which container tool is available and uses the most appropriate one, with preference for skopeo in restricted environments.

## Development

### Running Tests

This project includes comprehensive unit and integration tests to ensure reliability.

#### Install Test Dependencies

```bash
# Install test requirements
pip install -r requirements-test.txt

# Or use make
make install-test
```

#### Run Unit Tests

Unit tests are fast and don't require external dependencies:

```bash
# Using pytest directly
pytest test_query_operator_catalog.py -v

# Using make
make test

# With coverage report
make test-coverage
```

#### Run Integration Tests

Integration tests query real catalog images and require:
- Network access
- Container tool (skopeo or podman)
- Authentication to registries (if needed)

```bash
# Run integration tests
pytest test_integration.py -v --integration

# Or use make
make test-integration

# Set custom catalog for testing
TEST_CATALOG=registry.redhat.io/redhat/redhat-operator-index:v4.17 \
  pytest test_integration.py -v --integration

# Test specific operators
TEST_OPERATOR=local-storage-operator \
  pytest test_integration.py::TestRealCatalogExtraction::test_query_known_operator -v --integration
```

#### Test Coverage

Generate HTML coverage report:

```bash
make test-coverage
# Opens htmlcov/index.html in browser
```

#### Clean Test Artifacts

```bash
make clean
```

### Continuous Integration

To run tests in CI/CD pipelines:

```bash
# Install dependencies
pip install -r requirements-test.txt

# Run unit tests only (fast, no external dependencies)
pytest test_query_operator_catalog.py -v --tb=short

# Optionally run integration tests if catalog access available
pytest test_integration.py -v --integration || true
```

### Adding New Tests

When adding new features:

1. Add unit tests to `test_query_operator_catalog.py`
2. Add integration tests to `test_integration.py` if feature requires catalog access
3. Run `make test-coverage` to ensure good coverage
4. Run `make test-integration` to verify against real catalogs

Example test structure:

```python
def test_my_new_feature():
    """Test description"""
    # Arrange
    input_data = ...

    # Act
    result = my_function(input_data)

    # Assert
    assert result == expected_value
```

## Troubleshooting

### Authentication Required

If you get authentication errors:

```bash
# Using podman
podman login registry.redhat.io

# Using skopeo
skopeo login registry.redhat.io
```

### No Container Tool Available

If neither podman nor skopeo is available:

```
Error: No container tool available. Install skopeo or podman.
For container environments, skopeo is recommended: dnf install -y skopeo
```

Install skopeo as it's lightweight and doesn't require a container daemon.

### PyYAML Missing (for catalog.yaml format)

If you encounter errors about missing PyYAML when querying catalogs that use the YAML format:

```bash
pip install pyyaml
```

### Test Failures

If tests fail:

1. **Check dependencies**: Run `pip install -r requirements-test.txt`
2. **Check container tool**: Ensure skopeo or podman is installed
3. **Check authentication**: For integration tests, ensure you're logged into registries
4. **Run with verbose output**: Add `-vv` flag to pytest for detailed output
5. **Run specific test**: `pytest test_query_operator_catalog.py::TestClassName::test_name -v`
