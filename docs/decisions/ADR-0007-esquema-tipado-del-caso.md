# ADR-0007: Esquema tipado de `Case.data`

## Estado
Aceptada (2026-10-08).

## Contexto
`Case.data` era un `dict[str, Any]`: flexible para persistir en Mongo, pero las tools y el gate leían sus claves como texto. Una clave mal escrita (`verifed_income`) no fallaba: se perdía en silencio, y el score del buró o el texto crudo de un documento podían guardarse sin que nada lo impidiera.

## Decisión
Mantener el documento JSON flexible para persistir, pero **fijar su forma** con `CaseFacts` (`domain/facts.py`, `extra="forbid"`) y validarla en cada escritura (`with_data`) y en cada construcción o carga de un `Case`, incluida la lectura desde el repositorio.

## Consecuencias
- Una clave o un tipo inesperado falla al instante, antes de persistir.
- El esquema es el contrato entre tools, gate y repositorio; las pruebas que usaban claves inventadas se corrigieron (un efecto buscado).
- Privacidad por diseño: el esquema no tiene dónde guardar el score, el reporte del buró ni el texto crudo de los documentos.
- Agregar un campo exige editar `CaseFacts`; es una fricción deliberada.
- Un caso persistido con una forma antigua falla al cargar: un cambio de esquema pide una migración.

## Alternativas descartadas
- **Modelos tipados como fuente de verdad (sin dict):** más seguro, pero reescribe todos los handlers y el adaptador de Mongo; se deja como evolución.
- **Validar solo en las pruebas:** no protege la producción.
- **`extra="allow"`:** conserva la flexibilidad, pero permite exactamente el error que se quiere evitar.
