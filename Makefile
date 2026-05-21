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

# --- Database ---

db-backup:
	./scripts/db-backup.sh

db-restore:
	@echo "Usage: make db-restore FILE=backups/stargate-YYYYMMDD-HHMMSS.sql.gz"
	./scripts/db-restore.sh $(FILE)

# --- Podman / Container ---

podman-build:
	podman build -t summit-demo-factory:latest -f Containerfile .

podman-build-scanner:
	podman build -t stargate-scanner:latest -f Containerfile.scanner .

podman-build-frontend:
	podman build -t stargate-frontend:latest -f Containerfile.frontend .

podman-build-all: podman-build-scanner podman-build-frontend

podman-up:
	podman-compose -f podman-compose.yml up -d

podman-down:
	podman-compose -f podman-compose.yml down

podman-logs:
	podman-compose -f podman-compose.yml logs -f

podman-logs-scheduler:
	podman-compose -f podman-compose.yml logs -f scheduler

podman-logs-babylon:
	podman-compose -f podman-compose.yml logs -f babylon-worker

# --- Local API dev ---

api-local:
	STARGATE_DATABASE_URL=postgresql://stargate:stargate@localhost:5432/stargate \
	uvicorn api.app:app --host 0.0.0.0 --port 8090 --reload

# --- Clean ---

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f test.db
