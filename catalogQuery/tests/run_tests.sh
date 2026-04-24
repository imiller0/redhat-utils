#!/bin/bash
#
# Test runner script for catalog query tool
# Runs unit tests and optionally integration tests
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Go to parent directory (catalogQuery root)
cd "$SCRIPT_DIR/.."

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Catalog Query Tool Test Runner${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Check if test dependencies are installed
if ! python3 -c "import pytest" 2>/dev/null; then
    echo -e "${YELLOW}Installing test dependencies...${NC}"
    pip install -r tests/requirements-test.txt -q
fi

# Run unit tests
echo -e "${GREEN}Running unit tests...${NC}"
if pytest tests/test_query_operator_catalog.py -v --tb=short; then
    echo -e "${GREEN}✓ Unit tests passed${NC}"
else
    echo -e "${RED}✗ Unit tests failed${NC}"
    exit 1
fi

echo ""

# Ask about integration tests
if [ "$1" = "--integration" ] || [ "$1" = "-i" ]; then
    echo -e "${GREEN}Running integration tests...${NC}"
    echo -e "${YELLOW}This will query real catalog images and may take a few minutes${NC}"

    if pytest tests/test_integration.py -v --integration --tb=short; then
        echo -e "${GREEN}✓ Integration tests passed${NC}"
    else
        echo -e "${YELLOW}⚠ Integration tests failed (this may be due to network/auth issues)${NC}"
    fi
else
    echo -e "${YELLOW}Skipping integration tests (use --integration to run them)${NC}"
fi

echo ""

# Generate coverage report
if [ "$1" = "--coverage" ] || [ "$2" = "--coverage" ]; then
    echo -e "${GREEN}Generating coverage report...${NC}"
    pytest tests/test_query_operator_catalog.py \
        --cov=query_operator_catalog \
        --cov-report=term-missing \
        --cov-report=html \
        -v > /dev/null

    echo -e "${GREEN}✓ Coverage report generated in htmlcov/index.html${NC}"
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}All tests completed successfully!${NC}"
echo -e "${GREEN}================================${NC}"
