#!/usr/bin/env python3
"""
Test suite for query_operator_catalog.py

Run with: pytest test_query_operator_catalog.py -v
Coverage: pytest test_query_operator_catalog.py --cov=query_operator_catalog --cov-report=html
"""

import pytest
import json
import base64
import tempfile
import os
import shutil
import sys
from unittest.mock import patch, MagicMock, mock_open
import yaml

# Add parent directory to path to import main module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions to test
from query_operator_catalog import (
    natural_sort_key,
    parse_operator_spec,
    parse_ndjson,
    extract_install_modes,
    resolve_bundle,
    query_operator_from_objects,
    query_operator_all_channels_from_objects,
    query_operator_all_channels_directory_format,
    query_operator_all_channels_concatenated_json,
    query_operator_index_format,
    query_operator_all_channels_index_format,
    detect_container_tool,
    read_config_file,
    format_json_output,
    format_table_output,
)


# ============================================================================
# Fixtures - Sample Data
# ============================================================================

@pytest.fixture
def sample_csv_data():
    """Sample ClusterServiceVersion YAML data"""
    csv = {
        'apiVersion': 'operators.coreos.com/v1alpha1',
        'kind': 'ClusterServiceVersion',
        'metadata': {
            'name': 'test-operator.v1.0.0'
        },
        'spec': {
            'installModes': [
                {'type': 'OwnNamespace', 'supported': True},
                {'type': 'SingleNamespace', 'supported': True},
                {'type': 'MultiNamespace', 'supported': False},
                {'type': 'AllNamespaces', 'supported': False}
            ]
        }
    }
    return yaml.dump(csv)


@pytest.fixture
def sample_bundle_old_format():
    """Sample bundle with olm.csv.metadata format (older catalogs)"""
    return {
        'schema': 'olm.bundle',
        'name': 'test-operator.v1.0.0',
        'package': 'test-operator',
        'properties': [
            {
                'type': 'olm.csv.metadata',
                'value': {
                    'installModes': [
                        {'type': 'OwnNamespace', 'supported': True},
                        {'type': 'SingleNamespace', 'supported': True},
                        {'type': 'MultiNamespace', 'supported': False},
                        {'type': 'AllNamespaces', 'supported': False}
                    ]
                }
            }
        ]
    }


@pytest.fixture
def sample_bundle_new_format(sample_csv_data):
    """Sample bundle with olm.bundle.object format (newer catalogs)"""
    # Base64 encode the CSV data
    encoded_csv = base64.b64encode(sample_csv_data.encode('utf-8')).decode('utf-8')

    return {
        'schema': 'olm.bundle',
        'name': 'test-operator.v1.0.0',
        'package': 'test-operator',
        'properties': [
            {
                'type': 'olm.package',
                'value': {
                    'packageName': 'test-operator',
                    'version': '1.0.0'
                }
            },
            {
                'type': 'olm.bundle.object',
                'value': {
                    'data': encoded_csv
                }
            }
        ]
    }


@pytest.fixture
def sample_catalog_objects():
    """Sample FBC catalog with package, channel, and bundle"""
    return [
        {
            'schema': 'olm.package',
            'name': 'test-operator',
            'defaultChannel': 'stable'
        },
        {
            'schema': 'olm.channel',
            'name': 'stable',
            'package': 'test-operator',
            'entries': [
                {'name': 'test-operator.v1.0.0'},
                {'name': 'test-operator.v1.1.0'},
                {'name': 'test-operator.v1.2.0'}
            ]
        },
        {
            'schema': 'olm.bundle',
            'name': 'test-operator.v1.0.0',
            'package': 'test-operator',
            'properties': [
                {
                    'type': 'olm.csv.metadata',
                    'value': {
                        'installModes': [
                            {'type': 'OwnNamespace', 'supported': True},
                            {'type': 'AllNamespaces', 'supported': False}
                        ]
                    }
                }
            ]
        },
        {
            'schema': 'olm.bundle',
            'name': 'test-operator.v1.1.0',
            'package': 'test-operator',
            'properties': [
                {
                    'type': 'olm.csv.metadata',
                    'value': {
                        'installModes': [
                            {'type': 'OwnNamespace', 'supported': True},
                            {'type': 'AllNamespaces', 'supported': True}
                        ]
                    }
                }
            ]
        },
        {
            'schema': 'olm.bundle',
            'name': 'test-operator.v1.2.0',
            'package': 'test-operator',
            'properties': [
                {
                    'type': 'olm.csv.metadata',
                    'value': {
                        'installModes': [
                            {'type': 'OwnNamespace', 'supported': True},
                            {'type': 'SingleNamespace', 'supported': True},
                            {'type': 'AllNamespaces', 'supported': True}
                        ]
                    }
                }
            ]
        }
    ]


