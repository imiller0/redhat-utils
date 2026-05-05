#!/usr/bin/env python3
"""
Query Red Hat operator catalog indices for operator install modes.

This tool extracts installModes from operator ClusterServiceVersions (CSVs)
delivered via File-Based Catalog (FBC) format in Red Hat registry catalog indices.

Supports multiple FBC formats:
- configs/index.json (catalog-wide index, concatenated NDJSON)
- catalog.json (concatenated NDJSON)
- catalog.yaml (YAML multi-document, requires PyYAML)
- bundles/channels/package.json (directory structure)
- bundle-v*.json/channel.json/package.json (versioned bundles)
- bundles.json/channels.json/package.json (concatenated JSON files)

Usage:
    # Query specific operators (using version shorthand)
    ./query-operator-catalog.py \\
        --catalog 4.21 \\
        --operators local-storage-operator,odf-operator

    # Query from config file (using full URL)
    ./query-operator-catalog.py \\
        --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \\
        --config operators.txt

    # Specify channel and version (using version shorthand)
    ./query-operator-catalog.py \\
        --catalog 4.21 \\
        --operators 'odf-operator:stable-4.11,acm:release-2.9:2.9.0'

    # Query all channels for operators
    ./query-operator-catalog.py \\
        --catalog 4.22 \\
        --operators odf-operator \\
        --all-channels

    # JSON output
    ./query-operator-catalog.py \\
        --catalog 4.21 \\
        --operators cluster-logging \\
        -o json

Config file format (operators.txt):
    local-storage-operator
    odf-operator:stable
    # This is a comment
    advanced-cluster-management:release-2.9:2.9.0

Operator specification format:
    name[:channel[:version]]

    - name: Operator package name (required)
    - channel: Channel name (optional, uses defaultChannel if omitted)
    - version: Bundle version (optional, uses latest if omitted)

Requirements:
    - Python 3.6+
    - podman or skopeo CLI tool (skopeo preferred for container environments)
    - Access to Red Hat registry (podman/skopeo login may be required)
    - PyYAML (optional, for catalog.yaml format support)
"""

import argparse
import sys
import subprocess
import tempfile
import os
import shutil
import json
import re
import tarfile
import base64

# Try to import yaml for catalog.yaml support
try:
    import yaml
    YAML_SUPPORT = True
except ImportError:
    YAML_SUPPORT = False


def natural_sort_key(text):
    """
    Generate sort key for natural/version-aware sorting.

    Splits text into alternating string and number components.
    Numbers are converted to integers for proper numeric ordering.

    Args:
        text: String to generate sort key for (None and non-strings handled gracefully)

    Returns:
        List of comparable components (strings and ints)

    Examples:
        'gitops-1.6' → ['gitops-', 1, '.', 6, '']
        'gitops-1.10' → ['gitops-', 1, '.', 10, '']
    """
    # Handle None and empty strings
    if text is None or text == '':
        return ['']

    # Ensure text is a string
    if not isinstance(text, str):
        text = str(text)

    def convert(segment):
        return int(segment) if segment.isdigit() else segment

    return [convert(s) for s in re.split(r'(\d+)', text)]


