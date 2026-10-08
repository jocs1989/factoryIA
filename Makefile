# Atajos del ciclo local. `make check` es lo que debe estar en verde antes
# de entregar. Todo corre sin red ni credenciales (AGENT_ENV=mock).
COVERAGE_MIN ?= 85
export AGENT_ENV ?= mock
PKGS = api config domain adapters tools mocks agent observability cli scripts

.PHONY: sync lint types test eval demo report run mocks-validate mocks-serve \
	record-llm smoke-llm integration up start stop logs status clean check help

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
	uv run pytest tests/evals -q -p no:cacheprovider

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

# Prueba de humo con un LLM real. La clave se lee solo en memoria:
#   make smoke-llm ENV_FILE=/ruta/al/env SCENARIO=01
smoke-llm:
	uv run python -m scripts.smoke_llm --env-file "$(ENV_FILE)" --scenario $(or $(SCENARIO),01) --timeline

# Contra un MongoDB real: `MONGO_URI=mongodb://localhost:27017 make integration`
integration:
	uv run pytest tests/integration -q

# --- Levantar todo (api + mocks + mongo + interfaz) ------------------------
up:
	docker compose up --build

# Segundo plano: construye, espera a que la API responda y muestra las URLs.
start:
	docker compose up --build -d
	@echo "esperando a que la API responda..."
	@for i in $$(seq 1 60); do \
		curl -sf http://localhost:8000/health >/dev/null && break; sleep 2; done
	@curl -sf http://localhost:8000/health >/dev/null \
		|| { echo "la API no respondio: revisa 'make logs'"; exit 1; }
	@echo ""
	@echo "  Interfaz visual : http://localhost:8080"
	@echo "  API (docs)      : http://localhost:8000/docs"
	@echo "  Mocks           : http://localhost:9000/_mock/health"
	@echo "  Detener         : make stop     Logs: make logs"

stop:
	docker compose down

logs:
	docker compose logs -f --tail=100

status:
	docker compose ps

# Detiene todo y borra los volumenes (bitacora y datos de Mongo de la demo).
clean:
	docker compose down -v

help:
	@echo "make start    levanta todo con Docker (interfaz en :8080)"
	@echo "make stop     lo detiene"
	@echo "make demo     12 escenarios sin Docker ni red"
	@echo "make check    lint + tipos + tests + evaluacion"

check: lint types mocks-validate test eval
