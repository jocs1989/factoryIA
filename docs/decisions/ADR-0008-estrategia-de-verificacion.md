# ADR-0008: Estrategia de verificación del comportamiento

## Estado
Aceptada (2026-10-08).

## Contexto
La auditoría señaló dos debilidades: (1) el set de evaluación lo etiqueté yo con fixtures míos, así que "0 falsos OK" vale sobre ese set y no se generaliza; (2) los guiones del "LLM" se graban de la política por reglas, por lo que "ambas políticas dan lo mismo" prueba el cableado, no la calidad de un modelo.

## Decisión
Verificar en capas que no dependen de lo que el autor imaginó:
1. **Ejemplos y casos límite** (`tests/domain`, `tests/tools`): umbrales exactos (579/580, 10 %/25 %, 35 %).
2. **Propiedades** con `hypothesis` (`tests/domain/test_properties.py`): monotonía de la cuota, el tope LTV incluye la llave, menos ingreso nunca es mejor veredicto, simetría de la comparación de nombres, la máquina de estados.
3. **Fuzzing** (`tests/evals/test_fuzz.py`): el azar elige acciones, argumentos, principals e incluso la respuesta del modelo. Invariantes: sin excepciones, los estados terminales no cambian, todo caso en `READY_FOR_LENDER` pasa el gate recalculado desde cero, las etapas son alcanzables por aristas permitidas y el esquema se cumple.
4. **Evaluación etiquetada** (`make eval`): el set adversarial y un modelo hostil.
5. **Un modelo real** (`make smoke-llm`) para lo que ningún guion puede probar.

## Consecuencias
- Las propiedades encontraron un bug real (nombres con letras fuera del latín básico no coincidían consigo mismos).
- El fuzz exigió precisar una invariante: una tool puede encadenar varias transiciones válidas en una llamada.
- Con semillas nuevas (200 del ejecutor y 60 del LLM caótico) las invariantes se sostuvieron y el fuzz llegó a todos los estados.
- **Límite que sigue en pie:** ninguna de estas capas mide la *calidad conversacional* de un modelo real, ni sustituye una evaluación con casos etiquetados por el negocio. Con Azure OpenAI solo se ejercitaron tres escenarios.

## Alternativas descartadas
- **Medir solo cobertura de líneas:** un 90 % de cobertura no dice nada sobre las invariantes.
- **Un LLM como juez:** reintroduce no determinismo en la prueba de lo que debe ser determinista.
