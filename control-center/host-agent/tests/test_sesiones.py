import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sesiones  # noqa: E402

SID = "12345678-1234-1234-1234-1234567890ab"


def req(**kw):
    return sesiones.validate({"session_id": SID, "prompt": "hola"} | kw)


@pytest.mark.parametrize("bad", [{"level": "execute"}, {"model": "haiku"}, {"session_id": "../x"}, {"prompt": ""},
                                 {"resume": "x;rm"}, {"prompt": "x" * 20001}])
def test_valida(bad):
    with pytest.raises(ValueError):
        sesiones.validate({"session_id": SID, "prompt": "hola"} | bad)


def test_contenedor_endurecido(tmp_path):
    r = req(internet=True)
    dirs = sesiones.prepare_dirs(tmp_path, SID)
    argv = sesiones.docker_argv(tmp_path, r, dirs)
    joined = " ".join(argv)
    for must in ("--read-only", "--cap-drop ALL", "no-new-privileges", "--memory 1g", "--pids-limit", "--rm"):
        assert must in joined
    assert "docker.sock" not in joined and "--privileged" not in joined
    assert "CLAUDE_CODE_OAUTH_TOKEN" in argv and not any("CLAUDE_CODE_OAUTH_TOKEN=" in a for a in argv)  # sin valor
    assert "/vault" not in joined  # sin vault salvo que se pida
    assert "WebFetch" in argv[argv.index("--tools") + 1]
    assert "Bash" not in argv[argv.index("--tools") + 1]
    assert oct(dirs["base"].stat().st_mode)[-3:] == "700"


def test_vault_solo_lectura(tmp_path):
    argv = sesiones.docker_argv(tmp_path, req(vault=True), sesiones.prepare_dirs(tmp_path, SID))
    assert any(a.endswith(":/vault:ro") for a in argv) and "--add-dir" in argv


def test_permisos_por_nivel():
    s = sesiones.managed_settings("read", internet=False, vault=False)["permissions"]
    assert "Bash" in s["deny"] and "WebFetch" in s["deny"] and not any(a.startswith("Edit") for a in s["allow"])
    p = sesiones.managed_settings("propose", internet=True, vault=True)["permissions"]
    assert "Edit(//trabajo/**)" in p["allow"] and "Read(//vault/**)" in p["allow"] and "Edit(//vault/**)" in p["deny"]
    assert "Bash" in p["deny"] and "WebFetch" in p["allow"]


def test_execute_exige_ordenador():
    with pytest.raises(ValueError):
        sesiones.validate({"session_id": SID, "prompt": "x", "level": "execute"})
    r = sesiones.validate({"session_id": SID, "prompt": "x", "level": "execute", "vc": {"enabled": True, "owner": "Mi Agente;rm"}})
    assert r["vc"]["owner"] == "miagenterm"


def test_pasarela_montada_solo_si_hay_ordenador(tmp_path):
    r = sesiones.validate({"session_id": SID, "prompt": "x", "level": "execute", "vc": {"enabled": True}})
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID))
    assert "--mcp-config" in argv and any(a.endswith(":/run/vc") for a in argv) and any(a.endswith("vc_mcp.py:ro") for a in argv)
    assert "Bash" not in argv[argv.index("--tools") + 1]  # ni con execute: los comandos van al ordenador
    s = sesiones.managed_settings("execute", internet=False, vault=False, vc=True)["permissions"]
    assert "mcp__vc" in s["allow"] and "Bash" in s["deny"]
    plain = sesiones.docker_argv(tmp_path, req(), sesiones.prepare_dirs(tmp_path, SID))
    assert "--mcp-config" not in plain and not any(a.endswith(":/run/vc") for a in plain)


def test_subagentes_heredan_permisos(tmp_path):
    r = sesiones.validate({"session_id": SID, "prompt": "x", "level": "read", "subagents": True})
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID))
    tools = argv[argv.index("--tools") + 1].split(",")
    assert "Agent" in tools and "Bash" not in tools and "Edit" not in tools  # read sigue siendo read
    s = sesiones.managed_settings("read", internet=False, vault=False, subagents=True)["permissions"]
    assert "Agent" in s["allow"] and "Bash" in s["deny"]
    assert "Agent" not in sesiones.docker_argv(tmp_path, req(), sesiones.prepare_dirs(tmp_path, SID))[-1]


def test_coach_del_gym(tmp_path):
    with pytest.raises(ValueError):
        req(gym=True)  # sin vault no hay Coach
    r = req(gym=True, vault=True)
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert any(m.endswith(":/opt/gym/gym_mcp.py:ro") for m in mounts)
    assert any(m.endswith(":/opt/gym/gym_coach.py:ro") for m in mounts)
    assert any(m.endswith(":/vault:ro") for m in mounts)
    assert any(m.endswith(f"{SID}/gym:/gym") for m in mounts)
    cfg = argv[argv.index("--mcp-config") + 1]
    assert '"gym"' in cfg and '"vc"' not in cfg
    s = sesiones.managed_settings("read", internet=False, vault=True, gym=True)["permissions"]
    assert "mcp__gym" in s["allow"] and "Bash" in s["deny"]
    assert {"Read(//gym/**)", "Write(//gym/**)", "Edit(//vault/**)", "Read(//opt/**)"} <= set(s["deny"])
    assert "mcp__gym" not in sesiones.managed_settings("read", internet=False, vault=True)["permissions"]["allow"]


