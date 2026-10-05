# Desarrollo local

## Primera vez

```bash
uv sync --group dev
make check          # lint + tipos + mocks + tests + eval, todo sin red
```

En WSL sobre `/mnt/c` el `uv sync` es lento. Un entorno fuera del
proyecto lo acelera:

```bash
export UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/ae-venv
```

## Ciclo de trabajo

| Quiero... | Comando |
|---|---|
| Ver un escenario completo | `make demo ARGS="--scenario 05 --timeline"` |
| Un solo test | `uv run pytest tests/domain/test_loan.py::test_nombre -q` |
| Cambiar una regla de negocio | editar `config/profile_policy.yaml` o `config/document_policy.yaml` y subir su `version` |
| Agregar un mock de proveedor | ver `mocks/README.md`, luego `make mocks-validate` |
| Regrabar el "LLM guionado" | `make record-llm` (no pisa el 09, que es a mano) |
| Probar con Mongo real | `docker compose up mongo -d && MONGO_URI=mongodb://localhost:27017 make integration` |
| Probar la API | `make run` y la sección "Cómo se ve la API" del README |
| Ver una conversación paso a paso | `make demo ARGS="--scenario 11 --timeline"` |

## Agregar un escenario

1. Un JSON en `fixtures/scenarios/NN-nombre.json` (copia uno existente).
2. Si necesita datos nuevos, mappings en `mocks/mappings/` (clientes
   `cust-*`, vehículos `veh-*`, documentos `doc-*`).
3. `make record-llm` para generar su script de LLM.
4. `make demo ARGS="--scenario NN"` y `make test`.

## Antes de entregar

`make check` en verde, `docker compose up --build` si se va a mostrar con
Mongo, y revisar la sección "Cómo usé IA" del README.