# ============================================================================
# Tests - Utility Functions
# ============================================================================

class TestNaturalSortKey:
    """Test version-aware natural sorting"""

    def test_simple_versions(self):
        versions = ['1.2', '1.10', '1.3']
        sorted_versions = sorted(versions, key=natural_sort_key)
        assert sorted_versions == ['1.2', '1.3', '1.10']

    def test_operator_versions(self):
        versions = [
            'operator.v1.6',
            'operator.v1.10',
            'operator.v2.1',
            'operator.v1.15'
        ]
        sorted_versions = sorted(versions, key=natural_sort_key)
        assert sorted_versions == [
            'operator.v1.6',
            'operator.v1.10',
            'operator.v1.15',
            'operator.v2.1'
        ]

    def test_none_and_empty(self):
        assert natural_sort_key(None) == ['']
        assert natural_sort_key('') == ['']

    def test_non_string(self):
        # Non-strings are converted to string first, then split
        assert natural_sort_key(123) == ['', 123, '']


class TestParseOperatorSpec:
    """Test operator specification parsing"""

    def test_name_only(self):
        name, channel, version = parse_operator_spec('test-operator')
        assert name == 'test-operator'
        assert channel is None
        assert version is None

    def test_name_and_channel(self):
        name, channel, version = parse_operator_spec('test-operator:stable')
        assert name == 'test-operator'
        assert channel == 'stable'
        assert version is None

    def test_name_channel_version(self):
        name, channel, version = parse_operator_spec('test-operator:stable:1.0.0')
        assert name == 'test-operator'
        assert channel == 'stable'
        assert version == '1.0.0'

    def test_empty_spec(self):
        name, channel, version = parse_operator_spec('')
        assert name == ''
        assert channel is None
        assert version is None


class TestParseNDJSON:
    """Test NDJSON/concatenated JSON parsing"""

    def test_parse_ndjson(self, tmp_path):
        # Create test file with concatenated JSON
        test_file = tmp_path / "test.json"
        content = '''{"name": "obj1", "value": 1}
{"name": "obj2", "value": 2}
{"name": "obj3", "value": 3}'''
        test_file.write_text(content)

        objects = parse_ndjson(str(test_file))
        assert len(objects) == 3
        assert objects[0]['name'] == 'obj1'
        assert objects[1]['value'] == 2

    def test_parse_concatenated_json_no_newlines(self, tmp_path):
        # Test concatenated JSON without newlines (actual catalog format)
        test_file = tmp_path / "test.json"
        content = '{"name": "obj1"}{"name": "obj2"}{"name": "obj3"}'
        test_file.write_text(content)

        objects = parse_ndjson(str(test_file))
        assert len(objects) == 3

    def test_parse_with_whitespace(self, tmp_path):
        test_file = tmp_path / "test.json"
        content = '  {"name": "obj1"}  \n\n  {"name": "obj2"}  '
        test_file.write_text(content)

        objects = parse_ndjson(str(test_file))
        assert len(objects) == 2


