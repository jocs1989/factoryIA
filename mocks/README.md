# Motor de mocks de proveedores

Los proveedores externos (buró, cotización de llave, registro de vehículos,
lector de documentos, canal) se simulan con **mappings JSON declarativos**.
Los clientes del sistema (`adapters/*_http.py`) son clientes HTTP reales: en
`mock` hablan con el motor en proceso (sin red); en otros ambientes apuntan a
`PROVIDERS_BASE_URL`. Cambiar a un proveedor real es cambiar una URL.

## Un mapping

```json
{
  "id": "autoequity.bureau.v1.query.cust_s01",
  "domain": "bureau",
  "priority": 100,
  "request": {
    "method": "POST",
    "path": "/api/bureau/query",
    "bodyPatterns": [{"jsonPath": "$.customer_id", "equalTo": "cust-s01"}]
  },
  "response": {"status": 200, "jsonBody": {"score": 650, "accounts_delinquent": 0, "history_months": 48}}
}
```

Un archivo `.json` puede traer un mapping o una lista.

| Campo | Qué es |
|---|---|
| `id` | único; `^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+$` |
| `priority` | menor gana (default 100); a igual prioridad, el más específico (más `bodyPatterns`) |
| `request.bodyPatterns` | `jsonPath` (`$.a.b`) o `jsonPathConcat` contra `equalTo`; los booleanos se comparan como `true`/`false` |
| `response.jsonBody` | admite `{{request.body.CAMPO}}` |
| `response.faultDelayMs` | espera artificial: para probar *timeouts* |

El schema es **estricto**: un campo mal escrito (`bodypatterns`) falla al
validar en vez de ignorarse.

## Casos fijos

Los datos son ficticios. Convención: `cust-sNN` / `veh-sNN` para el escenario
NN; `doc-good-*` son los documentos correctos y `doc-sNN-*`/`doc-vNN-*` los
casos problemáticos. Variantes de perfil: `cust-a` (banda A), `cust-decline`,
`cust-delinquent`, `cust-thin`, `cust-noscore` y `cust-fail` (el buró responde
503). Las fechas de los documentos se calculan contra `fixed_today`
(2026-10-05) de `config/mock.yaml`.

## Comandos

```bash
make mocks-validate     # schema, ids únicos, duplicados y shadowing
make mocks-serve        # el mismo motor por HTTP en :9000
curl -s localhost:9000/_mock/health
```

Si ningún mapping coincide, la respuesta es 404 con `near_miss`: qué campo
esperaba cada candidato y qué llegó.