def read_config_file(config_path):
    """
    Read operator specifications from config file.

    File format: one operator spec per line, # for comments, blank lines ignored.

    Args:
        config_path: Path to config file

    Returns:
        List of operator specification strings
    """
    operators = []

    with open(config_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip blank lines and comments
            if not line or line.startswith('#'):
                continue
            operators.append(line)

    return operators


def parse_operator_spec(spec):
    """
    Parse operator specification string.

    Format: operator-name[:channel[:version]]

    Args:
        spec: Operator specification string

    Returns:
        Tuple of (name, channel, version) where channel and version may be None
    """
    if not spec:
        return '', None, None

    parts = spec.split(':')
    name = parts[0]
    channel = parts[1] if len(parts) > 1 else None
    version = parts[2] if len(parts) > 2 else None

    return name, channel, version


def parse_ndjson(file_path):
    """
    Parse NDJSON (newline-delimited JSON) file.

    Note: FBC catalog.json files are actually concatenated JSON objects,
    not newline-delimited. This parser handles both formats.

    Args:
        file_path: Path to NDJSON file

    Returns:
        List of parsed JSON objects
    """
    objects = []

    with open(file_path, 'r') as f:
        data = f.read()

    # Use JSONDecoder to parse concatenated JSON objects
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(data):
        # Skip whitespace
        while idx < len(data) and data[idx].isspace():
            idx += 1

        if idx >= len(data):
            break

        try:
            obj, end_idx = decoder.raw_decode(data, idx)
            objects.append(obj)
            idx = end_idx
        except json.JSONDecodeError as e:
            # Log warning but try to continue from next character
            print(f'Warning: Skipping invalid JSON at position {idx}: {e}', file=sys.stderr)
            idx += 1

    return objects


def parse_yaml_catalog(file_path):
    """
    Parse YAML-format FBC catalog.

    Args:
        file_path: Path to catalog.yaml file

    Returns:
        List of parsed YAML documents or None if YAML support unavailable
    """
    if not YAML_SUPPORT:
        return None

    with open(file_path, 'r') as f:
        docs = list(yaml.safe_load_all(f))

    return [d for d in docs if d]  # Filter out None documents


def load_json_file(file_path):
    """
    Load JSON file, handling both regular and concatenated JSON.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON object or list of objects for concatenated JSON
    """
    with open(file_path, 'r') as f:
        data = f.read()

    # Try regular JSON first
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        pass

    # Fall back to concatenated JSON parsing
    return parse_ndjson(file_path)


def query_operator_from_objects(objects, operator_name, channel_name, version):
    """
    Query operator from parsed FBC objects (works for all formats).

    Args:
        objects: List of FBC objects (from JSON, YAML, or NDJSON)
        operator_name: Operator package name
        channel_name: Channel name (None for default)
        version: Bundle version (None for latest)

    Returns:
        Dict with name, channel, version, installModes or None if not found
    """
    # Resolve bundle
    bundle, resolved_channel = resolve_bundle(objects, operator_name, channel_name, version)
    if not bundle:
        return None

    # Extract install modes
    install_modes = extract_install_modes(bundle)
    if install_modes is None:
        return None

    return {
        'name': operator_name,
        'channel': resolved_channel,
        'version': bundle.get('name'),
        'installModes': install_modes
    }


def query_operator_all_channels_from_objects(objects, operator_name):
    """
    Query operator from parsed FBC objects for all channels.

    Args:
        objects: List of FBC objects (from JSON, YAML, or NDJSON)
        operator_name: Operator package name

    Returns:
        List of dicts with name, channel, version, installModes for each channel,
        or empty list if operator not found
    """
    # Find package
    package = None
    for obj in objects:
        if obj.get('schema') == 'olm.package' and obj.get('name') == operator_name:
            package = obj
            break

    if not package:
        return []

    # Find all channels for this operator
    # Use a dict to deduplicate by channel name (in case same channel appears multiple times)
    channels_dict = {}
    for obj in objects:
        if (obj.get('schema') == 'olm.channel' and
            obj.get('package') == operator_name):
            channel_name = obj.get('name')
            if channel_name and channel_name not in channels_dict:
                channels_dict[channel_name] = obj

    if not channels_dict:
        return []

    results = []

    # Process each channel
    for channel in channels_dict.values():
        channel_name = channel.get('name')
        entries = channel.get('entries', [])

        if not entries:
            continue

        # Get latest bundle (last entry)
        bundle_name = entries[-1].get('name')

        # Find bundle
        bundle = None
        for obj in objects:
            if (obj.get('schema') == 'olm.bundle' and
                obj.get('name') == bundle_name and
                obj.get('package') == operator_name):
                bundle = obj
                break

        if not bundle:
            continue

        # Extract install modes
        install_modes = extract_install_modes(bundle)
        if install_modes is None:
            continue

        results.append({
            'name': operator_name,
            'channel': channel_name,
            'version': bundle.get('name'),
            'installModes': install_modes
        })

    return results


def query_operator_directory_format(operator_dir, operator_name, channel_name, version):
    """
    Query operator from bundles/channels directory format.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name
        channel_name: Channel name (None for default)
        version: Bundle version (None for latest)

    Returns:
        Dict with operator info or None if format doesn't match
    """
    package_file = os.path.join(operator_dir, 'package.json')
    channels_dir = os.path.join(operator_dir, 'channels')
    bundles_dir = os.path.join(operator_dir, 'bundles')

    if not all(os.path.exists(p) for p in [package_file, channels_dir, bundles_dir]):
        return None

    # Load package to get default channel
    package = load_json_file(package_file)
    if isinstance(package, list):
        package = package[0]

    target_channel = channel_name if channel_name else package.get('defaultChannel')
    if not target_channel:
        return None

    # Load channel
    channel_file = os.path.join(channels_dir, f'{target_channel}.json')
    if not os.path.exists(channel_file):
        return None

    channel = load_json_file(channel_file)
    if isinstance(channel, list):
        channel = channel[0]

    entries = channel.get('entries', [])
    if not entries:
        return None

    # Get bundle name
    bundle_name = version if version else entries[-1].get('name')

    # Load bundle
    bundle_file = os.path.join(bundles_dir, f'{bundle_name}.json')
    if not os.path.exists(bundle_file):
        return None

    bundle = load_json_file(bundle_file)
    if isinstance(bundle, list):
        bundle = bundle[0]

    # Extract install modes
    install_modes = extract_install_modes(bundle)
    if install_modes is None:
        return None

    return {
        'name': operator_name,
        'channel': target_channel,
        'version': bundle.get('name'),
        'installModes': install_modes
    }


def query_operator_all_channels_directory_format(operator_dir, operator_name):
    """
    Query operator from bundles/channels directory format for all channels.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name

    Returns:
        List of dicts with operator info for each channel, or empty list if format doesn't match
    """
    package_file = os.path.join(operator_dir, 'package.json')
    channels_dir = os.path.join(operator_dir, 'channels')
    bundles_dir = os.path.join(operator_dir, 'bundles')

    if not all(os.path.exists(p) for p in [package_file, channels_dir, bundles_dir]):
        return []

    # Load package
    package = load_json_file(package_file)
    if isinstance(package, list):
        package = package[0]

    # Get all channel files
    if not os.path.isdir(channels_dir):
        return []

    channel_files = [f for f in os.listdir(channels_dir) if f.endswith('.json')]
    if not channel_files:
        return []

    results = []
    seen_channels = set()

    # Process each channel
    for channel_filename in channel_files:
        channel_file = os.path.join(channels_dir, channel_filename)
        channel = load_json_file(channel_file)
        if isinstance(channel, list):
            channel = channel[0]

        channel_name = channel.get('name')

        # Skip duplicate channels
        if channel_name in seen_channels:
            continue
        seen_channels.add(channel_name)

        entries = channel.get('entries', [])

        if not entries:
            continue

        # Get latest bundle (last entry)
        bundle_name = entries[-1].get('name')

        # Load bundle
        bundle_file = os.path.join(bundles_dir, f'{bundle_name}.json')
        if not os.path.exists(bundle_file):
            continue

        bundle = load_json_file(bundle_file)
        if isinstance(bundle, list):
            bundle = bundle[0]

        # Extract install modes
        install_modes = extract_install_modes(bundle)
        if install_modes is None:
            continue

        results.append({
            'name': operator_name,
            'channel': channel_name,
            'version': bundle.get('name'),
            'installModes': install_modes
        })

    return results


def query_operator_concatenated_json(operator_dir, operator_name, channel_name, version):
    """
    Query operator from bundles.json/channels.json/package.json format.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name
        channel_name: Channel name (None for default)
        version: Bundle version (None for latest)

    Returns:
        Dict with operator info or None if format doesn't match
    """
    package_file = os.path.join(operator_dir, 'package.json')
    channels_file = os.path.join(operator_dir, 'channels.json')
    bundles_file = os.path.join(operator_dir, 'bundles.json')

    if not all(os.path.exists(p) for p in [package_file, channels_file, bundles_file]):
        return None

    # Load package
    package_data = load_json_file(package_file)
    if isinstance(package_data, list):
        package = package_data[0]
    else:
        package = package_data

    target_channel = channel_name if channel_name else package.get('defaultChannel')

    # Load channels
    channels_data = load_json_file(channels_file)
    if not isinstance(channels_data, list):
        channels_data = [channels_data]

    # Find the target channel
    channel = None
    for ch in channels_data:
        if ch.get('name') == target_channel:
            channel = ch
            break

    if not channel:
        return None

    entries = channel.get('entries', [])
    if not entries:
        return None

    # Get bundle name
    bundle_name = version if version else entries[-1].get('name')

    # Load bundles
    bundles_data = load_json_file(bundles_file)
    if not isinstance(bundles_data, list):
        bundles_data = [bundles_data]

    # Find the bundle
    bundle = None
    for b in bundles_data:
        if b.get('name') == bundle_name:
            bundle = b
            break

    if not bundle:
        return None

    install_modes = extract_install_modes(bundle)
    if install_modes is None:
        return None

    return {
        'name': operator_name,
        'channel': target_channel,
        'version': bundle.get('name'),
        'installModes': install_modes
    }


def query_operator_all_channels_concatenated_json(operator_dir, operator_name):
    """
    Query operator from bundles.json/channels.json/package.json format for all channels.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name

    Returns:
        List of dicts with operator info for each channel, or empty list if format doesn't match
    """
    package_file = os.path.join(operator_dir, 'package.json')
    channels_file = os.path.join(operator_dir, 'channels.json')
    bundles_file = os.path.join(operator_dir, 'bundles.json')

    if not all(os.path.exists(p) for p in [package_file, channels_file, bundles_file]):
        return []

    # Load package
    package_data = load_json_file(package_file)
    if isinstance(package_data, list):
        package = package_data[0]
    else:
        package = package_data

    # Load channels
    channels_data = load_json_file(channels_file)
    if not isinstance(channels_data, list):
        channels_data = [channels_data]

    # Load bundles
    bundles_data = load_json_file(bundles_file)
    if not isinstance(bundles_data, list):
        bundles_data = [bundles_data]

    results = []
    seen_channels = set()

    # Process each channel
    for channel in channels_data:
        channel_name = channel.get('name')

        # Skip duplicate channels
        if channel_name in seen_channels:
            continue
        seen_channels.add(channel_name)
        entries = channel.get('entries', [])

        if not entries:
            continue

        # Get latest bundle (last entry)
        bundle_name = entries[-1].get('name')

        # Find the bundle
        bundle = None
        for b in bundles_data:
            if b.get('name') == bundle_name:
                bundle = b
                break

        if not bundle:
            continue

        install_modes = extract_install_modes(bundle)
        if install_modes is None:
            continue

        results.append({
            'name': operator_name,
            'channel': channel_name,
            'version': bundle.get('name'),
            'installModes': install_modes
        })

    return results


def query_operator_versioned_bundles(operator_dir, operator_name, channel_name, version):
    """
    Query operator from bundle-v*.json format.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name
        channel_name: Channel name (None for default)
        version: Bundle version (None for latest)

    Returns:
        Dict with operator info or None if format doesn't match
    """
    package_file = os.path.join(operator_dir, 'package.json')
    channel_file = os.path.join(operator_dir, 'channel.json')

    if not all(os.path.exists(p) for p in [package_file, channel_file]):
        return None

    # Load package
    package_data = load_json_file(package_file)
    if isinstance(package_data, list):
        package = package_data[0]
    else:
        package = package_data

    target_channel = channel_name if channel_name else package.get('defaultChannel')

    # Load channel
    channel_data = load_json_file(channel_file)
    if isinstance(channel_data, list):
        channel = channel_data[0]
    else:
        channel = channel_data

    entries = channel.get('entries', [])
    if not entries:
        return None

    # Get bundle name
    bundle_name = version if version else entries[-1].get('name')

    # Find bundle file
    bundle_files = [f for f in os.listdir(operator_dir) if f.startswith('bundle-')]
    for bundle_filename in bundle_files:
        bundle_path = os.path.join(operator_dir, bundle_filename)
        bundle = load_json_file(bundle_path)
        if isinstance(bundle, list):
            bundle = bundle[0]

        if bundle.get('name') == bundle_name:
            install_modes = extract_install_modes(bundle)
            if install_modes is not None:
                return {
                    'name': operator_name,
                    'channel': target_channel,
                    'version': bundle.get('name'),
                    'installModes': install_modes
                }

    return None


def query_operator_all_channels_versioned_bundles(operator_dir, operator_name):
    """
    Query operator from bundle-v*.json format for all channels.

    Note: This format typically has a single channel.json file representing one channel.
    This function returns the latest bundle for that channel.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name

    Returns:
        List of dicts with operator info, or empty list if format doesn't match
    """
    package_file = os.path.join(operator_dir, 'package.json')
    channel_file = os.path.join(operator_dir, 'channel.json')

    if not all(os.path.exists(p) for p in [package_file, channel_file]):
        return []

    # Load package
    package_data = load_json_file(package_file)
    if isinstance(package_data, list):
        package = package_data[0]
    else:
        package = package_data

    # Load channel
    channel_data = load_json_file(channel_file)
    if isinstance(channel_data, list):
        channel = channel_data[0]
    else:
        channel = channel_data

    channel_name = channel.get('name')
    entries = channel.get('entries', [])

    if not entries:
        return []

    # Get latest bundle (last entry)
    bundle_name = entries[-1].get('name')

    # Find bundle file
    bundle_files = [f for f in os.listdir(operator_dir) if f.startswith('bundle-')]
    for bundle_filename in bundle_files:
        bundle_path = os.path.join(operator_dir, bundle_filename)
        bundle = load_json_file(bundle_path)
        if isinstance(bundle, list):
            bundle = bundle[0]

        if bundle.get('name') == bundle_name:
            install_modes = extract_install_modes(bundle)
            if install_modes is not None:
                return [{
                    'name': operator_name,
                    'channel': channel_name,
                    'version': bundle.get('name'),
                    'installModes': install_modes
                }]

    return []


def query_operator_index_format(operator_dir, operator_name, channel_name, version):
    """
    Query operator from index.json + bundle-v*.json format.

    This format has:
    - index.json: NDJSON file with olm.package and olm.channel objects
    - bundle-v*.json: Individual bundle files

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name
        channel_name: Channel name (None for default)
        version: Bundle version (None for latest)

    Returns:
        Dict with operator info or None if format doesn't match
    """
    index_file = os.path.join(operator_dir, 'index.json')

    if not os.path.exists(index_file):
        return None

    # Parse index.json as NDJSON
    try:
        objects = parse_ndjson(index_file)
    except Exception:
        return None

    # Find package
    package = None
    for obj in objects:
        if obj.get('schema') == 'olm.package' and obj.get('name') == operator_name:
            package = obj
            break

    if not package:
        return None

    # Determine channel to use
    target_channel = channel_name if channel_name else package.get('defaultChannel')
    if not target_channel:
        return None

    # Find channel
    channel = None
    for obj in objects:
        if (obj.get('schema') == 'olm.channel' and
            obj.get('name') == target_channel):
            channel = obj
            break

    if not channel:
        return None

    entries = channel.get('entries', [])
    if not entries:
        return None

    # Get bundle name
    bundle_name = version if version else entries[-1].get('name')

    # Find and load bundle file
    bundle_files = [f for f in os.listdir(operator_dir) if f.startswith('bundle-')]
    for bundle_filename in bundle_files:
        bundle_path = os.path.join(operator_dir, bundle_filename)
        try:
            bundle = load_json_file(bundle_path)
            if isinstance(bundle, list):
                bundle = bundle[0]

            if bundle.get('name') == bundle_name:
                install_modes = extract_install_modes(bundle)
                if install_modes is not None:
                    return {
                        'name': operator_name,
                        'channel': target_channel,
                        'version': bundle.get('name'),
                        'installModes': install_modes
                    }
        except Exception:
            continue

    return None


def query_operator_all_channels_index_format(operator_dir, operator_name):
    """
    Query operator from index.json + bundle-v*.json format for all channels.

    Args:
        operator_dir: Path to operator directory
        operator_name: Operator package name

    Returns:
        List of dicts with operator info for each channel, or empty list if format doesn't match
    """
    index_file = os.path.join(operator_dir, 'index.json')

    if not os.path.exists(index_file):
        return []

    # Parse index.json as NDJSON
    try:
        objects = parse_ndjson(index_file)
    except Exception:
        return []

    # Find package
    package = None
    for obj in objects:
        if obj.get('schema') == 'olm.package' and obj.get('name') == operator_name:
            package = obj
            break

    if not package:
        return []

    # Find all channels
    channels = []
    for obj in objects:
        if obj.get('schema') == 'olm.channel':
            channels.append(obj)

    if not channels:
        return []

    results = []

    # Process each channel
    for channel in channels:
        channel_name = channel.get('name')
        entries = channel.get('entries', [])

        if not entries:
            continue

        # Get latest bundle (last entry)
        bundle_name = entries[-1].get('name')

        # Find and load bundle file
        bundle_files = [f for f in os.listdir(operator_dir) if f.startswith('bundle-')]
        for bundle_filename in bundle_files:
            bundle_path = os.path.join(operator_dir, bundle_filename)
            try:
                bundle = load_json_file(bundle_path)
                if isinstance(bundle, list):
                    bundle = bundle[0]

                if bundle.get('name') == bundle_name:
                    install_modes = extract_install_modes(bundle)
                    if install_modes is not None:
                        results.append({
                            'name': operator_name,
                            'channel': channel_name,
                            'version': bundle.get('name'),
                            'installModes': install_modes
                        })
                    break
            except Exception:
                continue

    return results


def detect_container_tool():
    """
    Detect which container tool is available.

    Returns:
        String: 'skopeo', 'podman', or None if neither is available
    """
    # Try skopeo first (more container-friendly)
    try:
        result = subprocess.run(
            ['skopeo', '--version'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return 'skopeo'
    except FileNotFoundError:
        pass

    # Try podman
    try:
        result = subprocess.run(
            ['podman', '--version'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return 'podman'
    except FileNotFoundError:
        pass

    return None


def extract_catalog_with_skopeo(catalog_url, temp_dir):
    """
    Extract catalog configs using skopeo.

    Downloads image to OCI format, then extracts layers to find /configs directory.

    Args:
        catalog_url: Catalog index URL
        temp_dir: Temporary directory for extraction

    Raises:
        RuntimeError: If skopeo operations fail
    """
    oci_dir = os.path.join(temp_dir, 'oci')
    os.makedirs(oci_dir, exist_ok=True)

    # Copy image to OCI directory format (remove signatures as OCI doesn't support them)
    result = subprocess.run(
        ['skopeo', 'copy', '--remove-signatures', f'docker://{catalog_url}', f'oci:{oci_dir}'],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f'Failed to copy catalog with skopeo: {result.stderr}')

    # Find the blob directory
    blob_dir = os.path.join(oci_dir, 'blobs', 'sha256')
    if not os.path.exists(blob_dir):
        raise RuntimeError('Failed to find blobs in OCI image')

    # Extract layers to find /configs
    configs_found = False
    extract_dir = os.path.join(temp_dir, 'extracted')
    os.makedirs(extract_dir, exist_ok=True)

    # Try each blob (layer) until we find one with /configs
    for blob_file in os.listdir(blob_dir):
        blob_path = os.path.join(blob_dir, blob_file)

        # Skip if not a file
        if not os.path.isfile(blob_path):
            continue

        try:
            # Try to open as tar
            with tarfile.open(blob_path, 'r') as tar:
                # Check if this layer has a configs directory
                members = tar.getnames()
                has_configs = any(m.startswith('configs/') or m == 'configs' for m in members)

                if has_configs:
                    # Extract configs directory
                    for member in tar.getmembers():
                        if member.name.startswith('configs/') or member.name == 'configs':
                            # Use data filter to safely extract (Python 3.12+ security feature)
                            try:
                                tar.extract(member, extract_dir, filter='data')
                            except TypeError:
                                # Fall back for older Python versions
                                tar.extract(member, extract_dir)
                    configs_found = True
                    break
        except (tarfile.TarError, OSError):
            # Not a tar file or couldn't read it, skip
            continue

    if not configs_found:
        raise RuntimeError('Could not find /configs directory in catalog image')

    # Move configs to expected location
    configs_src = os.path.join(extract_dir, 'configs')
    configs_dst = os.path.join(temp_dir, 'configs')

    if os.path.exists(configs_src):
        shutil.move(configs_src, configs_dst)
    else:
        raise RuntimeError('Configs directory not properly extracted')


def extract_catalog_with_podman(catalog_url, temp_dir):
    """
    Extract catalog configs using podman.

    Pulls catalog image, creates container, extracts /configs directory.

    Args:
        catalog_url: Catalog index URL
        temp_dir: Temporary directory for extraction

    Raises:
        RuntimeError: If podman operations fail
    """
    # Pull catalog image
    result = subprocess.run(
        ['podman', 'pull', catalog_url],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f'Failed to pull catalog {catalog_url}: {result.stderr}')

    # Create temporary container
    container_name = f'catalog-temp-{os.getpid()}'
    result = subprocess.run(
        ['podman', 'create', '--name', container_name, catalog_url],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f'Failed to create container: {result.stderr}')

    try:
        # Copy configs directory
        result = subprocess.run(
            ['podman', 'cp', f'{container_name}:/configs', temp_dir],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f'Failed to copy configs: {result.stderr}')
    finally:
        # Always remove temporary container
        subprocess.run(
            ['podman', 'rm', container_name],
            capture_output=True,
            text=True
        )


def extract_catalog(catalog_url, tool=None):
    """
    Extract catalog configs using available container tool.

    Creates temporary directory, pulls catalog image, extracts /configs directory.
    Automatically detects and uses skopeo or podman, with preference for skopeo
    in container environments.

    Args:
        catalog_url: Catalog index URL (e.g., registry.redhat.io/redhat/redhat-operator-index:v4.21)
        tool: Force specific tool ('skopeo' or 'podman'), or None for auto-detect

    Returns:
        Path to temporary directory containing extracted configs

    Raises:
        RuntimeError: If extraction fails or no container tool is available
    """
    # Create unique temporary directory
    temp_dir = tempfile.mkdtemp(prefix='operator-catalog-')

    try:
        # Determine which tool to use
        if tool:
            selected_tool = tool
        else:
            selected_tool = detect_container_tool()

        if not selected_tool:
            raise RuntimeError(
                'No container tool available. Install skopeo or podman.\n'
                'For container environments, skopeo is recommended: dnf install -y skopeo'
            )

        print(f'Using {selected_tool} to extract catalog...', file=sys.stderr)

        # Extract using the selected tool
        if selected_tool == 'skopeo':
            extract_catalog_with_skopeo(catalog_url, temp_dir)
        elif selected_tool == 'podman':
            extract_catalog_with_podman(catalog_url, temp_dir)
        else:
            raise RuntimeError(f'Unknown tool: {selected_tool}')

        return temp_dir

    except Exception:
        # Cleanup temp directory on error
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise


def resolve_bundle(objects, operator_name, channel_name, version):
    """
    Resolve bundle for operator from catalog objects.

    Args:
        objects: List of parsed NDJSON objects
        operator_name: Operator package name
        channel_name: Channel name (None for default)
        version: Bundle version (None for latest)

    Returns:
        Tuple of (bundle_object, channel_name) or (None, None) if not found
    """
    # Find package
    package = None
    for obj in objects:
        if obj.get('schema') == 'olm.package' and obj.get('name') == operator_name:
            package = obj
            break

    if not package:
        return None, None

    # Determine channel to use
    target_channel = channel_name if channel_name else package.get('defaultChannel')

    if not target_channel:
        return None, None

    # Find channel
    channel = None
    for obj in objects:
        if (obj.get('schema') == 'olm.channel' and
            obj.get('name') == target_channel and
            obj.get('package') == operator_name):
            channel = obj
            break

    if not channel:
        return None, None

    # Determine bundle name
    entries = channel.get('entries', [])
    if not entries:
        return None, None

    if version:
        # Find specific version
        bundle_name = version
    else:
        # Use latest (last entry)
        bundle_name = entries[-1].get('name')

    # Find bundle
    bundle = None
    for obj in objects:
        if (obj.get('schema') == 'olm.bundle' and
            obj.get('name') == bundle_name and
            obj.get('package') == operator_name):
            bundle = obj
            break

    if not bundle:
        return None, None

    return bundle, target_channel


def extract_install_modes(bundle):
    """
    Extract installModes from bundle CSV metadata.

    Supports two formats:
    1. olm.csv.metadata property (older catalog format)
    2. ClusterServiceVersion in olm.bundle.object property (newer catalog format)

    Args:
        bundle: Bundle object with properties array

    Returns:
        List of installMode objects or None if not found
    """
    properties = bundle.get('properties', [])

    # Method 1: Try olm.csv.metadata property (older format)
    for prop in properties:
        if prop.get('type') == 'olm.csv.metadata':
            csv_metadata = prop.get('value', {})
            install_modes = csv_metadata.get('installModes')
            if install_modes:
                return install_modes

    # Method 2: Try olm.bundle.object property (newer format)
    # The CSV is base64-encoded YAML in the 'data' field
    for prop in properties:
        if prop.get('type') == 'olm.bundle.object':
            value = prop.get('value', {})
            data = value.get('data', '')

            if not data:
                continue

            try:
                # Decode from base64
                decoded = base64.b64decode(data).decode('utf-8')

                # Parse as YAML (CSVs are YAML documents)
                if YAML_SUPPORT:
                    csv_doc = yaml.safe_load(decoded)

                    # Check if this is a ClusterServiceVersion
                    if csv_doc and csv_doc.get('kind') == 'ClusterServiceVersion':
                        spec = csv_doc.get('spec', {})
                        install_modes = spec.get('installModes')
                        if install_modes:
                            return install_modes
                else:
                    # If YAML is not available, try to parse as JSON
                    # (some CSVs might be JSON-formatted)
                    csv_doc = json.loads(decoded)
                    if csv_doc and csv_doc.get('kind') == 'ClusterServiceVersion':
                        spec = csv_doc.get('spec', {})
                        install_modes = spec.get('installModes')
                        if install_modes:
                            return install_modes
            except (base64.binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                # Not base64, not valid UTF-8, or not valid JSON/YAML - skip this property
                continue
            except Exception:
                # Any other error - skip this property
                continue

    return None


def format_table_output(catalog, results, errors, output=sys.stdout):
    """
    Format results as human-readable table.

    Args:
        catalog: Catalog URL
        results: List of result dicts with name, channel, version, installModes
        errors: List of error dicts with operator and error
        output: Output stream (default: stdout)
    """
    print(f'Catalog: {catalog}\n', file=output)

    if results:
        # Sort results by operator name, then channel name with natural sorting
        results = sorted(results, key=lambda r: (r['name'], natural_sort_key(r['channel'])))

        # Print header
        print(f'{"OPERATOR":<40} {"CHANNEL":<20} {"VERSION":<50} INSTALL MODES', file=output)

        # Print results
        for result in results:
            name = result['name']
            channel = result['channel']
            version = result['version']

            # Get supported modes only
            install_modes = result.get('installModes', [])
            supported_modes = [
                mode['type'] for mode in install_modes
                if mode.get('supported', False)
            ]
            modes_str = ', '.join(supported_modes) if supported_modes else 'None'

            print(f'{name:<40} {channel:<20} {version:<50} {modes_str}', file=output)

    if errors:
        print(f'\nErrors:', file=output)
        for error in errors:
            print(f'  {error["operator"]}: {error["error"]}', file=output)


def format_json_output(catalog, results, errors, output=sys.stdout):
    """
    Format results as JSON.

    Args:
        catalog: Catalog URL
        results: List of result dicts with name, channel, version, installModes
        errors: List of error dicts with operator and error
        output: Output stream (default: stdout)
    """
    # Sort results by operator name, then channel name with natural sorting
    results = sorted(results, key=lambda r: (r['name'], natural_sort_key(r['channel'])))

    data = {
        'catalog': catalog,
        'operators': results,
        'errors': errors
    }

    json.dump(data, output, indent=2)
    print('', file=output)  # Trailing newline


def query_operator_from_directory(operator_dir, operator_name, channel, version, all_channels):
    """
    Query operator from directory, trying all supported catalog formats.

    Tries formats in order:
    1. catalog.json (NDJSON)
    2. catalog.yaml (YAML multi-document)
    3. bundles/channels directory structure
    4. concatenated JSON files (bundles.json/channels.json)
    5. versioned bundles (bundle-v*.json)
    6. index.json + bundle files

    Args:
        operator_dir: Path to operator directory in configs
        operator_name: Operator package name
        channel: Channel name (None for default)
        version: Bundle version (None for latest)
        all_channels: If True, query all channels; if False, query single channel

    Returns:
        - If all_channels=True: list of result dicts (empty if not found)
        - If all_channels=False: result dict or None if not found
        - Special value 'YAML_REQUIRED' if catalog.yaml exists but PyYAML not available
    """
    # Try catalog.json format
    catalog_json = os.path.join(operator_dir, 'catalog.json')
    if os.path.exists(catalog_json):
        try:
            objects = parse_ndjson(catalog_json)
            if all_channels:
                results = query_operator_all_channels_from_objects(objects, operator_name)
                if results:
                    return results
            else:
                result = query_operator_from_objects(objects, operator_name, channel, version)
                if result:
                    return result
        except Exception as e:
            print(f'Warning: Failed to parse catalog.json for {operator_name}: {e}', file=sys.stderr)

    # Try catalog.yaml format
    catalog_yaml = os.path.join(operator_dir, 'catalog.yaml')
    if os.path.exists(catalog_yaml):
        if not YAML_SUPPORT:
            return 'YAML_REQUIRED'
        try:
            objects = parse_yaml_catalog(catalog_yaml)
            if objects:
                if all_channels:
                    results = query_operator_all_channels_from_objects(objects, operator_name)
                    if results:
                        return results
                else:
                    result = query_operator_from_objects(objects, operator_name, channel, version)
                    if result:
                        return result
        except Exception as e:
            print(f'Warning: Failed to parse catalog.yaml for {operator_name}: {e}', file=sys.stderr)

    # Try bundles/channels directory format
    try:
        if all_channels:
            results = query_operator_all_channels_directory_format(operator_dir, operator_name)
            if results:
                return results
        else:
            result = query_operator_directory_format(operator_dir, operator_name, channel, version)
            if result:
                return result
    except Exception as e:
        print(f'Warning: Failed to parse directory format for {operator_name}: {e}', file=sys.stderr)

    # Try concatenated JSON files format
    try:
        if all_channels:
            results = query_operator_all_channels_concatenated_json(operator_dir, operator_name)
            if results:
                return results
        else:
            result = query_operator_concatenated_json(operator_dir, operator_name, channel, version)
            if result:
                return result
    except Exception as e:
        print(f'Warning: Failed to parse concatenated JSON format for {operator_name}: {e}', file=sys.stderr)

    # Try versioned bundles format
    try:
        if all_channels:
            results = query_operator_all_channels_versioned_bundles(operator_dir, operator_name)
            if results:
                return results
        else:
            result = query_operator_versioned_bundles(operator_dir, operator_name, channel, version)
            if result:
                return result
    except Exception as e:
        print(f'Warning: Failed to parse versioned bundles format for {operator_name}: {e}', file=sys.stderr)

    # Try index.json format
    try:
        if all_channels:
            results = query_operator_all_channels_index_format(operator_dir, operator_name)
            if results:
                return results
        else:
            result = query_operator_index_format(operator_dir, operator_name, channel, version)
            if result:
                return result
    except Exception as e:
        print(f'Warning: Failed to parse index.json format for {operator_name}: {e}', file=sys.stderr)

    # Nothing found
    return [] if all_channels else None


def query_operators(catalog_url, operator_specs, all_channels=False, tool=None):
    """
    Query operators from catalog.

    Args:
        catalog_url: Catalog index URL
        operator_specs: List of operator specification strings
        all_channels: If True, query all channels for each operator
        tool: Container tool to use ('skopeo' or 'podman'), or None for auto-detect

    Returns:
        Tuple of (results, errors) where results is list of operator dicts
        and errors is list of error dicts
    """
    results = []
    errors = []

    # Extract catalog
    try:
        temp_dir = extract_catalog(catalog_url, tool=tool)
    except RuntimeError as e:
        # Fatal error - cannot proceed
        raise RuntimeError(f'Failed to extract catalog: {e}')

    try:
        configs_dir = os.path.join(temp_dir, 'configs')

        # Check for catalog-wide index.json format
        catalog_index = os.path.join(configs_dir, 'index.json')
        catalog_objects = None

        if os.path.exists(catalog_index):
            # Catalog-wide index.json format - parse it once
            try:
                catalog_objects = parse_ndjson(catalog_index)
            except Exception as e:
                print(f'Warning: Failed to parse catalog-wide index.json: {e}', file=sys.stderr)

        # Process each operator
        for spec in operator_specs:
            operator_name, channel, version = parse_operator_spec(spec)

            if not operator_name:
                errors.append({
                    'operator': spec,
                    'error': 'Invalid operator specification'
                })
                continue

            # Warn if channel specified with --all-channels
            if all_channels and channel:
                print(f'Warning: Ignoring channel specification "{channel}" for {operator_name} due to --all-channels flag', file=sys.stderr)

            # If we have catalog-wide objects, query from them
            if catalog_objects:
                if all_channels:
                    query_result = query_operator_all_channels_from_objects(catalog_objects, operator_name)
                else:
                    query_result = query_operator_from_objects(catalog_objects, operator_name, channel, version)

                # Process results
                if all_channels:
                    if query_result:
                        results.extend(query_result)
                    else:
                        errors.append({
                            'operator': operator_name,
                            'error': 'No installModes found or operator not in catalog'
                        })
                else:
                    if query_result:
                        results.append(query_result)
                    else:
                        errors.append({
                            'operator': operator_name,
                            'error': 'No installModes found or operator not in catalog'
                        })
                continue

            # Otherwise, check if operator directory exists
            operator_dir = os.path.join(configs_dir, operator_name)
            if not os.path.exists(operator_dir):
                errors.append({
                    'operator': operator_name,
                    'error': 'Not found in catalog'
                })
                continue

            # Query operator using unified format detection
            query_result = query_operator_from_directory(
                operator_dir, operator_name, channel, version, all_channels
            )

            # Handle special YAML_REQUIRED marker
            if query_result == 'YAML_REQUIRED':
                errors.append({
                    'operator': operator_name,
                    'error': 'catalog.yaml format requires PyYAML (pip install pyyaml)'
                })
                continue

            # Process results
            if all_channels:
                if query_result:
                    results.extend(query_result)
                else:
                    errors.append({
                        'operator': operator_name,
                        'error': 'No installModes found or unsupported catalog format'
                    })
            else:
                if query_result:
                    results.append(query_result)
                else:
                    errors.append({
                        'operator': operator_name,
                        'error': 'No installModes found or unsupported catalog format'
                    })

    finally:
        # Cleanup temp directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    return results, errors


def normalize_catalog_url(catalog):
    """
    Normalize catalog argument to full URL.

    If catalog looks like a version number (e.g., "4.21", "4.22"), expand it to
    the well-known registry.redhat.io URL. Otherwise, return as-is.

    Args:
        catalog: Catalog string (version or full URL)

    Returns:
        Full catalog URL

    Examples:
        "4.21" -> "registry.redhat.io/redhat/redhat-operator-index:v4.21"
        "4.22" -> "registry.redhat.io/redhat/redhat-operator-index:v4.22"
        "registry.redhat.io/..." -> "registry.redhat.io/..." (unchanged)
    """
    # Check if this looks like a version number (e.g., "4.21", "4.22")
    # Pattern: digits, optional dots and more digits, no slashes or colons
    if re.match(r'^\d+\.\d+$', catalog):
        # Expand to full registry URL
        return f'registry.redhat.io/redhat/redhat-operator-index:v{catalog}'

    # Return as-is if it already looks like a full URL
    return catalog


def parse_arguments(args):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Query Red Hat operator catalog indices for install modes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s --catalog 4.21 --operators local-storage-operator,odf-operator

  %(prog)s --catalog registry.redhat.io/redhat/redhat-operator-index:v4.21 \\
           --operators local-storage-operator,odf-operator

  %(prog)s --catalog 4.22 --config operators.txt

  %(prog)s --catalog 4.21 --operators local-storage-operator -o json
        '''
    )

    parser.add_argument(
        '--catalog',
        required=True,
        help='Catalog version (e.g., 4.21, 4.22) or full catalog URL (e.g., registry.redhat.io/redhat/redhat-operator-index:v4.21)'
    )

    parser.add_argument(
        '--operators',
        help='Comma-separated list of operator specs (name[:channel[:version]])'
    )

    parser.add_argument(
        '--config',
        help='Config file with one operator spec per line'
    )

    parser.add_argument(
        '-o', '--output',
        choices=['table', 'json'],
        default='table',
        help='Output format (default: table)'
    )

    parser.add_argument(
        '--all-channels',
        action='store_true',
        help='Query all channels for each operator (ignores channel specifications)'
    )

    parser.add_argument(
        '--tool',
        choices=['skopeo', 'podman'],
        help='Container tool to use for extracting catalog (default: auto-detect, prefers skopeo)'
    )

    return parser.parse_args(args)


def main():
    """Main entry point."""
    args = parse_arguments(sys.argv[1:])

    # Normalize catalog URL (expand version-only format to full URL)
    catalog_url = normalize_catalog_url(args.catalog)

    # Collect operator specs
    operator_specs = []

    if args.operators:
        operator_specs.extend(args.operators.split(','))

    if args.config:
        try:
            operator_specs.extend(read_config_file(args.config))
        except FileNotFoundError:
            print(f'Error: Config file not found: {args.config}', file=sys.stderr)
            return 1

    if not operator_specs:
        print('Error: No operators specified. Use --operators or --config.', file=sys.stderr)
        print('Run with --help for usage information.', file=sys.stderr)
        return 1

    # Query operators
    try:
        results, errors = query_operators(
            catalog_url,
            operator_specs,
            all_channels=args.all_channels,
            tool=args.tool
        )
    except RuntimeError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1

    # Format output
    if args.output == 'json':
        format_json_output(catalog_url, results, errors)
    else:
        format_table_output(catalog_url, results, errors)

    # Return non-zero if there were errors
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
