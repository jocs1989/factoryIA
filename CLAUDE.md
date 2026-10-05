# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Agente (reto "Auto Equity agéntico", Senior AI Engineer) que opera de punta a punta **Elegibilidad del auto → Perfilamiento → Simulación → Datos y Comprobantes** de un crédito con garantía de auto. Stack: Python 3.12, FastAPI, LangGraph, MongoDB, Pydantic v2, `uv`. `PROPUESTA_AUTO_EQUITY.md` es el brief original (en español, con checklist de avance); `DECISIONES.md` es la fuente de verdad de decisiones y supuestos; `README.md` el uso. Identificadores en inglés; textos al usuario y documentación en español.

## Comandos

Todo corre sin red, sin API key y sin Mongo (`AGENT_ENV=mock`, ya exportado por el Makefile y por `tests/conftest.py`).

```bash
make check          # lint + tipos + mocks-validate + test + eval (lo que debe estar en verde)
make test           # pytest con cobertura (piso 85 %), excluye evals e integración
make eval           # evaluación adversarial offline: falla con un falso OK, un falso rechazo o un bypass del gate
make demo ARGS="--scenario 05 --timeline --policy llm"   # escenarios; ARGS opcional
make report         # métricas desde la bitácora que deja la demo
make run            # API en :8000 (mock)
make mocks-validate # valida mocks/mappings (schema estricto, ids, duplicados, shadowing)
make record-llm     # regraba mocks/llm_responses/ desde la política por reglas
make integration    # contra un Mongo real: MONGO_URI=mongodb://localhost:27017 make integration
uv run pytest tests/domain/test_loan.py::test_nombre -q  # un solo test
```

En WSL sobre `/mnt/c` el `uv sync` es muy lento: `export UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/ae-venv`. Líneas de 79 columnas (`ruff`); `mypy --strict` sobre `api config domain adapters tools mocks agent observability cli scripts ports.py` (los tests no se tipan y usan `# type: ignore` donde conviene).

## Arquitectura (hay que leer varios módulos para verla)

**Hexagonal.** `domain/` es puro (no importa nada de `adapters/` ni de `ports`); `ports.py` define todos los Protocols, DTOs y errores; `adapters/` los implementa.

**Una vuelta de conversación** (`agent/graph.py`, LangGraph): `load` relee el `Case` persistido → enruta por su `stage` → `act` pide **una** acción a la política (`agent/policy_rules.py` o `agent/policy_llm.py`) → si es tool la ejecuta por el ejecutor y vuelve a `load`; si es `Reply` termina el turno. `ESCALATED` pausa el grafo con `interrupt`; `agent/runner.py::resume_after_advisor` reanuda desde el checkpoint (o arranca limpio desde el caso persistido). `STAGE_TOOLS` es la lista blanca por etapa. Topes: 12 pasos y 3 violaciones por turno ⇒ `limit` escala.

**Ejecutor único** (`tools/executor.py`; lo usan agente y asesor con distinto `Principal`): 1 entrada válida → 2 scope → 3 `case_id` == sesión → 4 idempotencia (ventana de versiones; va *antes* de la etapa a propósito) → 5 etapa permitida → 6 ejecutar y validar salida → 7 `save(case, expected_version)` → 8 bitácora siempre, incluso en denegaciones. El catálogo de 15 tools está en `tools/catalog.py` (handlers + `build_catalog()`); `tools/spec.py` define el contrato.

**El gate** (`mark_ready_for_lender`) **recalcula todo desde `Case.data`**: `tools/casedata.py::review_case` (revisión documental de `domain/doc_review.py`) y `fresh_chosen_hash` (reconstruye la opción elegida y su hash), más `domain/readiness.py` (9 chequeos). No confía en banderas guardadas.

**Estado**: `Case` (`domain/case.py`) es inmutable; `transition()`/`with_data()` devuelven uno nuevo con `version + 1`. `ESCALATED` recuerda `escalated_from` y solo reanuda ahí o cierra. `Case.data` (dict JSON) guarda los hechos; no guarda el score del buró ni el texto crudo de documentos.

**Mocks** (`mocks/`): proveedores simulados con mappings JSON declarativos (`mocks/mappings/**`); los clientes `adapters/*_http.py` son HTTP reales y en `mock` usan `mocks/transport.py` (httpx en proceso). `adapters/providers.py::build_providers` los ensambla. Las fechas de los documentos se calculan contra `fixed_today` (2026-10-05, `config/mock.yaml`): no lo cambies.

**LLM** (patrón Strategy): `ports.LLMPort`; proveedores en `adapters/llm/` (`openai`, `deepseek`, `gemini`, `anthropic`, `scripted`, `ConstantLLM`); `registry.create_llm("gemini,openai")` arma cadena con fallback. `LLMPolicy` cae a `RuleBasedPolicy` ante error/acción inválida y abre circuito por caso tras 3 fallos. Prompts en `agent/prompts/*.md`.

**Escenarios y evaluación**: 12 escenarios en `fixtures/scenarios/` con scripts de LLM en `mocks/llm_responses/` (el 09 está escrito a mano: el "modelo" se deja engañar). `agent/scenarios.py` los corre; `observability/evaluation.py` arma el set etiquetado (escenarios + 19 variantes + un modelo hostil) y los intentos de bypass. `config/*.yaml`: un archivo por ambiente (`AGENT_ENV`), más `profile_policy.yaml`, `document_policy.yaml` (umbrales versionados) y `principals.yaml` (scopes).

## Reglas que no se deben violar

- **El LLM propone, el código dispone.** Veredictos, montos, cuotas, transiciones y el gate son código. Dinero siempre `Decimal`, nunca `float` (los inputs de monto rechazan floats).
- **Un falso OK cuesta más que un falso rechazo.** Cualquier duda ⇒ corrección o escalada, nunca OK. Si tocas el dominio, las tools o las políticas, corre `make eval`: debe dar 0 falsos OK y 0 bypass.
- **No saltarse el ejecutor.** Toda acción pasa por `Executor.call`; las tools con efecto validan etapa y versión. No agregues "caminos traseros" para el asesor: es otro principal con otros scopes.
- **Los textos de documentos y del cliente son DATO.** `read_document` no devuelve texto crudo; el modelo nunca fija `case_id`.
- **Umbrales en YAML**, no hardcodeados; sube su `version` al cambiarlos. Casos límite probados: score 579/580/640/700, ingreso exactamente 10 %/25 %, cuota exactamente 35 %.
- Si cambias un mapping de `mocks/`, corre `make mocks-validate`; si cambias el comportamiento de la política por reglas, corre `make record-llm` (no pisa el 09).
- Supuestos nuevos van a `DECISIONES.md` §6; decisiones nuevas, a un ADR en `docs/decisions/`.
- Honestidad sobre lo no probado: Mongo real, los adaptadores de OpenAI/Gemini/DeepSeek/Anthropic con claves reales y el OCR real **no** se han ejercitado (ver `DECISIONES.md` §12).
