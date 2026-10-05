"""La interfaz de prueba: que no filtre credenciales ni se desconfigure."""

from pathlib import Path

import yaml


def test_la_interfaz_no_lleva_credenciales_y_solo_habla_con_api() -> None:
    page = Path("web/index.html").read_text(encoding="utf-8")
    assert "X-API-Key" not in page  # las claves van en el proxy
    assert 'const API = "/api"' in page
    assert "demo-canal" not in page and "demo-asesor" not in page


def test_nginx_inyecta_una_credencial_distinta_por_ruta() -> None:
    conf = Path("web/nginx.conf.template").read_text(encoding="utf-8")
    advisor = conf.index("location /api/advisor/")
    channel = conf.index("location /api/ {")
    assert "${ADVISOR_API_KEY}" in conf[advisor:channel]
    assert "${AGENT_CLIENT_API_KEY}" in conf[channel:]


def test_compose_tiene_el_servicio_web_y_claves_de_demo() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    assert set(compose["services"]) == {"mongo", "mocks", "api", "web"}
    web = compose["services"]["web"]
    assert "8080:80" in web["ports"]
    # arranca sin configurar nada; las claves de demo se ven como de demo
    assert "demo-" in web["environment"]["ADVISOR_API_KEY"]
    api = compose["services"]["api"]["environment"]
    assert api["FIXED_TODAY"] == "2026-10-05"  # los fixtures no caducan
