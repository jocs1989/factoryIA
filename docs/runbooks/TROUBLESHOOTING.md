# Diagnóstico

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `AGENT_ENV='x' sin archivo` al arrancar | no existe `config/x.yaml` | usa `mock`, `dev` o `prod`, o crea el YAML |
| La API responde 401 al asesor | falta `ADVISOR_API_KEY` en la API o en la CLI, o no coinciden | exporta la misma clave en ambos; en `mock` **tampoco** hay asesor anónimo |
| `STAGE_NOT_ALLOWED` | se llamó una tool fuera de su etapa | revisa `get_case_snapshot`; el controlador es quien avanza las etapas |
| `STALE_VERSION` | otro actor modificó el caso entre la lectura y el guardado | relee el estado y reintenta |
| `NOT_READY` en `mark_ready_for_lender` | el gate encontró algo; el mensaje lista los bloqueos | corrige lo indicado (`documents_valid`, `payment_capacity`...) o escala |
| Un documento "venció" en la demo | las fechas de los fixtures se calculan contra `fixed_today` (2026-10-05) | no cambies `fixed_today` de `mock`, o regenera los mappings |
| El agente repite siempre lo mismo | tope de pasos o de intentos inválidos | busca `TOOL_NOT_WHITELISTED` o `AGENT_LIMIT` en la bitácora; se escala solo |
| Un proveedor devuelve 404 en los mocks | ningún mapping coincide | la respuesta trae `near_miss` con lo esperado vs. lo recibido |
| El LLM "no responde" | circuito abierto: `LLM_FALLBACK_TO_RULES` en la bitácora | revisa la clave del proveedor; el caso sigue por reglas |
| `mongomock` pasa pero Mongo real falla | diferencias del servidor | `make integration` contra un `mongod` real |

## Ver qué pasó en un caso

```bash
make demo ARGS="--audit reports/audit.jsonl"
grep '"case_id":"s05"' reports/audit.jsonl | jq -r '[.ts[11:19], .principal, .name, .outcome, (.reason_codes|join(","))] | @tsv'
make report
```

La bitácora guarda **solo hashes de entradas**, nunca datos personales en claro.
