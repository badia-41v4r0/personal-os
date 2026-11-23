import importlib
import os
import json
import subprocess
import threading
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TOKEN = "t" * 40


@pytest.fixture()
def ha(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_HOSTAGENT_TOKEN", TOKEN)
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hostagent
    importlib.reload(hostagent)
    return hostagent


def test_sin_token(ha):
    c = TestClient(ha.app)
    assert c.get("/v1/metrics").status_code == 401
    assert c.get("/v1/metrics", headers={"Authorization": "Bearer malo"}).status_code == 401


def test_metricas_reales(ha):
    c = TestClient(ha.app)
    m = c.get("/v1/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert 0 <= m["cpu"]["pct"] <= 100 and m["memory"]["total"] > 0 and m["uptime_s"] > 0
    assert m["disks"]


@pytest.mark.parametrize("unit", ["sshd.service", "jarvis-x;rm -rf ~", "../jarvis-a.service", "jarvis-A.service"])
def test_logs_unidad_no_permitida(ha, unit):
    c = TestClient(ha.app)
    r = c.get(f"/v1/logs/unit/{unit}", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code in (403, 404)


@pytest.mark.parametrize("name", ["otra-app-db-1", "otra-postgres-1", "jarvis;ls"])
def test_logs_contenedor_no_permitido(ha, name):
    c = TestClient(ha.app)
    assert c.get(f"/v1/logs/container/{name}", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403


def test_auditoria_de_denegaciones(ha, tmp_path):
    TestClient(ha.app).get("/v1/logs/unit/sshd.service", headers={"Authorization": f"Bearer {TOKEN}"})
    assert "denied" in (tmp_path / "hostagent-audit.jsonl").read_text()


def test_limpieza_del_prompt(ha):
    assert ha.clean_prompt("hola\nadiós") == "hola ⏎ adiós"
    assert ha.clean_prompt("a\x1b[Ab\x07c\x00") == "a[Abc"
    assert ha.clean_prompt("oculto‮txet​") == "ocultotxet"


@pytest.mark.parametrize("rid", ["x", "../../a", "12345678-1234-1234-1234-1234567890ab tg", ""])
def test_prompt_run_id_invalido(ha, rid):
    c = TestClient(ha.app)
    r = c.post("/v1/jarvis/prompt", json={"run_id": rid, "text": "hola"}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 422


def test_prompt_sin_token(ha):
    c = TestClient(ha.app)
    r = c.post("/v1/jarvis/prompt", json={"run_id": "12345678-1234-1234-1234-1234567890ab", "text": "hola"})
    assert r.status_code == 401


@pytest.mark.parametrize("name,h", [("../x", "a" * 64), ("ok", "corta"), ("Mayus", "a" * 64), ("a;b", "a" * 64)])
def test_propuestas_validacion(ha, name, h):
    c = TestClient(ha.app)
    r = c.post(f"/v1/proposals/{name}/approve", json={"hash": h}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code in (404, 422)


def test_lectura_del_uso(ha):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    text = ("You are currently using your subscription\n\nCurrent session: 71% used · resets Oct 31, 11:40pm (Europe/Madrid)\n"
            "Current week (all models): 69% used · resets Nov 4, 7am (Europe/Madrid)\n")
    d = ha.parse_usage_text(text)
    assert d["five_hour"]["utilization"] == 0.71 and d["seven_day"]["utilization"] == 0.69
    z = ZoneInfo("Europe/Madrid")
    now = datetime(2026, 10, 31, 20, 0, tzinfo=z)
    assert ha.parse_reset("Oct 31, 11:40pm", "Europe/Madrid", now) == datetime(2026, 10, 31, 23, 40, tzinfo=z).timestamp()
    assert ha.parse_reset("Nov 4, 7am", "Europe/Madrid", now) == datetime(2026, 11, 4, 7, 0, tzinfo=z).timestamp()
    assert ha.parse_reset("Jan 2, 12am", "Europe/Madrid", datetime(2026, 12, 30, tzinfo=z)) == datetime(2027, 1, 2, 0, 0, tzinfo=z).timestamp()
    assert ha.parse_usage_text("Total cost: $0.00") is None and ha.parse_reset("mañana", "Europe/Madrid") is None


def test_uso_sin_token(ha):
    assert TestClient(ha.app).post("/v1/claude/usage").status_code == 401


def _rollout(path, *payloads):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps({"payload": p}) for p in payloads) + "\n")


def test_codex_lee_su_ultima_cuota(ha, tmp_path):
    s = tmp_path / "sessions/2026/11/03"
    _rollout(s / "rollout-a.jsonl",
             {"type": "token_count", "rate_limits": {"primary": {"used_percent": 84.0, "window_minutes": 43200, "resets_at": 1795793283}, "secondary": None}},
             {"type": "token_count", "rate_limits": None},
             {"type": "token_count", "rate_limits": {"primary": {"used_percent": 92.0, "window_minutes": 43200, "resets_at": 1795793283},
                                                     "secondary": {"used_percent": 3.0, "window_minutes": 300, "resets_at": 1}}})
    w = ha.codex_windows(tmp_path / "sessions")
    assert [(x["name"], x["utilization"]) for x in w] == [("monthly", .92), ("five_hour", .03)]
    assert ha.codex_windows(tmp_path / "nada") == []


def test_codex_sin_lectura_no_esta_disponible(ha, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(ha, "_cli", lambda *_: "/usr/bin/codex")
    r = TestClient(ha.app).post("/v1/models/codex-terra/usage", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert r["available"] is False and r["windows"] == []


def test_antigravity_parser(ha):
    out = json.dumps({"command": {"data": {"groups": [
        {"name": "Gemini Models", "buckets": [{"window": "weekly", "remaining_fraction": .9, "reset_time": "2026-11-10T13:31:10Z"}]},
        {"name": "Claude and GPT models", "buckets": [{"id": "5h", "remaining_fraction": 1.0, "reset_time": "x"}]}]}}})
    assert ha.parse_antigravity_windows(out, "antigravity-flash")[0] == {"name": "weekly", "utilization": .1, "resets_at": "2026-11-10T13:31:10Z"}
    assert ha.parse_antigravity_windows(out, "antigravity-opus")[0]["name"] == "five_hour"
    for raro in ("", "[1]", '{"command":null}', "no es json"):
        assert ha.parse_antigravity_windows(raro, "antigravity-opus") == []


def test_antigravity_no_bloquea_metricas_ni_ve_el_token(ha, monkeypatch):
    seen, dentro, salir = {}, threading.Event(), threading.Event()

    def lento(argv, **kw):
        seen.update(kw)
        dentro.set()
        salir.wait(5)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(ha, "_cli", lambda *_: "/usr/bin/antigravity")
    monkeypatch.setattr(ha.subprocess, "run", lento)
    t = threading.Thread(target=ha.antigravity_stdout)
    t.start()
    assert dentro.wait(5)
    fin = threading.Event()
    threading.Thread(target=lambda: (ha.cached("metrics", 3, lambda: 1), fin.set()), daemon=True).start()
    assert fin.wait(1), "el lock de la caché quedó retenido"
    salir.set()
    t.join()
    assert "CC_HOSTAGENT_TOKEN" not in seen["env"] and seen["stdin"] == subprocess.DEVNULL and seen["cwd"]


def test_claude_no_se_consulta_por_la_ruta_de_modelos(ha):
    assert TestClient(ha.app).post("/v1/models/claude/usage", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403


def test_codex_informa_cuando_se_midio(ha, tmp_path):
    f = tmp_path / "rollout-1.jsonl"
    f.write_text('{"payload": {"rate_limits": {"primary": {"used_percent": 10, "window_minutes": 300}}}}\n')
    os.utime(f, (1000, 1000))
    windows, measured = ha.codex_latest(tmp_path)
    assert windows and measured == 1000


def test_voz_borra_el_audio_siempre(ha, tmp_path, monkeypatch, client=None):
    import base64
    from fastapi.testclient import TestClient
    monkeypatch.setattr(ha, "ROOT", tmp_path)
    vistos = []

    def fake(argv, **k):
        vistos.append(list((tmp_path / "data/voz/entrada").iterdir()))
        return subprocess.CompletedProcess(argv, 0, stdout="hola jarvis\n", stderr="")
    monkeypatch.setattr(ha.subprocess, "run", fake)
    c = TestClient(ha.app)
    h = {"Authorization": f"Bearer {ha.TOKEN if hasattr(ha, 'TOKEN') else ''}"}
    ha.app.dependency_overrides[ha.auth] = lambda: None
    r = c.post("/v1/voice/transcribe", json={"audio": base64.b64encode(b"sonido").decode()}, headers=h)
    ha.app.dependency_overrides.clear()
    assert r.json() == {"text": "hola jarvis"} and len(vistos[0]) == 1
    assert list((tmp_path / "data/voz/entrada").iterdir()) == []


def test_encierro_oculta_lo_personal(ha, tmp_path):
    (tmp_path / "Desktop").mkdir()
    (tmp_path / ".ssh").mkdir()
    argv = ha.jail_argv(tmp_path, tmp_path / "w", tmp_path / ".codex")
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    assert str(tmp_path / "Desktop") in tmpfs and str(tmp_path / ".ssh") in tmpfs
    assert "--unshare-pid" in argv and argv.count("--bind") == 2


def test_consulta_solo_a_proveedores_conocidos(ha):
    from fastapi.testclient import TestClient
    ha.app.dependency_overrides[ha.auth] = lambda: None
    r = TestClient(ha.app).post("/v1/models/rm-rf/ask", json={"prompt": "x", "model": "m-1"})
    r2 = TestClient(ha.app).post("/v1/models/codex-terra/ask", json={"prompt": "x", "model": "$(evil)"})
    ha.app.dependency_overrides.clear()
    assert r.status_code == 403 and r2.status_code == 422


def test_horarios_ida_y_vuelta():
    os.environ.setdefault("CC_HOSTAGENT_TOKEN", TOKEN)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hostagent as h
    assert h.horarios(["*-*-* 06,18:45:00"]) == ([], ["06:45", "18:45"])
    assert h.horarios(["Sun *-*-* 20:00:00"]) == (["Sun"], ["20:00"])
    assert h.horarios(["Mon..Wed *-*-* 07:00"]) == (["Mon", "Tue", "Wed"], ["07:00"])
    assert h.calendars_for([], ["07:00"]) == ["*-*-* 07:00:00"]
    assert h.calendars_for(["Sun", "Mon"], ["20:00", "08:30"]) == ["Mon,Sun *-*-* 08:30:00", "Mon,Sun *-*-* 20:00:00"]
    assert h.calendars_for(list(h.DIAS), ["07:00"]) == ["*-*-* 07:00:00"]
    for dias, horas in (([], []), (["Lun"], ["07:00"]), ([], ["25:00"]), ([], ["07:00;rm"]), ([], ["0" + str(i) + ":00" for i in range(7)])):
        with pytest.raises(ValueError):
            h.calendars_for(dias, horas)
    with pytest.raises(ValueError):
        h.horarios(["hourly"])


def test_credenciales_del_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("POS_INSTANCE=posdev\nCLAUDE_CODE_OAUTH_TOKEN=\n")
    monkeypatch.setenv("POS_ENV_FILE", str(env))
    monkeypatch.setenv("CC_HOSTAGENT_TOKEN", TOKEN)
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hostagent
    importlib.reload(hostagent)
    c = TestClient(hostagent.app)
    h = {"Authorization": f"Bearer {TOKEN}"}
    assert c.get("/v1/credenciales", headers=h).json()["CLAUDE_CODE_OAUTH_TOKEN"] is False
    # Formato malo, clave no permitida o sin token: no se escribe nada
    assert c.put("/v1/credenciales/CLAUDE_CODE_OAUTH_TOKEN", json={"valor": "hola"}, headers=h).status_code == 422
    assert c.put("/v1/credenciales/CC_HOSTAGENT_TOKEN", json={"valor": "x" * 40}, headers=h).status_code == 404
    assert c.put("/v1/credenciales/CLAUDE_CODE_OAUTH_TOKEN", json={"valor": "sk-ant-" + "a" * 30}).status_code == 401
    assert "sk-ant" not in env.read_text()
    tok = "sk-ant-oat01-" + "b" * 40
    r = c.put("/v1/credenciales/CLAUDE_CODE_OAUTH_TOKEN", json={"valor": tok}, headers=h)
    assert r.status_code == 200 and r.json()["CLAUDE_CODE_OAUTH_TOKEN"] is True and tok not in r.text
    assert env.read_text() == f"POS_INSTANCE=posdev\nCLAUDE_CODE_OAUTH_TOKEN={tok}\n"  # el resto, igual
    assert oct(env.stat().st_mode & 0o777) == "0o600"
    assert c.put("/v1/credenciales/TELEGRAM_CHAT_ID", json={"valor": "-100123"}, headers=h).json()["TELEGRAM_CHAT_ID"] is True
    assert env.read_text().endswith("TELEGRAM_CHAT_ID=-100123\n")
    assert c.delete("/v1/credenciales/TELEGRAM_CHAT_ID", headers=h).json()["TELEGRAM_CHAT_ID"] is False
    assert tok not in (tmp_path / "hostagent-audit.jsonl").read_text()
