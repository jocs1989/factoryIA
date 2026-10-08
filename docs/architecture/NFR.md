# Requisitos no funcionales (FURPS+)

Cada requisito dice **qué se exige, cómo se comprueba y en qué estado está**.
Las cifras son medidas en esta máquina con proveedores simulados; donde no se
midió, se dice. Estados: **cumple**, **parcial**, **pendiente**.

## F: Funcionalidad

| Requisito | Evidencia | Estado |
|---|---|---|
| Opera las cuatro etapas de punta a punta | 12 escenarios (`make demo`) y prueba de humo HTTP contra la pila de Docker | cumple |
| Un falso OK es inaceptable | `make eval`: 0 falsos OK, 0 falsos rechazos y 0 bypass del gate; fuzzing con 260 semillas nuevas sin violar invariantes | cumple |
| Valida ingreso, moneda, período, identidad, domicilio, vigencia, titularidad, CURP/RFC y aritmética | `tests/domain/test_doc_review.py` (con los límites exactos) | cumple |
| Escalada a humano y reanudación | `tests/agent/test_graph.py`, `tests/api/test_api.py` y la interfaz web | cumple |
| Calidad conversacional de un modelo real | 3 escenarios con `gpt-5.4-mini` (Azure) | **parcial** |

## U: Usabilidad

| Requisito | Evidencia | Estado |
|---|---|---|
| Levantar todo con un comando | `make start` (imprime las URLs) | cumple |
| Probar sin saber usar la API | interfaz visual en `web/` | cumple |
| Errores accionables | la configuración inválida lista todos los problemas; `docs/runbooks/TROUBLESHOOTING.md` | cumple |
| Accesibilidad de la interfaz de prueba | no se auditó | pendiente |

## R: Confiabilidad

| Requisito | Evidencia | Estado |
|---|---|---|
| Si el LLM falla, el caso no se pierde | circuit breaker por caso y respaldo a reglas (escenario 12, `test_policies`) | cumple |
| Reintentos solo ante fallos transitorios | `RetryingLLM` con backoff exponencial y jitter (`test_llm_retry.py`) | cumple |
| Sin escrituras que se pisen | control optimista por versión (Mongo real) y un turno a la vez por caso | cumple |
| Reintentos sin efectos duplicados | idempotencia con ventana de versiones | cumple |
| No operar sin auditoría | el arranque falla y `/ready` da 503 si no se puede escribir la bitácora | cumple |
| Recuperación tras reinicio | el caso persistido es la verdad; la reanudación arranca limpia sin checkpoint | cumple |
| Alta disponibilidad (Multi-AZ, varias réplicas) | sesiones y límites en memoria de un proceso | **pendiente** |

## P: Rendimiento

Medido contra la pila de Docker, política por reglas, mocks, 1 proceso:

| Escenario | Resultado |
|---|---|
| 25 conversaciones secuenciales (100 turnos) | turno p50 52 ms, p95 128 ms, máximo 140 ms; 3,2 conv/s; 25 de 25 llegan a READY |
| 50 conversaciones con 10 en paralelo (200 turnos) | turno p50 652 ms, **p95 1 747 ms**; 2,8 conv/s; 50 de 50 llegan a READY |

**Lectura honesta:** un proceso se satura cerca de 3 conversaciones por segundo y
más concurrencia solo sube la latencia (comparten el GIL). Con un LLM real el
tiempo lo domina el modelo (≈15 llamadas y ≈19 mil tokens de entrada por caso
en las pruebas). Escalar exige varias réplicas y, antes, mover las sesiones a un
almacén compartido. No se hizo una prueba de carga con un LLM real.

## S: Soportabilidad y mantenimiento

| Requisito | Evidencia | Estado |
|---|---|---|
| Reglas de negocio cambian sin tocar código | umbrales en YAML con `version`; la decisión guarda la versión de regla | cumple |
| Cambiar de proveedor es escribir un adaptador | puertos, contratos probados por adaptador; el código de producción no depende de `mocks/` | cumple |
| Superficie pública documentada | 480 de 480 docstrings, con compuerta en CI (≥ 90 %) | cumple |
| Módulos de tamaño razonable | el mayor es `tools/handlers/documents.py` (≈280 líneas) | cumple |
| Observabilidad | bitácora de decisiones, `make report`, logs JSON con correlación y sin datos personales | cumple |
| Trazas distribuidas / métricas en vivo | no hay OpenTelemetry ni Prometheus | pendiente |

## +: Restricciones de diseño, implementación, interfaz y físicas

| Tema | Decisión | Estado |
|---|---|---|
| Arquitectura | hexagonal; el dominio no importa infraestructura (ADR-0001) | cumple |
| Seguridad | mínimo privilegio, defensa en profundidad, amenazas en `docs/THREAT_MODEL.md` | cumple |
| Privacidad | el score y el texto crudo no tienen dónde guardarse (ADR-0007); logs redactados | cumple |
| Datos en reposo | `Case.data` con datos personales **sin cifrar** | **pendiente** |
| Retención | la idempotencia expira a 7 días; la bitácora no tiene política | **parcial** |
| Interfaz | REST con errores tipados; sin versionado de ruta (`/v1`) | **parcial** |
| Infraestructura como código | solo `docker-compose`; sin Terraform ni etiquetado de nube | **pendiente** |
| Contenedor | sin privilegios, solo lectura, sin capacidades, `uv.lock` congelado | cumple |
