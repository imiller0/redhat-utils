#!/usr/bin/env python3
"""
Integration tests for query_operator_catalog.py

These tests can be run against real catalog images if available.
They are skipped by default unless --integration flag is used.

Run with: pytest test_integration.py -v --integration
"""

import pytest
import os
import subprocess
import sys

# Add parent directory to path to import main module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from query_operator_catalog import (
    detect_container_tool,
    extract_catalog,
    query_operators,
    parse_operator_spec,
)


# Skip integration tests unless explicitly requested
pytestmark = pytest.mark.skipif(
    not pytest.config.getoption("--integration", default=False),
    reason="Integration tests require --integration flag"
)


def pytest_addoption(parser):
    """Add custom command line option"""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests against real catalog images"
    )


@pytest.fixture(scope="module")
def container_tool():
    """Check if a container tool is available"""
    tool = detect_container_tool()
    if not tool:
        pytest.skip("No container tool (skopeo or podman) available")
    return tool


@pytest.fixture(scope="module")
def test_catalog():
    """Catalog URL to use for testing"""
    # Use environment variable or default to a known catalog
    return os.getenv(
        'TEST_CATALOG',
        'registry.redhat.io/redhat/redhat-operator-index:v4.16'
    )


class TestRealCatalogExtraction:
    """Test extraction from real catalog images"""

    def test_detect_tool(self, container_tool):
        """Verify container tool detection works"""
        assert container_tool in ['skopeo', 'podman']

    def test_extract_catalog(self, container_tool, test_catalog):
        """Test extracting a real catalog"""
        # This will take time and requires network/auth
        temp_dir = extract_catalog(test_catalog, tool=container_tool)

        try:
            # Verify extraction worked
            configs_dir = os.path.join(temp_dir, 'configs')
            assert os.path.exists(configs_dir)
            assert os.path.isdir(configs_dir)

            # Check that some operators exist
            operators = os.listdir(configs_dir)
            assert len(operators) > 0

            print(f"Extracted {len(operators)} operators from catalog")

        finally:
            # Cleanup
            import shutil
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def test_query_known_operator(self, container_tool, test_catalog):
        """Test querying a known operator from real catalog"""
        # Use a well-known operator that should exist
        test_operator = os.getenv('TEST_OPERATOR', 'local-storage-operator')

        results, errors = query_operators(
            test_catalog,
            [test_operator],
            all_channels=False,
            tool=container_tool
        )

        # Should have results
        assert len(results) >= 1
        assert results[0]['name'] == test_operator
        assert 'installModes' in results[0]
        assert len(results[0]['installModes']) > 0

        # Should not have errors for this operator
        operator_errors = [e for e in errors if e['operator'] == test_operator]
        assert len(operator_errors) == 0

        print(f"Successfully queried {test_operator}:")
        print(f"  Channel: {results[0]['channel']}")
        print(f"  Version: {results[0]['version']}")
        print(f"  Install Modes: {[m['type'] for m in results[0]['installModes'] if m['supported']]}")

    def test_query_multiple_operators(self, container_tool, test_catalog):
        """Test querying multiple operators"""
        test_operators = os.getenv(
            'TEST_OPERATORS',
            'local-storage-operator,cluster-logging'
        ).split(',')

        results, errors = query_operators(
            test_catalog,
            test_operators,
            all_channels=False,
            tool=container_tool
        )

        # Should have results for most/all operators
        assert len(results) > 0
        print(f"Queried {len(results)} operators successfully")

        # Verify structure of results
        for result in results:
            assert 'name' in result
            assert 'channel' in result
            assert 'version' in result
            assert 'installModes' in result

    def test_query_all_channels(self, container_tool, test_catalog):
        """Test querying all channels for an operator"""
        test_operator = os.getenv('TEST_OPERATOR', 'local-storage-operator')

        results, errors = query_operators(
            test_catalog,
            [test_operator],
            all_channels=True,
            tool=container_tool
        )

        # Should have at least one channel
        assert len(results) >= 1

        # All results should be for the same operator
        for result in results:
            assert result['name'] == test_operator

        # Channels should be different
        channels = [r['channel'] for r in results]
        print(f"Found channels for {test_operator}: {channels}")

    def test_query_nonexistent_operator(self, container_tool, test_catalog):
        """Test querying operator that doesn't exist"""
        fake_operator = 'nonexistent-operator-12345'

        results, errors = query_operators(
            test_catalog,
            [fake_operator],
            all_channels=False,
            tool=container_tool
        )

        # Should have no results
        assert len(results) == 0

        # Should have error for this operator
        assert len(errors) == 1
        assert errors[0]['operator'] == fake_operator


class TestCatalogAuthentication:
    """Test handling of authentication scenarios"""

    def test_unauthenticated_catalog_access(self, container_tool):
        """Test accessing catalog without authentication"""
        # Use Red Hat catalog which requires auth
        catalog = 'registry.redhat.io/redhat/redhat-operator-index:v4.16'

        # Check if we're authenticated
        result = subprocess.run(
            ['skopeo', 'login', '--get-login', 'registry.redhat.io'],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # Not authenticated - this should fail gracefully
            with pytest.raises(RuntimeError, match="Failed to extract catalog"):
                extract_catalog(catalog, tool=container_tool)
        else:
            # Authenticated - should work
            pytest.skip("Already authenticated to Red Hat registry")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--integration'])
