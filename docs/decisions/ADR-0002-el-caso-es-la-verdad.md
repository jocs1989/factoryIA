# ADR-0002: El caso persistido es la verdad; el grafo es efímero

## Estado
Aceptada.

## Contexto
El agente conversa en varios turnos y a veces se pausa (escalada). Un asesor
y el agente pueden actuar sobre el mismo caso. Los procesos se reinician.

## Decisión
- La fuente de verdad es el agregado `Case` (inmutable, con `version`) en el
  repositorio. El estado del grafo (mensajes, paso actual) es auxiliar.
- Tras **cada** acción el grafo relee el caso y enruta por su `stage`.
- Las escrituras usan control optimista (`save(case, expected_version=...)`).
- La escalada **pausa** el grafo con `interrupt`; al resolver el asesor, el
  runner reanuda desde el checkpoint, o, si no existe (reinicio), arranca
  limpio desde el caso persistido.
- Las respuestas ya entregadas antes de la pausa no se repiten al reanudar.

## Consecuencias
- Reiniciar el proceso no pierde casos. Un asesor ve el mismo estado que el
  agente. Un conflicto de versión se reintenta con el estado fresco.
- Hay que cuidar que lo importante viva en `Case.data` y no solo en el grafo.
