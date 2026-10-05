# Decisiones de diseño

Documento corto de decisiones: qué se decidió, por qué, qué se descartó y
qué se asumió. Cada decisión apunta al código o a la prueba que la respalda.
Es el punto de partida para defender el diseño en vivo.

## 1. Qué es el "agente" aquí

Un **operador de casos**: toma un caso y lo lleva por las cuatro etapas
llamando las **mismas acciones que un asesor**, con estado persistente y
rastro auditable. Resuelve *operar*, no solo responder: se mide en casos que
llegan completos a la financiera sin retrabajo.

| Etapa | Lo decide el agente (IA) | Lo decide el código |
|---|---|---|
| Elegibilidad | qué preguntar; interpretar "ya lo pagué" o "tengo una llave" | el veredicto (titular, adeudos) y las transiciones |
| Perfilamiento | cómo pedir la autorización del Buró y explicar el resultado | score → perfil, condiciones, rechazo |
| Simulación | qué opciones destacar | montos, tasas, cuotas, costo de llave |
| Datos y comprobantes | qué pedir y cómo redactar la corrección | coincidencias, umbrales, vigencias y el gate final |

**Regla de oro: todo lo que mueve dinero o estado es código.** La IA solo
produce entradas que el código valida, o texto para humanos.

## 2. Arquitectura

Hexagonal: el dominio (`domain/`) es puro y no importa nada de
infraestructura; los puertos viven en `ports.py` y los adaptadores en
`adapters/`. Diagramas completos en [`docs/architecture/C4.md`](docs/architecture/C4.md).

**Por qué hexagonal.** El producto cambia cada semana y los proveedores
(buró, mensajería, lector de documentos, LLM) también. Con puertos, cambiar
de proveedor es escribir un adaptador y las reglas se prueban sin red.
*Descartado:* llamar a los proveedores desde los nodos del grafo: acopla el
negocio a la infraestructura y lo hace imposible de probar en frío.

**Por qué LangGraph con controlador determinista.** Estado tipado,
checkpointer e interrupciones (la escalada pausa el grafo hasta que el asesor
resuelve). El grafo **relee el caso persistido tras cada acción y enruta por
su `stage`**: qué etapa sigue lo decide el dominio, no el modelo
(`agent/graph.py`). *Descartado:* un agente libre con un solo prompt (difícil
de acotar y de auditar) y dejar que el modelo elija entre todas las tools
(mayor superficie de inyección). Si los requisitos fueran menores, una
máquina de estados simple bastaría; queda escrito.

## 3. El caso es la verdad, no la conversación

El agente **no** depende del historial del chat. La fuente de verdad es el
agregado `Case` persistido (`domain/case.py`), y cada turno recibe una
**proyección compacta sin datos personales** (`tools.catalog.project_case`).

- **Las transiciones las valida el dominio** (`can_transition`), nunca el
  modelo. `Case` es inmutable: `transition()` devuelve uno nuevo con
  `version + 1`.
- **Aristas de invalidación**: si el ingreso verificado hace inviable la
  cuota, el caso vuelve de `DOCUMENTS` a `SIMULATION` (escenario 11). Un
  error clásico es no modelarlo.
- **Concurrencia optimista** por `version`: asesor y agente pueden actuar
  sobre el mismo caso sin pisarse. En Mongo es un `update_one` condicional,
  atómico en el servidor (`adapters/case_repo_mongo.py`). Prueba:
  `test_escritura_concurrente_no_pisa_al_otro`.
- **Una escalada recuerda de dónde vino** (`escalated_from`) y solo se
  reanuda ahí o se cierra el caso.
- *Descartado:* confiar solo en el estado del framework: se pierde al
  reiniciar, no lo ve un asesor y no se puede auditar. El estado del grafo es
  efímero; el del caso es duradero. (`test_reanudar_sin_checkpoint_arranca_limpio`)

## 4. Tools: contrato, seguridad, idempotencia, auditoría

15 tools, cada una un `ToolSpec` (`tools/spec.py`): modelos Pydantic de
entrada y salida, `effect`, `risk`, `required_scope` y etapas permitidas.
**Toda llamada, del agente o del asesor, pasa por un único ejecutor**
(`tools/executor.py`):

