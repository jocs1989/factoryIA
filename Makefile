# Atajos del ciclo local. `make check` es lo que debe estar en verde antes
# de entregar. Todo corre sin red ni credenciales (AGENT_ENV=mock).
COVERAGE_MIN ?= 85
export AGENT_ENV ?= mock
PKGS = api config domain adapters tools mocks agent observability cli scripts

.PHONY: sync lint types test eval demo report run mocks-validate mocks-serve \
	record-llm integration up check

sync:
	uv sync --group dev

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy $(PKGS) ports.py

# Reglas, tools, agente, API y CLIs. La evaluacion adversarial va aparte.
test:
	mkdir -p reports
	uv run pytest tests --ignore=tests/evals --ignore=tests/integration \
		--cov=domain --cov=tools --cov=agent --cov=api --cov=adapters \
		--cov=mocks --cov=observability --cov-report=term-missing:skip-covered \
		--cov-fail-under=$(COVERAGE_MIN) -q

# Set etiquetado con documentos adversariales. Falla si hay un falso OK.
eval:
	uv run python -m cli.eval

# Todos los escenarios, sin red. `make demo ARGS="--scenario 05 --timeline"`.
demo:
	uv run python -m cli.demo $(ARGS)

# Metricas del reto desde la bitacora que deja la demo.
report:
	uv run python -m cli.demo --audit reports/audit.jsonl > /dev/null
	uv run python -m cli.report --audit reports/audit.jsonl

run:
	uv run uvicorn api.app:app --reload

mocks-validate:
	uv run python -m mocks.validate

mocks-serve:
	uv run uvicorn mocks.server:app --port 9000

# Regraba mocks/llm_responses/ desde la politica por reglas.
record-llm:
	uv run python -m scripts.record_llm_scripts

# Contra un MongoDB real: `MONGO_URI=mongodb://localhost:27017 make integration`
integration:
	uv run pytest tests/integration -q

up:
	docker compose up --build

check: lint types mocks-validate test eval
