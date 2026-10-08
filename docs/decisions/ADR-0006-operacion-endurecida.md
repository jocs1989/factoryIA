# ADR-0006: Operación endurecida de la API

## Estado
Aceptada (2026-10-08).

## Contexto
Una auditoría interna encontró que la API funcionaba pero no era operable en serio: las sesiones crecían sin límite en memoria, un tercero podía dejar fuera al cliente legítimo con cinco verificaciones fallidas (el bloqueo era permanente), no había logs ni correlación, un volumen sin permisos dejaba el servicio "listo" mientras toda conversación daba 500, y la configuración insegura de producción solo se descubría en uso.

## Decisión
- **Fail-fast al arrancar** (`config/validation.py`): prod rechaza principal anónimo, `fixed_today` (congelaría la vigencia de los documentos), endpoints de demo, LLM guionado, mocks y claves débiles o de demostración. Todos los problemas se reportan juntos y sin imprimir valores.
- **Sin bitácora no se opera:** el arranque falla y `/ready` devuelve 503 si no se puede escribir.
- **Sesiones** con vencimiento, purga y tope de tamaño; **bloqueo temporal** (no permanente) de verificación; **límite de 30 mensajes por minuto y sesión** para proteger el costo del LLM.
- **Observabilidad:** `X-Correlation-ID` válido o generado, logs JSON con redacción de datos personales por nombre de campo y por contenido, error interno sin traza hacia el cliente.
- **Contenedor mínimo:** usuario sin privilegios, sistema de archivos de solo lectura, sin capacidades de Linux, `uv.lock` congelado y healthchecks.
- **Un turno a la vez por caso** dentro del proceso (el control de versión sigue protegiendo entre réplicas).

## Consecuencias
- Un ambiente mal configurado no arranca, con un mensaje accionable.
- Las sesiones, el bloqueo y el límite de tasa viven en memoria de **un** proceso: escalar a varias réplicas exige moverlos a un almacén compartido con TTL. Las clases están pensadas para ese reemplazo.
- **Medido:** con la política por reglas un proceso atiende ~3 conversaciones/s; con 10 en paralelo el rendimiento no mejora (GIL) y el p95 de un turno pasa de 128 ms a 1,7 s. Con un LLM real el tiempo lo domina el modelo.
- Los 15 commits anteriores a este ADR llevan `Co-authored-by`, lo que el estándar de la organización prohíbe. Quitarlo exige reescribir la historia y `push --force`; se deja pendiente de aprobación explícita y los commits nuevos ya no lo incluyen.

## Alternativas descartadas
- **Bloqueo permanente tras N fallos:** protege la verificación pero permite negar el servicio a un cliente con solo equivocarse a propósito.
- **Redis desde el primer día:** correcto para producción multirréplica, pero añade un servicio al ejercicio; se deja como evolución detrás de la misma interfaz.
- **Validar la configuración en la primera petición:** el fallo llega al usuario; arrancar y fallar permite que el orquestador lo detecte antes.