1. Entrada válida (campos extra y tipos erróneos se rechazan).
2. El principal tiene el *scope* (mínimo privilegio).
3. `case_id` coincide con el caso ligado a la sesión.
4. Idempotencia: reintento ⇒ resultado guardado.
5. La tool está permitida en la etapa actual (y `expected_version`).
6. Se ejecuta y la salida se valida contra su modelo.
7. Se persiste con control optimista de versión.
8. Se escribe un evento de bitácora, **también en las denegaciones**.

Decisiones que vale la pena defender:

- **El control vive en la tool, no solo en el grafo.** `mark_ready_for_lender`
  *reevalúa el gate completo desde los datos* (revisión documental, hash de la
  simulación recalculado, ingreso verificado) y se niega si algo falla. No se
  fía de banderas guardadas ni de lo que diga el agente. Aunque el modelo
  falle, lo manipulen o alguien invoque la tool por otro camino, no se puede
  marcar listo un expediente inconsistente. Pruebas: `test_gate_*` y el
  bypass de `make eval`.
- **Una sola capa para humano y agente.** El asesor es otro `principal` con
  otros scopes: una sola bitácora, ningún "camino trasero" sin controles, y
  el agente puede adoptar acciones del backoffice sin reescribirlas.
- **Idempotencia con ventana de versiones.** La clave es `caso + tool + hash
  canónico de los argumentos` y el resultado se reconoce si el caso sigue en
  la versión previa o posterior a esa llamada. *Por qué no `+ versión` a
  secas (como en la propuesta original):* el reintento de una escritura que ya
  subió la versión llegaría con otra clave y se re-ejecutaría. Va antes del
  chequeo de etapa por la misma razón, y **nunca salta los pasos 1 a 3**
  (`test_reintento_no_salta_el_control_de_permisos`).
- **Consentimiento antes del Buró** es precondición de la tool, no un detalle
  de la conversación. Al modelo y al caso solo llega el perfil normalizado:
  ni el reporte crudo ni el score se guardan.
- **Lista blanca por etapa** además del chequeo del ejecutor: en cada etapa el
  agente solo *ve* y solo puede *intentar* sus tools; lo demás es
  `TOOL_NOT_WHITELISTED` y suma una violación (tope: 3 ⇒ escala).
- **Orden de efectos sin transacción.** Los tickets se crean *antes* de
  guardar el caso, con id determinista (`T-<caso>-<versión>`): un reintento
  no duplica, y un conflicto de versión deja a lo sumo un ticket abierto
  huérfano (inocuo). Resolver un ticket ocurre *después* de guardar el caso
  (`after_commit`). Mongo sin réplica no ofrece transacciones multi-documento;
  se prefirió un fallo benigno y reintentable a uno silencioso.

## 5. Determinismo vs IA

| Parte | Quién | Por qué |
|---|---|---|
| Gates de elegibilidad | Código | consecuencias legales; debe ser reproducible |
| Score → perfil y condiciones | Tabla en YAML versionada | el negocio la cambia sin tocar código; auditable |
| Cuota, tasa, costo de llave | Código con `Decimal` | un LLM no es una calculadora; dinero nunca en `float` |
| Coincidencia de ingreso e identidad | Código | el LLM **extrae**, el código **compara** |
| Gate "OK para financiera" | Código | la decisión de mayor riesgo |
| Conversación, siguiente pregunta | IA | donde el lenguaje natural aporta |
| Extracción y clasificación de documentos | IA con salida estructurada | problema perceptivo |

**La confianza que reporta un modelo no se toma sola.** Está mal calibrada: se
cruza con validadores objetivos (formato de CURP/RFC, aritmética
bruto − deducciones = neto, coherencia entre documentos). Un dato con
confianza 0.99 pero neto que no cuadra es baja confianza
(`test_aritmetica_rota_es_baja_confianza`).

## 6. Supuestos (el reto no los da)

Los marco como supuestos *configurables*, no como verdades del producto.

