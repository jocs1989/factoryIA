# Operación: SLOs, alertas y rollback

> **Estado de los números.** Los SLOs son **objetivos propuestos** para discutir
> con el negocio: no se midieron en producción (no existe). Las cifras de
> referencia salen de `docs/architecture/NFR.md`, medidas con mocks.
> Definirlos y el rollback *antes* de producción es una regla de la organización.

## 1. SLOs propuestos

| SLI (de dónde sale) | Objetivo | Por qué |
|---|---|---|
| **Falsos OK** (reversión del asesor sobre una muestra de casos `READY_FOR_LENDER`) | **0 %** en el set offline; < 0,5 % en la muestra de producción | el error caro: un expediente malo llega a la financiera |
| Disponibilidad de `/ready` | 99,5 % mensual | el canal no debe perder clientes |
| Latencia de un turno **sin** LLM (p95) | < 500 ms | referencia medida: 128 ms en secuencial |
| Latencia de un turno **con** LLM (p95) | < 8 s | el modelo domina; ≈15 llamadas por caso repartidas en 4 turnos |
| Tasa de caída a reglas (`LLM_FALLBACK_TO_RULES` sobre decisiones del LLM) | < 5 % | indica un proveedor degradado |
| Tasa de escalada a humano | observar; alerta si se duplica en 1 día | cambio de mezcla de casos o un modelo manipulado |
| Violaciones de invariantes (`type=invariant`) | **0** | cualquiera es un defecto |

El presupuesto de error de los falsos OK es **cero**: una sola reversión confirmada
abre un incidente y congela el modo autónomo (ver §3).

## 2. Qué mirar y alertar

| Señal | Fuente | Alerta |
|---|---|---|
| `invariant_violations > 0` | `make report` / bitácora `type=invariant` | **inmediata** |
| `mark_ready_for_lender` negado en ráfaga | bitácora, `outcome=denied` con `NOT_READY` | revisar: un modelo manipulado intenta saltarse el gate |
| `circuit_open` o `LLM_FALLBACK_TO_RULES` creciendo | bitácora `type=llm` | proveedor de LLM caído o clave vencida |
| `/ready` 503 | sonda del orquestador | Mongo o la bitácora no responden |
| 429 en `/verify` | log `verificacion fallida` | posible fuerza bruta de un teléfono |
| Costo del LLM por caso | `make report` (requiere `config/llm_pricing.yaml`) | desviación > 30 % |

## 3. Rollback y apagado de emergencia

Todo cambio debe poder deshacerse **sin desplegar código**:

| Quiero... | Acción | Efecto |
|---|---|---|
| Quitar el LLM ya | `POLICY=rules` y reiniciar | el agente decide solo con reglas; el caso no se pierde |
| Cambiar de proveedor de LLM | `LLM_BACKEND=gemini,openai` | cadena con respaldo y circuit breaker |
| Deshacer un cambio de umbrales | revertir el YAML (`config/*_policy.yaml`) | cada decisión guarda la `rule_version` con que se tomó |
| Volver a la versión anterior | desplegar el tag anterior de la imagen | los casos persistidos siguen siendo válidos si el esquema no cambió (ADR-0007) |
| Parar la entrada de casos nuevos | quitar la credencial del canal | los casos abiertos los sigue atendiendo el asesor |
| Congelar el modo autónomo | `POLICY=rules` y que el asesor apruebe `mark_ready_for_lender` | pasa a modo asistido |

**Cambio de esquema de `Case.data`:** un cambio incompatible exige migración;
los casos con la forma vieja fallan al cargar (es deliberado). Hacer rollback
del código sin deshacer la migración deja casos ilegibles: migrar siempre con
*expand/contract* (agregar campos opcionales primero, retirarlos después).

## 4. Despliegue

1. `make check` en verde y CI en verde (`check`, `integration` y `smoke`).
2. Configuración: variables por entorno; `AGENT_ENV=prod` valida y se niega a arrancar si es insegura (`config/validation.py`).
3. Primero **modo sombra** (el agente propone y registra, el humano ejecuta), luego asistido, luego autónomo por etapa solo donde las métricas lo justifiquen (`DECISIONES.md` §10).
4. Verificar `/ready` y la prueba de humo (`make smoke`) tras cada despliegue.

## 5. Datos

- **Bitácora (JSONL):** solo hashes de entradas, nunca datos personales. Definir retención y rotación; hoy no hay política.
- **Idempotencia:** expira sola a los 7 días (índice TTL).
- **Casos:** contienen datos personales **sin cifrar en reposo** (pendiente: cifrado a nivel de campo y política de retención).
- **Migrar de la imagen anterior (usuario root) a esta:** un volumen `audit` creado por la imagen vieja pertenece a root y la API (ahora sin privilegios) **se niega a arrancar** con `dependencia no lista al arrancar: PermissionError`. Recrear el volumen (`make clean`) o `chown 10001 /data`.

## 6. Secretos

Solo por variables de entorno inyectadas desde un gestor de secretos; nunca en el
código. Las claves de demo de `docker-compose.yml` empiezan con `demo-` y **prod
las rechaza**. Rotar una clave = cambiar la variable y reiniciar. Las claves del
canal y del asesor son distintas a propósito.