def _base(**k):
    return {"session_id": "12345678-1234-1234-1234-1234567890ab", "level": "read", "model": "sonnet", "prompt": "hola"} | k


def test_credencial_pos_valida_y_nunca_en_la_linea_de_comandos(tmp_path):
    import sesiones
    tok = "a" * 43
    req = sesiones.validate(_base(pos_token=tok))
    dirs = sesiones.prepare_dirs(tmp_path, req["session_id"])
    argv = sesiones.docker_argv(tmp_path, req, dirs)
    assert tok not in " ".join(argv) and "--mcp-config" in argv and any("pos_mcp.py" in a for a in argv)
    assert "mcp__pos" in sesiones.managed_settings("read", False, False, pos=True)["permissions"]["allow"]
    assert "mcp__pos" not in sesiones.managed_settings("read", False, False)["permissions"]["allow"]


def test_credencial_pos_rara_se_rechaza():
    import pytest
    import sesiones
    with pytest.raises(ValueError):
        sesiones.validate(_base(pos_token="$(evil)"))


def test_vault_limitada_a_su_apartado(tmp_path):
    (tmp_path / "Jarvis-Vault/Jarvis/Areas").mkdir(parents=True)
    (tmp_path / "Jarvis-Vault/Jarvis/Areas/Gym.md").write_text("x")
    r = req(vault=True, vault_paths=["Jarvis/Areas/Gym.md", "Jarvis/No-existe.md"])
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID) | {"settings": tmp_path / "s"})
    assert f"{tmp_path}/Jarvis-Vault/Jarvis/Areas/Gym.md:/vault/Jarvis/Areas/Gym.md:ro" in argv
    assert f"{tmp_path}/Jarvis-Vault:/vault:ro" not in argv and not [a for a in argv if "No-existe" in a]


@pytest.mark.parametrize("mal", [["../secrets"], ["/etc/passwd"], ["Jarvis/../../secrets"], ["a"] * 13])
def test_rutas_de_vault_no_validas(mal):
    with pytest.raises(ValueError):
        req(vault=True, vault_paths=mal)


def test_escritura_solo_en_jarvis_y_nunca_en_sistema(tmp_path):
    r = req(vault=True, vault_write=True, level="propose")
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID) | {"settings": tmp_path / "s"})
    assert f"{tmp_path}/Jarvis-Vault:/vault:ro" in argv
    assert f"{tmp_path}/Jarvis-Vault/Jarvis:/vault/Jarvis:rw" in argv and f"{tmp_path}/Jarvis-Vault/Jarvis/Sistema:/vault/Jarvis/Sistema:ro" in argv
    assert argv.index(f"{tmp_path}/Jarvis-Vault/Jarvis:/vault/Jarvis:rw") < argv.index(f"{tmp_path}/Jarvis-Vault/Jarvis/Sistema:/vault/Jarvis/Sistema:ro")
    m = sesiones.managed_settings("propose", False, True, vault_write=True)["permissions"]
    assert "Edit(//vault/Jarvis/**)" in m["allow"] and "Edit(//vault/Jarvis/Sistema/**)" in m["deny"]
    assert "Edit(//vault/**)" in sesiones.managed_settings("read", False, True)["permissions"]["deny"]


@pytest.mark.parametrize("kw", [{"vault": True, "vault_write": True, "level": "read"}, {"vault": False, "vault_write": True, "level": "propose"},
                                {"vault": True, "vault_write": True, "level": "propose", "vault_paths": ["Jarvis/Tareas.md"]}])
def test_escritura_solo_para_una_rutina(kw):
    with pytest.raises(ValueError):
        req(**kw)


def test_entregables_solo_la_carpeta_de_la_uni_y_con_escritura(tmp_path):
    r = req(level="propose", entregables=True)
    argv = sesiones.docker_argv(tmp_path, r, sesiones.prepare_dirs(tmp_path, SID))
    assert f"{tmp_path / 'archivos/Uni'}:/entregables:rw" in argv and "--add-dir" in argv
    assert (tmp_path / "archivos/Uni").is_dir()
    assert not any(a.startswith(f"{tmp_path / 'archivos'}:") for a in argv)  # nunca la carpeta común entera
    permisos = sesiones.managed_settings("propose", internet=False, vault=False, entregables=True)["permissions"]
    assert "Write(//entregables/**)" in permisos["allow"] and "Bash" in permisos["deny"]
    # Sin pedirlo, ni existe en el contenedor
    sin = sesiones.docker_argv(tmp_path, req(level="propose"), sesiones.prepare_dirs(tmp_path, SID))
    assert "/entregables" not in " ".join(sin)
    assert not any("/entregables" in a for a in sesiones.managed_settings("propose", False, False)["permissions"]["allow"])


def test_entregables_exige_escritura():
    with pytest.raises(ValueError):
        req(level="read", entregables=True)