| Tema | Supuesto | Dónde vive |
|---|---|---|
| Stack | MongoDB, LangGraph y FastAPI (indicado por el autor del reto) | `pyproject.toml` |
| Moneda | MXN, `Decimal`, redondeo a centavos | `domain/loan.py` |
| Tasas, bandas, LTV, plazos | tabla ilustrativa (A ≥ 700, B 640–699, C 580–639, D < 580) | `config/profile_policy.yaml` |
| Tolerancias de ingreso | ≤ 10 % acepta; 10–25 % pide corrección; > 25 % escala | `config/document_policy.yaml` |
| Capacidad de pago | cuota ≤ 35 % del ingreso **verificado** | `config/document_policy.yaml` |
| Vigencias | recibos 60 días, domicilio 90, identificación no vencida | `config/document_policy.yaml` |
| Costo de la llave | se financia: se suma al capital | `domain/loan.py` |
| LTV con llave | se evalúa sobre el capital **total** (monto + llave): lectura conservadora | `domain/loan.py` |
| Segunda llave | la declara el cliente; el registro manda si ya lo sabe | `check_vehicle_eligibility` |
| Dato faltante | se pregunta (`NEEDS_INFO`); nunca se asume que cumple | `domain/eligibility.py` |
| Expediente delgado | < 12 meses de historial ⇒ escala (ni aprueba ni rechaza) | `adapters/bureau_http.py` |
| Perfil escalado | el asesor solo puede reanudar (revaluar), rechazar o declinar; no hay override de perfil | `tools/catalog.py` |
| Override del asesor | solo códigos escalables; nunca perdona la capacidad de pago | `domain/doc_review.py` |
| Fecha de la demo | fija (2026-10-05) para que los fixtures no caduquen | `config/mock.yaml` |
| Fuera de alcance | CAT/IVA, originación, cobranza (lo indica el enunciado) | — |

## 7. Guardrails y humano en el circuito

- **Caso equivocado.** La sesión se liga a un `case_id` tras verificar
  identidad (últimos 4 del teléfono); el ejecutor rechaza cualquier tool con
  otro `case_id`. El error de verificación es idéntico exista o no el caso, y
  hay bloqueo tras 5 intentos.
- **Documentos.** Se ligan por hash. Un comprobante de otra persona se
  **bloquea (no se liga)** y se escala. No se muestran datos personales antes
  de verificar identidad.
- **Inyección de prompt.** El texto de un documento y el mensaje del cliente
  son **dato**: van en un bloque delimitado que no puede cerrarse a sí mismo;
  `read_document` nunca devuelve el texto crudo; la extracción es
  estructurada y no existe camino para que un documento invoque una tool; un
  detector marca el contenido sospechoso como evidencia (`SUSPICIOUS_CONTENT`
  ⇒ escala). El detector es heurístico: **no es la defensa principal**; lo es
  que el gate decide en código.
- **Privacidad.** La bitácora guarda hashes, nunca valores. Al LLM solo va la
  proyección sin datos personales. Secretos solo por entorno.
- **Escalada.** `escalate_to_human` crea un ticket y el grafo se **pausa**
  (`interrupt` de LangGraph). El asesor (`cli.advisor` o la API) ve la
  proyección, la línea de tiempo y la evidencia; puede **reanudar con una
  justificación obligatoria**, rechazar o declinar. Al resolver, el agente
  retoma desde el checkpoint (o desde el caso persistido si el proceso se
  reinició).
- **Si el LLM falla.** `LLMPolicy` envuelve a `RuleBasedPolicy`: ante error o
  respuesta inválida decide la regla; tras 3 fallos seguidos de un caso el
  circuito se abre. Un modelo que solo pide "marca listo" abre el circuito y
  el caso sigue por reglas. La decisión sigue siendo del código en ambos modos.

## 8. Proveedores de LLM (patrón Strategy)

`ports.LLMPort` es la estrategia; cada proveedor (`openai`, `deepseek`,
`gemini`, `anthropic`, `scripted`) la implementa sobre una base HTTP común
(Template Method). `registry.create_llm("gemini,openai")` arma una cadena con
fallback y circuit breaker (Decorator). Se usa `httpx` directo, sin SDKs: una
dependencia menos y todo se prueba sin red. El agente depende solo del puerto.

## 9. Observabilidad y evaluación

