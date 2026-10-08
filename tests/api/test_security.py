"""Sesiones, bloqueo temporal y limite de tasa, con reloj simulado."""

from api.security import AttemptLimiter, RateLimiter, SessionStore


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def test_la_sesion_vence_y_se_purga() -> None:
    clk = Clock()
    store = SessionStore(ttl_s=60, clock=clk)
    token = store.create("c1")
    assert store.get(token) == "c1"
    clk.advance(61)
    assert store.get(token) is None
    assert len(store) == 0  # al consultarla se elimina


def test_crear_sesiones_purga_las_vencidas_sin_que_nadie_las_use() -> None:
    clk = Clock()
    store = SessionStore(ttl_s=60, clock=clk)
    for i in range(50):
        store.create(f"c{i}")
    clk.advance(120)
    store.create("nuevo")
    assert len(store) == 1  # las 50 vencidas ya no ocupan memoria


def test_el_almacen_tiene_tope_y_expulsa_la_mas_vieja() -> None:
    store = SessionStore(max_sessions=3)
    first = store.create("c0")
    for i in range(1, 5):
        store.create(f"c{i}")
    assert len(store) == 3 and store.get(first) is None


def test_revocar_cierra_todas_las_sesiones_del_caso() -> None:
    store = SessionStore()
    a, b, other = store.create("c1"), store.create("c1"), store.create("c2")
    store.revoke_case("c1")
    assert store.get(a) is None and store.get(b) is None
    assert store.get(other) == "c2"


def test_los_tokens_no_se_repiten() -> None:
    store = SessionStore()
    assert len({store.create("c") for _ in range(200)}) == 200


def test_el_bloqueo_es_temporal_y_no_deja_fuera_para_siempre() -> None:
    clk = Clock()
    lim = AttemptLimiter(max_failures=3, lock_s=300, clock=clk)
    for _ in range(3):
        lim.record_failure("c1")
    assert 0 < lim.retry_after("c1") <= 301
    clk.advance(301)
    assert lim.retry_after("c1") == 0  # el cliente legitimo vuelve a entrar
    lim.record_failure("c1")
    assert lim.retry_after("c1") == 0  # y el contador empezo de cero


def test_los_fallos_viejos_salen_de_la_ventana() -> None:
    clk = Clock()
    lim = AttemptLimiter(max_failures=3, window_s=100, clock=clk)
    lim.record_failure("c1")
    lim.record_failure("c1")
    clk.advance(101)
    lim.record_failure("c1")  # los 2 anteriores ya no cuentan
    assert lim.retry_after("c1") == 0


def test_el_bloqueo_es_por_caso_y_un_acierto_lo_reinicia() -> None:
    lim = AttemptLimiter(max_failures=2)
    lim.record_failure("c1")
    lim.record_failure("c1")
    assert lim.retry_after("c1") > 0 and lim.retry_after("c2") == 0
    lim.reset("c1")
    assert lim.retry_after("c1") == 0


def test_limite_de_tasa_por_ventana_deslizante() -> None:
    clk = Clock()
    rl = RateLimiter(limit=3, per_s=60, clock=clk)
    assert [rl.allow("s") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("otra")  # claves independientes
    clk.advance(61)
    assert rl.allow("s")  # la ventana se desliza