class TestReadConfigFile:
    """Test config file reading"""

    def test_read_config(self, tmp_path):
        config_file = tmp_path / "operators.txt"
        content = '''operator1
operator2:stable
# This is a comment
operator3:stable:1.0.0

operator4
'''
        config_file.write_text(content)

        operators = read_config_file(str(config_file))
        assert len(operators) == 4
        assert 'operator1' in operators
        assert 'operator2:stable' in operators
        assert 'operator3:stable:1.0.0' in operators
        assert 'operator4' in operators

    def test_skip_comments_and_blanks(self, tmp_path):
        config_file = tmp_path / "operators.txt"
        content = '''# Comment
operator1

# Another comment
operator2
'''
        config_file.write_text(content)

        operators = read_config_file(str(config_file))
        assert len(operators) == 2


# ============================================================================
# Tests - Install Modes Extraction
# ============================================================================

class TestExtractInstallModes:
    """Test installModes extraction from different bundle formats"""

    def test_extract_old_format(self, sample_bundle_old_format):
        """Test extraction from olm.csv.metadata format"""
        install_modes = extract_install_modes(sample_bundle_old_format)
        assert install_modes is not None
        assert len(install_modes) == 4
        assert install_modes[0]['type'] == 'OwnNamespace'
        assert install_modes[0]['supported'] is True

    def test_extract_new_format(self, sample_bundle_new_format):
        """Test extraction from olm.bundle.object format"""
        install_modes = extract_install_modes(sample_bundle_new_format)
        assert install_modes is not None
        assert len(install_modes) == 4
        assert install_modes[0]['type'] == 'OwnNamespace'
        assert install_modes[0]['supported'] is True

    def test_extract_no_install_modes(self):
        """Test bundle without installModes"""
        bundle = {
            'schema': 'olm.bundle',
            'name': 'test-operator.v1.0.0',
            'properties': [
                {'type': 'olm.package', 'value': {'packageName': 'test'}}
            ]
        }
        install_modes = extract_install_modes(bundle)
        assert install_modes is None

    def test_extract_empty_properties(self):
        """Test bundle with empty properties"""
        bundle = {
            'schema': 'olm.bundle',
            'name': 'test-operator.v1.0.0',
            'properties': []
        }
        install_modes = extract_install_modes(bundle)
        assert install_modes is None

    def test_extract_malformed_base64(self):
        """Test bundle with invalid base64 data"""
        bundle = {
            'schema': 'olm.bundle',
            'name': 'test-operator.v1.0.0',
            'properties': [
                {
                    'type': 'olm.bundle.object',
                    'value': {'data': 'not-valid-base64!!!'}
                }
            ]
        }
        install_modes = extract_install_modes(bundle)
        assert install_modes is None


# ============================================================================
# Tests - Bundle Resolution
# ============================================================================

class TestResolveBundle:
    """Test bundle resolution from catalog objects"""

    def test_resolve_default_channel_latest_version(self, sample_catalog_objects):
        """Test resolving bundle with default channel and latest version"""
        bundle, channel = resolve_bundle(
            sample_catalog_objects,
            'test-operator',
            None,
            None
        )

        assert bundle is not None
        assert channel == 'stable'
        assert bundle['name'] == 'test-operator.v1.2.0'  # Latest

    def test_resolve_specific_version(self, sample_catalog_objects):
        """Test resolving specific version"""
        bundle, channel = resolve_bundle(
            sample_catalog_objects,
            'test-operator',
            'stable',
            'test-operator.v1.1.0'
        )

        assert bundle is not None
        assert channel == 'stable'
        assert bundle['name'] == 'test-operator.v1.1.0'

    def test_resolve_nonexistent_package(self, sample_catalog_objects):
        """Test resolving non-existent package"""
        bundle, channel = resolve_bundle(
            sample_catalog_objects,
            'nonexistent-operator',
            None,
            None
        )

        assert bundle is None
        assert channel is None

    def test_resolve_nonexistent_channel(self, sample_catalog_objects):
        """Test resolving non-existent channel"""
        bundle, channel = resolve_bundle(
            sample_catalog_objects,
            'test-operator',
            'nonexistent-channel',
            None
        )

        assert bundle is None
        assert channel is None


# ============================================================================
# Tests - Query Functions
# ============================================================================

