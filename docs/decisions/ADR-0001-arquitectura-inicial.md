# ADR-0001: Arquitectura inicial

## Estado
Aceptada.

## Contexto
El reto pide un agente que opere un tramo de un proceso real con tools,
estado, validaciones y trazabilidad, sobre un sistema que cambia cada semana
y que hoy operan humanos. Stack indicado: FastAPI, LangGraph y MongoDB.

## Decisión
- **Hexagonal**: dominio puro, puertos en `ports.py`, adaptadores en
  `adapters/`. Las reglas se prueban sin red.
- **LangGraph como controlador de etapas determinista**; el LLM (o las
  reglas) solo elige la siguiente acción dentro de una etapa y con lista
  blanca de tools.
- **FastAPI** expone el agente (cliente) y el mismo ejecutor de tools (asesor).
- **MongoDB** persiste casos, tickets e idempotencia; el checkpointer del
  grafo puede ir en Mongo.
- Todo lo que mueve dinero o estado es **código**; los umbrales viven en YAML
  versionado.

## Consecuencias
- Cambiar de proveedor o de base de datos es escribir un adaptador.
- El agente es más predecible y auditable que uno libre, a costa de menos
  flexibilidad conversacional.
- Hay más código que un prototipo con un solo prompt; se compensa con
  pruebas y con una evaluación que demuestra el comportamiento.

## Alternativas descartadas
- Agente libre con un solo prompt: difícil de acotar y de auditar.
- Estado solo en el framework de orquestación: efímero y no visible al asesor.
- Llamar proveedores desde los nodos del grafo: acopla negocio e infraestructura.
