.PHONY: install test test-cov test-schemas test-rubrics test-api test-db \
       validate-rubrics build-report \
       podman-build podman-up podman-down podman-logs \
       api-dev clean

# --- Install ---

install:
	pip install -e ".[dev]"

install-api:
	pip install -e ".[dev,api]"

# --- Tests ---

test:
	pytest -v -m "not integration"

test-all:
	pytest -v

test-integration:
	pytest -v -m integration

test-cov:
	pytest -v --cov=api --cov=cli --cov=reports --cov-report=term-missing

test-schemas:
	pytest -v tests/test_schemas.py

test-rubrics:
	pytest -v tests/test_rubric_loader.py tests/test_rubric_evaluator.py

test-api:
	pytest -v tests/test_api.py

test-db:
	pytest -v tests/test_db.py

# --- Validation ---

validate-rubrics:
	python -m api.app.rubric_loader rubrics/platform/

build-report:
	python -m reports.build_report

# --- Podman / Container ---

podman-build:
	podman build -t summit-demo-factory:latest -f Containerfile .

podman-build-test:
	podman build -t summit-demo-factory-test:latest -f Containerfile.test .

podman-up:
	podman-compose -f podman-compose.yml up -d

podman-down:
	podman-compose -f podman-compose.yml down

podman-logs:
	podman-compose -f podman-compose.yml logs -f

podman-db:
	podman run -d --name sdf-db \
		-e POSTGRESQL_USER=sdf \
		-e POSTGRESQL_PASSWORD=sdf \
		-e POSTGRESQL_DATABASE=summit_demo_factory \
		-p 5432:5432 \
		registry.redhat.io/rhel9/postgresql-15:latest

podman-db-stop:
	podman stop sdf-db && podman rm sdf-db

# --- Local API dev ---

api-dev:
	DATABASE_URL=postgresql://sdf:REDACTED@localhost:5432/summit_demo_factory \
	uvicorn api.app.main:app --host 0.0.0.0 --port 8080 --reload

# --- Clean ---

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f test.db
