# ADR-0004: Mocks declarativos detrás de clientes HTTP reales

## Estado
Aceptada.

## Contexto
Hace falta simular buró, cotización de llave, registro de vehículos, lector de
documentos y canal, y que quien clone el repo corra todo sin red. Los datos de
demostración deben poder crecer (más casos) sin tocar código.

## Decisión
- Los proveedores se simulan con **mappings JSON** (`mocks/mappings/`): `id`,
  `priority`, `request` (método, path, `bodyPatterns`) y `response`.
- Un motor (`mocks/engine.py`) resuelve por prioridad y especificidad; un 404
  explica el *near miss*. Un validador comprueba schema estricto, ids únicos,
  duplicados y *shadowing* (`make mocks-validate`).
- Los adaptadores (`adapters/*_http.py`) son **clientes HTTP reales**. En
  `mock` usan un transporte `httpx` que apunta al motor en proceso; en otros
  ambientes, `PROVIDERS_BASE_URL`. El mismo motor se sirve por HTTP para
  `docker compose`.
- El buró devuelve un reporte semi-crudo y **el adaptador lo normaliza**.

## Consecuencias
- Pasar a un proveedor real es cambiar una URL y revisar el contrato.
- Los clientes reales quedan probados por las pruebas de contrato.
- Hay que mantener los mappings alineados con las fechas de `fixed_today`.

## Alternativas descartadas
- Fixtures leídos por el adaptador: el adaptador real quedaría sin probar.
