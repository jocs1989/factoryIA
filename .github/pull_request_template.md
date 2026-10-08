## Qué cambia y por qué

<!-- El porqué importa más que el qué. Enlaza el ADR si hay una decisión no trivial. -->

## Definición de hecho (DoD)

- [ ] `make check` en verde (lint, tipos, SAST, docstrings, mocks, tests y evaluación)
- [ ] Si toca dominio, tools o políticas: `make eval` da 0 falsos OK y 0 bypass
- [ ] Pruebas nuevas o actualizadas, incluido el caso límite que motivó el cambio
- [ ] Sin secretos ni datos personales en el código, los fixtures ni los logs
- [ ] Umbrales en YAML con su `version` incrementada, si cambiaron
- [ ] ADR nuevo si es una decisión no trivial; `CHANGELOG.md` actualizado
- [ ] Commits atómicos con Conventional Commits y **sin** `Co-authored-by`
- [ ] Si cambia la operación: runbook y SLOs revisados (`docs/runbooks/OPERACION.md`)
