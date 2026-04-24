.PHONY: help test test-unit test-integration test-coverage install-test clean

help:
	@echo "Available targets:"
	@echo "  install-test       Install test dependencies"
	@echo "  test              Run all unit tests"
	@echo "  test-unit         Run unit tests only"
	@echo "  test-integration  Run integration tests (requires catalog access)"
	@echo "  test-coverage     Run tests with coverage report"
	@echo "  clean             Remove test artifacts and cache"

install-test:
	pip install -r tests/requirements-test.txt

test: test-unit

test-unit:
	pytest tests/test_query_operator_catalog.py -v

test-integration:
	@echo "Running integration tests (this will access real catalogs)..."
	pytest tests/test_integration.py -v --integration

test-coverage:
	pytest tests/test_query_operator_catalog.py \
		--cov=query_operator_catalog \
		--cov-report=term-missing \
		--cov-report=html \
		-v
	@echo ""
	@echo "Coverage report generated in htmlcov/index.html"

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache htmlcov .coverage
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