class TestQueryOperatorFromObjects:
    """Test querying operator from catalog objects"""

    def test_query_success(self, sample_catalog_objects):
        """Test successful operator query"""
        result = query_operator_from_objects(
            sample_catalog_objects,
            'test-operator',
            None,
            None
        )

        assert result is not None
        assert result['name'] == 'test-operator'
        assert result['channel'] == 'stable'
        assert result['version'] == 'test-operator.v1.2.0'
        assert result['installModes'] is not None
        assert len(result['installModes']) == 3

    def test_query_specific_version(self, sample_catalog_objects):
        """Test query with specific version"""
        result = query_operator_from_objects(
            sample_catalog_objects,
            'test-operator',
            'stable',
            'test-operator.v1.0.0'
        )

        assert result is not None
        assert result['version'] == 'test-operator.v1.0.0'
        assert len(result['installModes']) == 2  # v1.0.0 has 2 install modes

    def test_query_not_found(self, sample_catalog_objects):
        """Test query for non-existent operator"""
        result = query_operator_from_objects(
            sample_catalog_objects,
            'nonexistent',
            None,
            None
        )

        assert result is None


# ============================================================================
# Tests - Container Tool Detection
# ============================================================================

class TestDetectContainerTool:
    """Test container tool detection"""

    @patch('subprocess.run')
    def test_detect_skopeo_first(self, mock_run):
        """Test that skopeo is preferred when both are available"""
        mock_run.return_value = MagicMock(returncode=0)

        tool = detect_container_tool()
        assert tool == 'skopeo'

        # Should check skopeo first
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == 'skopeo'

    @patch('subprocess.run')
    def test_detect_podman_fallback(self, mock_run):
        """Test fallback to podman when skopeo not available"""
        def side_effect(*args, **kwargs):
            cmd = args[0][0]
            if cmd == 'skopeo':
                raise FileNotFoundError()
            elif cmd == 'podman':
                return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        tool = detect_container_tool()
        assert tool == 'podman'

    @patch('subprocess.run')
    def test_detect_none(self, mock_run):
        """Test when neither tool is available"""
        mock_run.side_effect = FileNotFoundError()

        tool = detect_container_tool()
        assert tool is None


# ============================================================================
# Tests - Output Formatting
# ============================================================================

class TestFormatOutput:
    """Test output formatting functions"""

    def test_json_output(self, sample_catalog_objects):
        """Test JSON output format"""
        import io
        output = io.StringIO()

        results = [
            {
                'name': 'test-operator',
                'channel': 'stable',
                'version': 'test-operator.v1.0.0',
                'installModes': [
                    {'type': 'OwnNamespace', 'supported': True}
                ]
            }
        ]
        errors = []

        format_json_output('test-catalog:v1', results, errors, output)

        output_str = output.getvalue()
        parsed = json.loads(output_str)

        assert parsed['catalog'] == 'test-catalog:v1'
        assert len(parsed['operators']) == 1
        assert parsed['operators'][0]['name'] == 'test-operator'
        assert len(parsed['errors']) == 0

    def test_json_output_with_errors(self):
        """Test JSON output with errors"""
        import io
        output = io.StringIO()

        results = []
        errors = [
            {'operator': 'bad-operator', 'error': 'Not found'}
        ]

        format_json_output('test-catalog:v1', results, errors, output)

        output_str = output.getvalue()
        parsed = json.loads(output_str)

        assert len(parsed['errors']) == 1
        assert parsed['errors'][0]['operator'] == 'bad-operator'

    def test_table_output(self):
        """Test table output format"""
        import io
        output = io.StringIO()

        results = [
            {
                'name': 'test-operator',
                'channel': 'stable',
                'version': 'test-operator.v1.0.0',
                'installModes': [
                    {'type': 'OwnNamespace', 'supported': True},
                    {'type': 'AllNamespaces', 'supported': False}
                ]
            }
        ]
        errors = []

        format_table_output('test-catalog:v1', results, errors, output)

        output_str = output.getvalue()
        assert 'test-operator' in output_str
        assert 'stable' in output_str
        assert 'OwnNamespace' in output_str
        assert 'Catalog: test-catalog:v1' in output_str


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """End-to-end integration tests"""

    def test_full_query_workflow(self, sample_catalog_objects):
        """Test complete query workflow"""
        # Query operator
        result = query_operator_from_objects(
            sample_catalog_objects,
            'test-operator',
            None,
            None
        )

        # Verify result structure
        assert 'name' in result
        assert 'channel' in result
        assert 'version' in result
        assert 'installModes' in result

        # Verify install modes structure
        for mode in result['installModes']:
            assert 'type' in mode
            assert 'supported' in mode
            assert isinstance(mode['supported'], bool)


