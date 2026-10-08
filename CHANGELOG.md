# Changelog

Todos los cambios relevantes de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
el proyecto usa [versionado semántico](https://semver.org/lang/es/).

## [0.2.0] - 2026-10-08

Endurecimiento de arquitectura y operación tras una auditoría interna.

### Added
- Esquema tipado de `Case.data` (`domain/facts.py`, `extra="forbid"`): una clave o tipo inesperado falla al escribir y al cargar (ADR-0007).
- Validación de configuración al arrancar (`config/validation.py`): prod rechaza anónimo, `fixed_today`, demo, LLM guionado, mocks y claves débiles (ADR-0006).
- `SessionStore`, `AttemptLimiter` y `RateLimiter` (`api/security.py`): sesiones con vencimiento y tope, bloqueo temporal de verificación y límite de mensajes por sesión.
- Middleware con `X-Correlation-ID`, cabeceras seguras, tope de cuerpo y error interno sin traza; endpoint `/ready`.
- Logging estructurado con redacción de CURP, RFC, correo, teléfonos y credenciales (`observability/logging.py`).
- Reintento con backoff exponencial y jitter ante errores transitorios del LLM (`adapters/llm/retry.py`).
- Proveedor Azure OpenAI y `make smoke-llm` para probar un modelo real sin guardar credenciales.
- Tokens, modelo y costo estimado del LLM en `make report` (tarifas en `config/llm_pricing.yaml`, sin valores inventados).
- Índices de MongoDB al arrancar y expiración (TTL) de la idempotencia.
- Pruebas de propiedades (`hypothesis`) y fuzzing del ejecutor y de un LLM caótico contra las invariantes del gate (ADR-0008).
- `gate_decision`: el gate como función pura, usada por la tool y por las pruebas.
- Prueba de humo HTTP (`make smoke`), SAST (`make sast`), compuerta de docstrings (`make docstrings`) y CI de GitHub Actions.
- `make start|stop|logs|status|clean|help`, puertos configurables y una interfaz visual de prueba (`web/`).
- Docstrings en toda la superficie pública (474 de 474) y documentación de operación (SLOs, rollback, NFR).

### Changed
- `tools/catalog.py` (1 076 líneas) se divide en un handler por etapa bajo `tools/handlers/`.
- `adapters/` ya no depende de `mocks/`: el cableado de mocks vive en la raíz de composición (`mocks/wiring.py`).
- La imagen de Docker corre sin privilegios, con dependencias congeladas, sistema de archivos de solo lectura y healthchecks.
- Los turnos de un mismo caso se serializan dentro del proceso.
- El bloqueo por intentos de verificación es temporal (antes era permanente).
- `make eval` ahora también corre `tests/evals` (fuzzing), que antes no se ejecutaba en CI.

### Fixed
- Un nombre con letras fuera del latín básico (p. ej. `Ŋ`, `Ł`) no coincidía ni consigo mismo.
- Montos formateados con `float` en el texto al cliente; ahora `Decimal`.
- `/ready` declaraba listo un servicio que no podía escribir su bitácora y cada conversación respondía 500.
- Crear un caso repetido devolvía 500; ahora 409. Los 422 ya no devuelven los valores enviados.

### Security
- Sin `Co-authored-by` en los commits nuevos, según el estándar de la organización (los 15 commits anteriores aún lo llevan; ver `docs/decisions/ADR-0006-operacion-endurecida.md`).

## [0.1.0] - 2026-10-05

Primera versión: el agente de punta a punta.

### Added
- Dominio puro: elegibilidad, perfil, simulación, validaciones documentales, gate y máquina de estados.
- Puertos y adaptadores (MongoDB, memoria, JSONL, clientes HTTP de proveedores y motor de mocks declarativo).
- Capa de 15 tools con ejecutor único (scope, caso ligado, idempotencia, etapa, versión y bitácora).
- Agente en LangGraph con políticas por reglas y por LLM (OpenAI, DeepSeek, Gemini, Anthropic) y respaldo.
- API FastAPI, CLIs, 12 escenarios reproducibles y evaluación adversarial.
