# ADR-0003: El gate se reevalúa dentro de la tool

## Estado
Aceptada.

## Contexto
El error caro es un falso OK: marcar listo un expediente que no lo está. El
modelo puede equivocarse, ser manipulado por un documento o por el cliente, y
alguien puede invocar la tool por otro camino.

## Decisión
`mark_ready_for_lender` no confía en banderas guardadas ni en el agente:
**recalcula todo desde los datos** — revisión documental completa sobre los
documentos ligados, hash de la opción elegida recalculado desde sus insumos,
elegibilidad y perfil guardados — y evalúa 9 chequeos. Cualquier falla la
niega y lista los bloqueos. Cualquier duda ⇒ corrección o escalada, nunca OK.

Defensa en profundidad: transiciones validadas por el dominio, lista blanca
de tools por etapa, scope por principal, y este gate.

## Consecuencias
- Los documentos adjuntados *después* de validar, o una simulación alterada,
  se detectan (`test_gate_detecta_*`).
- Se mide con `make eval`: 0 falsos OK, 0 bypass; hay una prueba que rompe el
  gate para comprobar que la evaluación lo detectaría.
- Cuesta recalcular en cada intento; es aceptable frente al riesgo.