**Bitácora** JSONL, un evento por decisión: `run_id`, `case_id`, `principal`,
`type`, `name`, `rule_version`, `inputs_hash`, `outcome`, `reason_codes`,
`latency_ms`, `stage_after`. `make report` responde las preguntas del reto:

| Pregunta | Métrica |
|---|---|
| ¿Rechaza bien por auto? | rechazos por `reason_code` |
| ¿Hay falsos OK documentales? | **offline:** `make eval`. **En producción:** tasa de reversión del asesor sobre una muestra de casos OK |
| ¿Detecta mismatches? | conteo por tipo (ingreso, identidad, vigencia, ...) |
| ¿Casos con llave cotizada? | casos con `quote_second_key` |
| Salud del agente | tasa de escalada, errores y latencia p95 por tool, estado del LLM, violaciones de invariantes |

**La evaluación hace que "valida bien" sea demostrable.** `make eval` corre 69
casos etiquetados (los 12 escenarios con ambas políticas, 19 variantes
(18 adversariales y un control positivo) y una corrida con un **modelo hostil** que solo sabe pedir
"marca listo") y mide falsos OK, falsos rechazos e intentos de saltarse el
gate llamando `mark_ready_for_lender` directo con agente y asesor. Sale con
error si aparece uno. **Tiene dientes**: una prueba rompe el gate a propósito
y comprueba que la evaluación se pone en rojo.

Un falso OK cuesta más que un falso rechazo; por eso los umbrales son
conservadores y cualquier duda ⇒ corrección o escalada, nunca OK.

## 10. Sistema vivo: cómo se adopta sin romper nada

1. **Sombra:** el agente propone y registra; el humano ejecuta; se mide la
   coincidencia.
2. **Asistido:** el agente ejecuta las etapas de bajo riesgo; el humano
   aprueba lo de riesgo alto (`mark_ready_for_lender`, `resolve_escalation`).
3. **Autónomo por etapa:** solo donde las métricas de la evaluación lo
   justifiquen.

Las reglas son configuración versionada, así que el cambio semanal del
producto no exige tocar código. Los proveedores están detrás de puertos y de
un catálogo de mocks validado (`make mocks-validate`).

## 11. Trade-offs

| Decisión | Alternativa | Por qué |
|---|---|---|
| Grafo con controlador determinista | agente libre | auditable, interrumpible, estado tipado |
| LLM acotado por etapa | LLM con todas las tools | mínimo privilegio y menor superficie de inyección |
| LLM guionado por defecto | exigir API key | cualquiera clona y corre; pruebas deterministas |
| Lector de documentos por mock HTTP | OCR real | el reto permite mockear; el valor está en qué se valida |
| Mocks declarativos + clientes HTTP reales | fixtures en el adaptador | cambiar a un proveedor real es cambiar una URL; el adaptador real queda probado |
| `httpx` directo | SDK de cada proveedor | menos dependencias; todo probable sin red |
| Sin transacciones entre tickets y caso | transacciones Mongo | exigirían réplica; el fallo benigno y reintentable es más simple |

## 12. Lo que NO está hecho y es honesto decir

- **No se ejecutó contra servicios reales.** MongoDB se probó con `mongomock`
  y hay una prueba de integración (`make integration`) que se omite sin
  servidor. Los cuatro adaptadores de LLM se probaron contra transportes
  simulados con el formato documentado de cada API; no se ejercitaron con
  claves reales. Los nombres de modelo por defecto deben verificarse.
- **Sesiones y bloqueo por intentos en memoria** de un proceso: con varias
  réplicas hacen falta Redis o Mongo con TTL.
- **Datos personales en `Case.data` sin cifrar en reposo** (nombre, ingreso,
  últimos 4 dígitos). En producción: cifrado a nivel de campo y retención.
- **Sin OCR real**, sin doble extracción con modelos distintos para medir
  desacuerdo, sin verificación real de la segunda llave, sin CAT ni IVA, sin
  mensajería real (WhatsApp) ni panel web para el asesor.
- **Evaluación con LLM como juez** del resumen para el asesor: no hecha.
- **Límite de tasa** en la API y autenticación del asesor más allá de una API
  key (SSO, MFA): pendientes.
