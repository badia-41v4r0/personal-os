"""Proveedores de IA: traducción de su salida real, configuración que reciben y contenedor sin red."""
import json
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proveedores  # noqa: E402
import sesiones  # noqa: E402

SID = "12345678-1234-1234-1234-1234567890ab"
# Salidas reales capturadas con codex-cli 0.169 y opencode 2.2.7 (15/11/2026)
CODEX = [
    '{"type":"thread.started","thread_id":"01a1e095-ad1d-76b3-b885-df21b31e188e"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"ls"}}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"ok"}}',
    '{"type":"turn.completed","usage":{"input_tokens":13679,"cached_input_tokens":6912,"output_tokens":5}}',
]
OPENCODE = [
    '{"type":"step_start","sessionID":"ses_e1f6a13f9ffelezg96FWF8UJWP","part":{"type":"step-start"}}',
    '{"type":"tool_use","sessionID":"ses_e1f6a13f9ffelezg96FWF8UJWP","part":{"type":"tool","tool":"read","state":{"status":"completed","input":{"path":"/trabajo/nota.txt"}}}}',
    '{"type":"step_finish","sessionID":"ses_e1f6a13f9ffelezg96FWF8UJWP","part":{"type":"step-finish","cost":0.0012,"tokens":{"input":7449,"output":3}}}',
    '{"type":"text","sessionID":"ses_e1f6a13f9ffelezg96FWF8UJWP","part":{"type":"text","text":"El número es 42"}}',
    '{"type":"step_finish","sessionID":"ses_e1f6a13f9ffelezg96FWF8UJWP","part":{"type":"step-finish","cost":0.0008,"tokens":{"input":100,"output":5}}}',
]


def _todo(prov, lineas):
    t = proveedores.Traductor(prov)
    out = [e for l in lineas for e in t.linea(l)] + t.final()
    return out


def test_codex_se_traduce_al_formato_de_claude():
    evs = _todo("codex", CODEX)
    assert evs[0] == {"type": "system", "subtype": "init", "session_id": "01a1e095-ad1d-76b3-b885-df21b31e188e"}
    tools = [c for e in evs if e["type"] == "assistant" for c in e["message"]["content"] if c["type"] == "tool_use"]
    assert tools[0]["name"] == "command_execution" and tools[0]["input"]["query"] == "ls"
    fin = [e for e in evs if e["type"] == "result"]
    assert len(fin) == 1 and fin[0]["result"] == "ok" and not fin[0]["is_error"] and fin[0]["usage"]["output_tokens"] == 5


def test_opencode_suma_coste_y_cierra_al_acabar():
    evs = _todo("opencode", OPENCODE)
    fin = evs[-1]
    assert fin["type"] == "result" and fin["result"] == "El número es 42" and fin["session_id"].startswith("ses_")
    assert fin["total_cost_usd"] == pytest.approx(0.002) and fin["proveedor"] == "opencode"
    tools = [c for e in evs if e["type"] == "assistant" for c in e["message"]["content"] if c["type"] == "tool_use"]
    assert tools[0]["name"] == "read" and tools[0]["input"]["query"] == "/trabajo/nota.txt"


def test_error_de_codex_llega_como_error():
    t = proveedores.Traductor("codex")
    t.linea('{"type":"thread.started","thread_id":"01a1e095-ad1d-76b3-b885-df21b31e188e"}')
    fin = t.linea('{"type":"turn.failed","error":{"message":"usage limit"}}')[-1]
    assert fin["is_error"] and "usage limit" in fin["result"]


def test_basura_no_rompe():
    t = proveedores.Traductor("opencode")
    assert t.linea("no es json") == [] and t.linea("[1,2]") == []


def test_config_de_codex_es_toml_valido_y_sin_red(tmp_path):
    servers = sesiones.mcp_servers(vc=False, gym=False, pos=True)
    env = proveedores.preparar_home("codex", tmp_path, servers, "read", 'Eres "Jarvis".\nSé breve.', {"codex_auth": '{"x":1}'})
    cfg = tomllib.loads((tmp_path / ".codex/config.toml").read_text())
    assert cfg["approval_policy"] == "never" and cfg["sandbox_workspace_write"]["network_access"] is False
    assert cfg["developer_instructions"].startswith('Eres "Jarvis"') and cfg["mcp_servers"]["pos"]["args"] == ["/opt/pos/pos_mcp.py"]
    assert env == {"CODEX_HOME": "/home/node/.codex"}
    assert oct((tmp_path / ".codex/auth.json").stat().st_mode & 0o777) == "0o600"


def test_config_de_opencode_sin_terminal_y_clave_por_entorno(tmp_path):
    env = proveedores.preparar_home("opencode", tmp_path, {}, "read", "hola", {"openrouter_key": "sk-or-secreta"})
    texto = (tmp_path / ".config/opencode/opencode.json").read_text()
    cfg = json.loads(texto)
    assert cfg["permission"]["bash"] == "deny" and cfg["permission"]["edit"] == "deny"
    assert "sk-or-secreta" not in texto and env["OPENROUTER_API_KEY"] == "sk-or-secreta"


def test_contenedor_de_otro_proveedor_va_sin_red_y_sin_secretos_en_argv(tmp_path):
    r = sesiones.validate({"session_id": SID, "prompt": "hola", "provider": "opencode", "model": "openrouter/x/y"})
    dirs = sesiones.prepare_dirs(tmp_path, SID)
    argv = sesiones.docker_argv(tmp_path, r, dirs, ("OPENROUTER_API_KEY",))
    j = " ".join(argv)
    assert "--network none" in j and "/run/egress:ro" in j and "-e OPENROUTER_API_KEY" in j
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in j and "sk-or" not in j
    assert argv[-6:] == ["opencode", "run", "--format", "json", "-m", "openrouter/x/y"]


def test_claude_sigue_igual(tmp_path):
    r = sesiones.validate({"session_id": SID, "prompt": "hola"})
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID))
    assert "--network bridge" in " ".join(argv) and "-e CLAUDE_CODE_OAUTH_TOKEN" in " ".join(argv)


@pytest.mark.parametrize("cuerpo", [
    {"provider": "antigravity"}, {"provider": "otro"}, {"provider": "codex", "subagents": True},
    {"provider": "opencode", "model": "x; rm -rf /"}, {"provider": "codex", "resume": "ses_abc"},
    {"provider": "opencode", "internet": True},
])
def test_valida_lo_que_cada_proveedor_no_puede(cuerpo):
    with pytest.raises(ValueError):
        sesiones.validate({"session_id": SID, "prompt": "hola"} | cuerpo)


def test_reanudar_codex():
    r = sesiones.validate({"session_id": SID, "prompt": "hola", "provider": "codex", "model": "", "resume": "01a1e095-ad1d-76b3-b885-df21b31e188e"})
    a = proveedores.argv("codex", r["model"], r["resume"])
    assert a[:4] == ["codex", "exec", "resume", "01a1e095-ad1d-76b3-b885-df21b31e188e"] and a[-1] == "-" and "-m" not in a
