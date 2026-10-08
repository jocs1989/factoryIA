# ADR-0005: Proveedores de LLM como estrategias intercambiables

## Estado
Aceptada.

## Contexto
Se quiere poder usar OpenAI, Gemini, DeepSeek o Anthropic sin tocar el agente,
tener respaldo si uno falla, y correr todo sin API key.

## Decisión
- Puerto `LLMPort` (`complete(LLMRequest) -> LLMResponse`) y `LLMError` con
  `retryable`. Cada proveedor es una estrategia sobre una base HTTP común
  (Template Method). OpenAI y DeepSeek comparten el protocolo.
- `create_llm("gemini,openai")` arma una cadena con fallback y **circuit
  breaker** (Decorator). `LLM_BACKEND` acepta un nombre o una cadena.
- `httpx` directo, sin SDKs.
- `LLMPolicy` envuelve a `RuleBasedPolicy`: ante error o acción inválida
  decide la regla; el circuito se abre por caso tras 3 fallos seguidos.
- El modo por defecto es `scripted`: respuestas grabadas desde la política por
  reglas (`make record-llm`), con la de la inyección (09) escrita a mano.

## Consecuencias
- Agregar un proveedor es una entrada en `registry.PROVIDERS`.
- Los adaptadores se prueban sin red con el formato documentado de cada API,
  pero **no se han ejercitado con claves reales**.
- El LLM guionado demuestra el cableado y la validación, no la calidad de un
  modelo real; eso se mide aparte.

## Alternativas descartadas

- **SDK de cada proveedor:** más dependencias y pruebas que exigen red; `httpx` directo se prueba con transportes simulados.
- **Una librería multi-proveedor (p. ej. LiteLLM):** oculta el contrato de errores y el formato de cada API, justo lo que se quiere controlar y probar.
- **Un solo proveedor fijo:** una caída del proveedor tumbaría la operación; la cadena con respaldo y circuit breaker lo evita.