# ============================================================================
# Tests - Duplicate Scenarios (Regression Tests)
# ============================================================================

class TestDuplicateScenarios:
    """
    Regression tests for duplicate handling scenarios.

    These tests cover both bug cases (unwanted duplicates) and expected cases
    (multi-channel results with same version).
    """

    def test_duplicate_channel_objects_deduplicated(self):
        """
        Test that duplicate channel objects with same name are deduplicated.

        Bug scenario: Catalog contains multiple olm.channel objects with the
        same name (e.g., from catalog updates or merges). Only one should be
        processed.
        """
        from query_operator_catalog import query_operator_all_channels_from_objects

        # Create catalog with duplicate channel definitions
        objects = [
            {
                'schema': 'olm.package',
                'name': 'test-operator',
                'defaultChannel': 'stable'
            },
            # First definition of 'stable' channel
            {
                'schema': 'olm.channel',
                'name': 'stable',
                'package': 'test-operator',
                'entries': [
                    {'name': 'test-operator.v1.0.0'},
                    {'name': 'test-operator.v1.1.0'}
                ]
            },
            # Duplicate definition of 'stable' channel (should be ignored)
            {
                'schema': 'olm.channel',
                'name': 'stable',
                'package': 'test-operator',
                'entries': [
                    {'name': 'test-operator.v1.0.0'},
                    {'name': 'test-operator.v1.2.0'}  # Different latest version
                ]
            },
            {
                'schema': 'olm.bundle',
                'name': 'test-operator.v1.1.0',
                'package': 'test-operator',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'OwnNamespace', 'supported': True}
                            ]
                        }
                    }
                ]
            },
            {
                'schema': 'olm.bundle',
                'name': 'test-operator.v1.2.0',
                'package': 'test-operator',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'AllNamespaces', 'supported': True}
                            ]
                        }
                    }
                ]
            }
        ]

        results = query_operator_all_channels_from_objects(objects, 'test-operator')

        # Should only get one result for 'stable' channel (first definition processed)
        assert len(results) == 1
        assert results[0]['channel'] == 'stable'
        assert results[0]['version'] == 'test-operator.v1.1.0'

    def test_multiple_channels_same_version_not_duplicated(self):
        """
        Test that multiple channels with same latest version show separate entries.

        Expected behavior: Different channels that happen to have the same version
        as their latest should each appear in results. This is NOT a duplicate -
        it's correct behavior showing the same operator version is available in
        multiple channels.
        """
        from query_operator_catalog import query_operator_all_channels_from_objects

        # Create catalog with two channels pointing to same latest version
        objects = [
            {
                'schema': 'olm.package',
                'name': 'test-operator',
                'defaultChannel': 'stable'
            },
            {
                'schema': 'olm.channel',
                'name': 'stable',
                'package': 'test-operator',
                'entries': [
                    {'name': 'test-operator.v1.0.0'},
                    {'name': 'test-operator.v1.1.0'}
                ]
            },
            {
                'schema': 'olm.channel',
                'name': 'fast',
                'package': 'test-operator',
                'entries': [
                    {'name': 'test-operator.v1.0.0'},
                    {'name': 'test-operator.v1.1.0'}  # Same latest version
                ]
            },
            {
                'schema': 'olm.bundle',
                'name': 'test-operator.v1.1.0',
                'package': 'test-operator',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'OwnNamespace', 'supported': True}
                            ]
                        }
                    }
                ]
            }
        ]

        results = query_operator_all_channels_from_objects(objects, 'test-operator')

        # Should get TWO results - one for each channel, even though version is the same
        assert len(results) == 2

        # Both should have same version but different channels
        channels = {r['channel'] for r in results}
        assert channels == {'stable', 'fast'}

        versions = {r['version'] for r in results}
        assert versions == {'test-operator.v1.1.0'}

    def test_directory_format_duplicate_channel_files(self):
        """
        Test that directory format handles duplicate channel files correctly.

        Bug scenario: If the bundles/channels directory structure has duplicate
        channel JSON files (e.g., stable.json appearing twice due to filesystem
        issues), they should be deduplicated.
        """
        from query_operator_catalog import query_operator_all_channels_directory_format
        import tempfile
        import os
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create operator directory structure
            package_file = os.path.join(tmpdir, 'package.json')
            channels_dir = os.path.join(tmpdir, 'channels')
            bundles_dir = os.path.join(tmpdir, 'bundles')

            os.makedirs(channels_dir)
            os.makedirs(bundles_dir)

            # Write package.json
            with open(package_file, 'w') as f:
                json.dump({
                    'schema': 'olm.package',
                    'name': 'test-operator',
                    'defaultChannel': 'stable'
                }, f)

            # Write channel file
            channel_data = {
                'schema': 'olm.channel',
                'name': 'stable',
                'package': 'test-operator',
                'entries': [{'name': 'test-operator.v1.0.0'}]
            }
            with open(os.path.join(channels_dir, 'stable.json'), 'w') as f:
                json.dump(channel_data, f)

            # Write bundle file
            bundle_data = {
                'schema': 'olm.bundle',
                'name': 'test-operator.v1.0.0',
                'package': 'test-operator',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'OwnNamespace', 'supported': True}
                            ]
                        }
                    }
                ]
            }
            with open(os.path.join(bundles_dir, 'test-operator.v1.0.0.json'), 'w') as f:
                json.dump(bundle_data, f)

            # Query all channels
            results = query_operator_all_channels_directory_format(tmpdir, 'test-operator')

            # Should get exactly one result
            assert len(results) == 1
            assert results[0]['channel'] == 'stable'

    def test_concatenated_json_duplicate_channels(self):
        """
        Test that concatenated JSON format deduplicates channels correctly.

        Bug scenario: If channels.json contains the same channel definition
        multiple times, only the first should be processed.
        """
        from query_operator_catalog import query_operator_all_channels_concatenated_json
        import tempfile
        import os
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            package_file = os.path.join(tmpdir, 'package.json')
            channels_file = os.path.join(tmpdir, 'channels.json')
            bundles_file = os.path.join(tmpdir, 'bundles.json')

            # Write package.json
            with open(package_file, 'w') as f:
                json.dump({
                    'schema': 'olm.package',
                    'name': 'test-operator',
                    'defaultChannel': 'stable'
                }, f)

            # Write channels.json with duplicate channel
            channels_data = [
                {
                    'schema': 'olm.channel',
                    'name': 'stable',
                    'package': 'test-operator',
                    'entries': [{'name': 'test-operator.v1.0.0'}]
                },
                # Duplicate - should be ignored
                {
                    'schema': 'olm.channel',
                    'name': 'stable',
                    'package': 'test-operator',
                    'entries': [{'name': 'test-operator.v2.0.0'}]
                }
            ]
            with open(channels_file, 'w') as f:
                json.dump(channels_data, f)

            # Write bundles.json
            bundles_data = [
                {
                    'schema': 'olm.bundle',
                    'name': 'test-operator.v1.0.0',
                    'package': 'test-operator',
                    'properties': [
                        {
                            'type': 'olm.csv.metadata',
                            'value': {
                                'installModes': [
                                    {'type': 'OwnNamespace', 'supported': True}
                                ]
                            }
                        }
                    ]
                },
                {
                    'schema': 'olm.bundle',
                    'name': 'test-operator.v2.0.0',
                    'package': 'test-operator',
                    'properties': [
                        {
                            'type': 'olm.csv.metadata',
                            'value': {
                                'installModes': [
                                    {'type': 'AllNamespaces', 'supported': True}
                                ]
                            }
                        }
                    ]
                }
            ]
            with open(bundles_file, 'w') as f:
                json.dump(bundles_data, f)

            # Query all channels
            results = query_operator_all_channels_concatenated_json(tmpdir, 'test-operator')

            # Should get exactly one result (first channel definition)
            assert len(results) == 1
            assert results[0]['channel'] == 'stable'
            assert results[0]['version'] == 'test-operator.v1.0.0'

    def test_real_world_acm_scenario(self):
        """
        Test scenario matching advanced-cluster-management real-world behavior.

        Expected behavior: ACM has multiple release channels (release-2.10,
        release-2.11, etc.), each with different latest versions. All channels
        should appear in results - this is NOT a duplicate bug.
        """
        from query_operator_catalog import query_operator_all_channels_from_objects

        # Simulate ACM catalog structure with multiple release channels
        objects = [
            {
                'schema': 'olm.package',
                'name': 'advanced-cluster-management',
                'defaultChannel': 'release-2.14'
            },
            {
                'schema': 'olm.channel',
                'name': 'release-2.10',
                'package': 'advanced-cluster-management',
                'entries': [
                    {'name': 'advanced-cluster-management.v2.10.9'}
                ]
            },
            {
                'schema': 'olm.channel',
                'name': 'release-2.11',
                'package': 'advanced-cluster-management',
                'entries': [
                    {'name': 'advanced-cluster-management.v2.11.9'}
                ]
            },
            {
                'schema': 'olm.channel',
                'name': 'release-2.12',
                'package': 'advanced-cluster-management',
                'entries': [
                    {'name': 'advanced-cluster-management.v2.12.8'}
                ]
            },
            {
                'schema': 'olm.bundle',
                'name': 'advanced-cluster-management.v2.10.9',
                'package': 'advanced-cluster-management',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'OwnNamespace', 'supported': True}
                            ]
                        }
                    }
                ]
            },
            {
                'schema': 'olm.bundle',
                'name': 'advanced-cluster-management.v2.11.9',
                'package': 'advanced-cluster-management',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'OwnNamespace', 'supported': True}
                            ]
                        }
                    }
                ]
            },
            {
                'schema': 'olm.bundle',
                'name': 'advanced-cluster-management.v2.12.8',
                'package': 'advanced-cluster-management',
                'properties': [
                    {
                        'type': 'olm.csv.metadata',
                        'value': {
                            'installModes': [
                                {'type': 'OwnNamespace', 'supported': True}
                            ]
                        }
                    }
                ]
            }
        ]

        results = query_operator_all_channels_from_objects(objects, 'advanced-cluster-management')

        # Should get three results - one per channel (this is correct, not a duplicate)
        assert len(results) == 3

        # Verify each channel appears exactly once
        channels = [r['channel'] for r in results]
        assert sorted(channels) == ['release-2.10', 'release-2.11', 'release-2.12']

        # Verify versions are different (matching channel)
        channel_version_map = {r['channel']: r['version'] for r in results}
        assert channel_version_map['release-2.10'] == 'advanced-cluster-management.v2.10.9'
        assert channel_version_map['release-2.11'] == 'advanced-cluster-management.v2.11.9'
        assert channel_version_map['release-2.12'] == 'advanced-cluster-management.v2.12.8'


