"""Las pruebas corren siempre en `mock`: sin red, sin credenciales."""

import os

os.environ.setdefault("AGENT_ENV", "mock")
