import importlib
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import google_auth  # noqa: E402
import gcal  # noqa: E402


@pytest.fixture()
def g(tmp_path, monkeypatch):
    importlib.reload(google_auth)
    tp, tu = tmp_path / "gcal-token.json", tmp_path / "gmail-secundaria-token.json"
    monkeypatch.setattr(gcal, "CUENTAS", {"personal": (tp, "s", "yo@gmail.com"), "secundaria": (tu, "s", "yo@universidad.example")})
    monkeypatch.setattr(gcal, "url_autorizacion", lambda cuenta, state: f"https://accounts.example/auth?state={state}&c={cuenta}")
    canjes = []

    def canjear(code, cuenta):
        canjes.append((code, cuenta))
        gcal.CUENTAS[cuenta][0].write_text("{}")
        return gcal.CUENTAS[cuenta][0]

    monkeypatch.setattr(gcal, "canjear", canjear)
    google_auth._pending.clear()
    google_auth.canjes = canjes
    return google_auth


def _state(url):
    return url.split("state=")[1].split("&")[0]


def test_estado_sin_token_y_con_edad(g, tmp_path):
    a, b = g.status()
    assert a["autorizada"] is False and a["dias_restantes"] is None
    tok = tmp_path / "gcal-token.json"
    tok.write_text("{}")
    import os
    hace_5 = time.time() - 5 * 86400
    os.utime(tok, (hace_5, hace_5))
    a = g.status()[0]
    assert a["autorizada"] and 4.9 < a["edad_dias"] < 5.1 and 1.9 < a["dias_restantes"] < 2.1
    assert "refresh" not in str(a)  # nunca el contenido


def test_flujo_completo(g):
    url = g.auth_url("personal")["url"]
    r = g.exchange("personal", f"http://127.0.0.1:8765/?state={_state(url)}&code=4/0AbCdEfGhIjKlMnOp&scope=x")
    assert r == {"ok": True, "cuenta": "personal"} and g.canjes == [("4/0AbCdEfGhIjKlMnOp", "personal")]


def test_state_de_un_solo_uso(g):
    url = g.auth_url("personal")["url"]
    pegado = f"http://127.0.0.1:8765/?state={_state(url)}&code=4/0AbCdEfGhIjKlMn"
    g.exchange("personal", pegado)
    with pytest.raises(g.GoogleError) as e:
        g.exchange("personal", pegado)
    assert e.value.status == 409 and len(g.canjes) == 1


def test_state_ajeno_o_inventado(g):
    url = g.auth_url("personal")["url"]
    with pytest.raises(g.GoogleError) as e:
        g.exchange("secundaria", f"?state={_state(url)}&code=4/0AbCdEfGhIjKlMn")  # state de otra cuenta
    assert e.value.status == 409
    with pytest.raises(g.GoogleError) as e:
        g.exchange("personal", "?state=inventado&code=4/0AbCdEfGhIjKlMn")
    assert e.value.status == 409 and not g.canjes


def test_caduca_a_los_10_minutos(g):
    t0 = 1_000_000.0
    url = g.auth_url("personal", now=t0)["url"]
    with pytest.raises(g.GoogleError) as e:
        g.exchange("personal", f"?state={_state(url)}&code=4/0AbCdEfGhIjKlMn", now=t0 + 601)
    assert e.value.status == 409


def test_una_renovacion_por_cuenta_invalida_la_anterior(g):
    vieja = _state(g.auth_url("personal")["url"])
    g.auth_url("personal")
    with pytest.raises(g.GoogleError):
        g.exchange("personal", f"?state={vieja}&code=4/0AbCdEfGhIjKlMn")


@pytest.mark.parametrize("pegado", ["", "   ", "x" * 3000, "?state=a&code=", "code=\x00\x00malo&state=a"])
def test_pegado_invalido(g, pegado):
    with pytest.raises(g.GoogleError) as e:
        g.exchange("personal", pegado)
    assert e.value.status == 422


def test_solo_el_codigo_no_vale_sin_state(g):
    g.auth_url("personal")
    with pytest.raises(g.GoogleError) as e:
        g.exchange("personal", "4/0AbCdEfGhIjKlMnOpQrSt")
    assert e.value.status == 422 and not g.canjes


def test_cuenta_desconocida(g):
    for f in (lambda: g.auth_url("otra"), lambda: g.exchange("otra", "x")):
        with pytest.raises(g.GoogleError) as e:
            f()
        assert e.value.status == 404


def test_google_rechaza_el_codigo(g, monkeypatch):
    url = g.auth_url("personal")["url"]

    def malo(code, cuenta):
        raise gcal.Error("Google rechazó el código")

    monkeypatch.setattr(gcal, "canjear", malo)
    with pytest.raises(g.GoogleError) as e:
        g.exchange("personal", f"?state={_state(url)}&code=4/0AbCdEfGhIjKlMn")
    assert e.value.status == 502
