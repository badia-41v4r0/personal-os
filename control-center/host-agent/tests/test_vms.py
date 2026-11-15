import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vms  # noqa: E402

VID = "12345678-1234-1234-1234-1234567890ab"


def test_contenedor_endurecido_sin_red_por_defecto():
    a = vms.run_argv(vms.validate({"id": VID, "profile": "desktop"}))
    j = " ".join(a)
    for must in ("--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit 512", "--network none",
                 "--memory-swap", f"src=jarvis-vc-{VID},dst=/home/vc"):
        assert must in j
    for never in ("--privileged", "docker.sock", "-p ", "--publish", str(Path.home()), ".env", "secrets"):
        assert never not in j
    assert a[-1] == "jarvis-vc:desktop"


def test_internet_solo_si_se_pide():
    assert "--network bridge" in " ".join(vms.run_argv(vms.validate({"id": VID, "internet": True})))


@pytest.mark.parametrize("bad", [{"id": "x"}, {"profile": "root"}, {"cpus": 8}, {"memory_mb": 64000}, {"disk_mb": 1}])
def test_validacion(bad):
    with pytest.raises(ValueError):
        vms.validate({"id": VID} | bad)


@pytest.mark.parametrize("p,ok", [("a.txt", "/home/vc/trabajo/a.txt"), ("/home/vc/descargas/x.pdf", "/home/vc/descargas/x.pdf"),
                                  ("/home/vc", "/home/vc")])
def test_rutas_validas(p, ok):
    assert vms.safe_path(p) == ok


@pytest.mark.parametrize("p", ["/etc/passwd", "/home/vc/../root", "../../etc", "/home/vcx/a", "/proc/1/environ"])
def test_rutas_prohibidas(p):
    with pytest.raises(ValueError):
        vms.safe_path(p)


def test_owner_saneado():
    assert vms.validate({"id": VID, "owner": "agent:X; rm -rf"})["owner"] == "agent:xrm-rf"
    assert ";" not in vms.validate({"id": VID, "owner": "a;b"})["owner"]


# ---------- Canvas: sin red propia, solo el socket de su proxy ----------

def test_canvas_sin_red_y_con_socket_del_proxy():
    req = vms.validate({"id": VID, "profile": "canvas", "internet": True, "egress_allow": ["campus.example.edu"], "start_url": "https://campus.example.edu/"})
    assert req["internet"] is False  # aunque se pida: sale solo por su proxy
    j = " ".join(vms.run_argv(req))
    assert "--network none" in j and f"src=jarvis-vc-{VID}-gw,dst=/run/egress,readonly" in j
    assert vms.run_argv(req)[-1] == "jarvis-vc:canvas"


def test_proxy_endurecido_y_sin_secretos():
    j = " ".join(vms.egress_argv(VID))
    for must in ("--read-only", "--cap-drop ALL", "no-new-privileges", "--memory 384m", f"jarvis.vc.egress={VID}"):
        assert must in j
    for never in ("--privileged", "docker.sock", "--publish", "-p ", str(Path.home()), ".env", "secrets"):
        assert never not in j
    assert "jarvis.vc=" not in j  # no cuenta como ordenador ni aparece en la lista


@pytest.mark.parametrize("keys", ["Return", "ctrl+l", "Page_Down alt+Left"])
def test_teclas_validas(keys):
    assert vms.key_cmd(keys)[:2] == ["xdotool", "key"]


@pytest.mark.parametrize("keys", ["", "a;b", "$(id)", "x " * 11, "`id`"])
def test_teclas_invalidas(keys):
    with pytest.raises(ValueError):
        vms.key_cmd(keys)


def test_clic_y_scroll_validan():
    assert vms.click_cmd(10, 20)[:4] == ["xdotool", "mousemove", "10", "20"]
    with pytest.raises(ValueError):
        vms.click_cmd(-1, 5)
    with pytest.raises(ValueError):
        vms.click_cmd(1, 1, "boton")
    with pytest.raises(ValueError):
        vms.scroll_cmd(1, 1, "arriba")


def test_texto_va_tras_doble_guion():
    assert vms.type_cmd("--help")[-2:] == ["--", "--help"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "ftp://x", "https://a b"])
def test_navegador_solo_http(url):
    with pytest.raises(ValueError):
        vms.browser_cmd("open", url)


def test_navegador_operacion_cerrada():
    with pytest.raises(ValueError):
        vms.browser_cmd("eval", "1+1")
    assert vms.browser_cmd("open", "https://campus.ejemplo.edu/")[-2:] == ["open", "https://campus.ejemplo.edu/"]


ID = "12345678-1234-1234-1234-123456789012"


def test_aplicaciones_necesita_su_lista_de_dominios():
    with pytest.raises(ValueError):
        vms.validate({"id": ID, "profile": "aplicaciones"})
    with pytest.raises(ValueError):
        vms.validate({"id": ID, "profile": "aplicaciones", "egress_allow": ["no es un dominio"]})
    with pytest.raises(ValueError):
        vms.validate({"id": ID, "profile": "aplicaciones", "egress_allow": [f"d{i}.com" for i in range(41)]})
    r = vms.validate({"id": ID, "profile": "aplicaciones", "egress_allow": ["Greenhouse.io."], "internet": True})
    assert r["egress_allow"] == ["greenhouse.io"] and r["internet"] is False  # sin red propia: solo su proxy
    argv = vms.run_argv(r)
    assert "none" in argv and any("dst=/run/egress" in a for a in argv)


def test_otros_perfiles_no_llevan_lista():
    assert vms.validate({"id": ID, "profile": "terminal", "egress_allow": ["x.com"]})["egress_allow"] == []


def test_el_agente_de_solicitudes_no_tiene_terminal_raton_ni_envio():
    for op in ("exec", "click", "type", "key", "write_file", "read_file", "destroy", "request", "submit", "form_submit"):
        assert op not in vms.APLICACIONES_OPS
    assert {"form_fields", "form_fill", "form_attach", "open_url", "page_text"} <= vms.APLICACIONES_OPS


def test_formularios_solo_operaciones_cerradas():
    with pytest.raises(ValueError):
        vms.form_cmd("eval", {})
    with pytest.raises(ValueError):
        vms.form_cmd("fill", {"valores": {"f1": "x" * 200_000}})
    c = vms.form_cmd("fill", {"valores": {"f1": "'; import os #"}})
    assert c[:2] == ["python3", "-c"] and c[2] == vms.FORM_PY and c[3] == "fill"  # el valor va como datos, no como código
