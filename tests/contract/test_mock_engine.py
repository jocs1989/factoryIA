import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mocks.engine import MockEngine
from mocks.model import Mapping
from mocks.server import create_app
from mocks.validate import validate_catalog


def m(id_: str, patterns: list[tuple[str, str]], body: Any = None, **kw: Any):  # type: ignore[no-untyped-def]
    return Mapping.model_validate(
        {
            "id": id_,
            "domain": "t",
            "request": {
                "method": "POST",
                "path": "/x",
                "bodyPatterns": [
                    {"jsonPath": p, "equalTo": v} for p, v in patterns
                ],
            },
            "response": {"jsonBody": body or {"id": id_}},
            **kw,
        }
    )


def test_gana_menor_prioridad_luego_mas_especifico() -> None:
    e = MockEngine(
        [
            m("a.general", []),
            m("a.especifico", [("$.k", "1")]),
            m("a.override", [("$.k", "1")], priority=5),
        ]
    )
    assert e.handle("POST", "/x", {"k": 1}).body == {"id": "a.override"}
    assert e.handle("POST", "/x", {"k": 2}).body == {"id": "a.general"}


def test_especificidad_desempata_a_igual_prioridad() -> None:
    e = MockEngine([m("a.general", []), m("a.fino", [("$.k", "1")])])
    assert e.handle("POST", "/x", {"k": 1}).body == {"id": "a.fino"}


def test_jsonpath_anidado_booleanos_y_concat() -> None:
    e = MockEngine(
        [
            m("a.anidado", [("$.a.b", "true")]),
            Mapping.model_validate(
                {
                    "id": "a.concat",
                    "domain": "t",
                    "request": {
                        "method": "POST",
                        "path": "/y",
                        "bodyPatterns": [
                            {"jsonPathConcat": ["$.p", "$.q"], "equalTo": "ab"}
                        ],
                    },
                    "response": {"jsonBody": {"ok": 1}},
                }
            ),
        ]
    )
    assert e.handle("POST", "/x", {"a": {"b": True}}).status == 200
    assert e.handle("POST", "/y", {"p": "a", "q": "b"}).status == 200
    assert e.handle("POST", "/y", {"p": "a", "q": "c"}).status == 404


def test_plantilla_con_el_cuerpo_de_la_peticion() -> None:
    e = MockEngine([m("a.t", [], {"folio": "F-{{request.body.id}}"})])
    assert e.handle("POST", "/x", {"id": "9"}).body == {"folio": "F-9"}


def test_404_explica_el_near_miss() -> None:
    e = MockEngine([m("a.uno", [("$.k", "1")])])
    res = e.handle("POST", "/x", {"k": 2})
    assert res.status == 404
    miss = res.body["near_miss"][0]
    assert miss["expected"] == {"$.k": "1"} and miss["got"] == {"$.k": "2"}
    assert (
        "other_methods_for_path"
        in e.handle("GET", "/x", None).body["near_miss"]
    )
    assert e.handle("POST", "/nada", None).status == 404


def test_fault_delay_se_reporta() -> None:
    e = MockEngine(
        [
            Mapping.model_validate(
                {
                    "id": "a.lento",
                    "domain": "t",
                    "request": {"method": "GET", "path": "/s"},
                    "response": {"jsonBody": {}, "faultDelayMs": 250},
                }
            )
        ]
    )
    assert e.handle("GET", "/s", None).delay_ms == 250


def test_schema_estricto_rechaza_campos_mal_escritos() -> None:
    with pytest.raises(ValueError):
        Mapping.model_validate(
            {
                "id": "a.b",
                "domain": "t",
                "request": {
                    "method": "POST",
                    "path": "/x",
                    "bodypatterns": [],
                },
                "response": {"jsonBody": {}},
            }
        )


def test_catalogo_del_repo_es_valido() -> None:
    assert validate_catalog(Path("mocks/mappings")) == []


def test_validador_detecta_duplicados_y_shadowing(tmp_path: Path) -> None:
    def write(name: str, item: dict[str, Any]) -> None:
        (tmp_path / name).write_text(json.dumps(item))

    base = m("a.one", [("$.k", "1")]).model_dump(mode="json")
    write("1.json", base)
    write("2.json", {**base, "id": "a.two"})  # misma firma y prioridad
    write("3.json", {**base, "id": "a.three", "priority": 7})  # shadowing
    write("4.json", {**base, "id": "a.one"})  # id repetido
    write("5.json", {"id": "bad id", "domain": "t"})
    errors = "\n".join(validate_catalog(tmp_path))
    assert "id duplicado" in errors
    assert "ambiguo" in errors or "shadowing" in errors
    assert "5.json" in errors


def test_servidor_standalone() -> None:
    app = create_app(MockEngine.from_dir(Path("mocks/mappings")))
    c = TestClient(app)
    assert c.get("/_mock/health").json()["ready"] is True
    ok = c.post("/api/keys/quote", json={"vehicle_id": "veh-s04"})
    assert ok.json()["amount"] == "4200.00"
    assert (
        c.post("/api/bureau/query", json={"customer_id": "x"}).status_code
        == 404
    )