class TestIndexJsonFormat:
    """Test index.json + bundle-v*.json format"""

    def test_index_format_single_channel(self, tmp_path):
        """Test querying operator from index.json format"""
        operator_dir = tmp_path / "test-operator"
        operator_dir.mkdir()

        # Create index.json with package and channel
        index_data = [
            {
                "schema": "olm.package",
                "name": "test-operator",
                "defaultChannel": "stable"
            },
            {
                "schema": "olm.channel",
                "name": "stable",
                "entries": [
                    {"name": "test-operator.v1.0.0"},
                    {"name": "test-operator.v1.1.0"}
                ]
            }
        ]

        # Write as NDJSON (concatenated JSON)
        index_file = operator_dir / "index.json"
        with open(index_file, 'w') as f:
            for obj in index_data:
                json.dump(obj, f)

        # Create bundle file
        bundle = {
            "schema": "olm.bundle",
            "name": "test-operator.v1.1.0",
            "package": "test-operator",
            "properties": [
                {
                    "type": "olm.csv.metadata",
                    "value": {
                        "installModes": [
                            {"type": "OwnNamespace", "supported": True},
                            {"type": "AllNamespaces", "supported": False}
                        ]
                    }
                }
            ]
        }

        bundle_file = operator_dir / "bundle-v1.1.0.json"
        with open(bundle_file, 'w') as f:
            json.dump(bundle, f)

        # Test query
        result = query_operator_index_format(
            str(operator_dir),
            "test-operator",
            None,
            None
        )

        assert result is not None
        assert result['name'] == 'test-operator'
        assert result['channel'] == 'stable'
        assert result['version'] == 'test-operator.v1.1.0'
        assert len(result['installModes']) == 2

    def test_index_format_all_channels(self, tmp_path):
        """Test querying all channels from index.json format"""
        operator_dir = tmp_path / "test-operator"
        operator_dir.mkdir()

        # Create index.json with package and multiple channels
        index_data = [
            {
                "schema": "olm.package",
                "name": "test-operator",
                "defaultChannel": "stable"
            },
            {
                "schema": "olm.channel",
                "name": "stable",
                "entries": [
                    {"name": "test-operator.v1.1.0"}
                ]
            },
            {
                "schema": "olm.channel",
                "name": "alpha",
                "entries": [
                    {"name": "test-operator.v1.2.0"}
                ]
            }
        ]

        # Write as NDJSON
        index_file = operator_dir / "index.json"
        with open(index_file, 'w') as f:
            for obj in index_data:
                json.dump(obj, f)

        # Create bundle files
        bundle1 = {
            "schema": "olm.bundle",
            "name": "test-operator.v1.1.0",
            "package": "test-operator",
            "properties": [
                {
                    "type": "olm.csv.metadata",
                    "value": {
                        "installModes": [
                            {"type": "OwnNamespace", "supported": True}
                        ]
                    }
                }
            ]
        }

        bundle2 = {
            "schema": "olm.bundle",
            "name": "test-operator.v1.2.0",
            "package": "test-operator",
            "properties": [
                {
                    "type": "olm.csv.metadata",
                    "value": {
                        "installModes": [
                            {"type": "AllNamespaces", "supported": True}
                        ]
                    }
                }
            ]
        }

        with open(operator_dir / "bundle-v1.1.0.json", 'w') as f:
            json.dump(bundle1, f)

        with open(operator_dir / "bundle-v1.2.0.json", 'w') as f:
            json.dump(bundle2, f)

        # Test query all channels
        results = query_operator_all_channels_index_format(
            str(operator_dir),
            "test-operator"
        )

        assert len(results) == 2

        # Check stable channel
        stable_result = [r for r in results if r['channel'] == 'stable'][0]
        assert stable_result['version'] == 'test-operator.v1.1.0'
        assert stable_result['installModes'][0]['type'] == 'OwnNamespace'

        # Check alpha channel
        alpha_result = [r for r in results if r['channel'] == 'alpha'][0]
        assert alpha_result['version'] == 'test-operator.v1.2.0'
        assert alpha_result['installModes'][0]['type'] == 'AllNamespaces'

    def test_index_format_missing_file(self, tmp_path):
        """Test index format returns None when index.json doesn't exist"""
        operator_dir = tmp_path / "test-operator"
        operator_dir.mkdir()

        result = query_operator_index_format(
            str(operator_dir),
            "test-operator",
            None,
            None
        )

        assert result is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
