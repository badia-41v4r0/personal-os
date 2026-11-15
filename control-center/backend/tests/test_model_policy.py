import asyncio
import json
import time
from datetime import datetime, timedelta

from app import config, model_usage
from app.model_policy import choose, over_limit

NOW = datetime(2026, 11, 4, 12)
OK = {"name": "weekly", "utilization": .1}


def row(available=True, windows=(OK,), model="x"):
    return {"available": available, "windows": list(windows), "model": model}


def test_policy_prefers_claude_until_weekly_85():
    rows = {"claude": row(windows=[{"name": "five_hour", "utilization": .99}, {"name": "seven_day", "utilization": .84}])}
    assert choose(rows).provider == "claude"
    rows["claude"] = row(windows=[{"name": "seven_day", "utilization": .85}])
    rows["antigravity-flash"] = row(windows=[{"name": "daily", "utilization": .2}], model="Gemini 3.8 Flash")
    assert choose(rows).provider == "antigravity-flash"


def test_policy_alternatives_use_any_window_then_claude_last_resort():
    rows = {
        "claude": row(windows=[{"name": "weekly", "utilization": .9}]),
        "antigravity-flash": row(windows=[{"name": "daily", "utilization": .9}]),
        "antigravity-opus": row(windows=[{"name": "daily", "utilization": .9}]),
        "codex-terra": row(False),
    }
    out = choose(rows)
    assert out.provider == "claude" and out.emergency
    assert over_limit([{"utilization": .85}])
    assert not over_limit([{"utilization": .849}])


def test_complete_fallback_chain_transitions():
    rows = {
        "claude": row(windows=[{"name": "seven_day", "utilization": 0.84}]),
        "antigravity-flash": row(model="Gemini 3.8 Flash"),
        "antigravity-opus": row(model="Claude Opus 4.6"),
        "codex-terra": row(model="GPT-5.6 Terra"),
    }
    assert choose(rows).provider == "claude"
    rows["claude"] = row(windows=[{"name": "seven_day", "utilization": 0.85}])
    assert choose(rows).provider == "antigravity-flash"
    rows["antigravity-flash"] = row(windows=[{"name": "daily", "utilization": 0.85}])
    assert choose(rows).provider == "antigravity-opus"
    rows["antigravity-opus"] = row(windows=[{"name": "daily", "utilization": 0.85}])
    assert choose(rows).provider == "codex-terra"
    rows["codex-terra"] = row(available=False)
    emergency = choose(rows)
    assert emergency.provider == "claude" and emergency.emergency
    rows["claude"] = row(available=False)
    assert choose(rows).provider == ""


def test_sin_lectura_no_se_elige():
    full = [{"name": "seven_day", "utilization": .99}]
    # Terra instalado pero sin ventanas: no se sabe si queda cuota
    out = choose({"claude": row(windows=full), "codex-terra": row(windows=[])})
    assert out.provider == "claude" and out.emergency
    # Claude sin ventana semanal tampoco se da por bueno
    assert choose({"claude": row(windows=[{"name": "five_hour", "utilization": .1}]), "antigravity-flash": row()}).provider == "antigravity-flash"


def test_lectura_vieja_no_decide():
    viejo = (NOW - timedelta(hours=1)).isoformat() + "Z"
    rows = {"claude": row(windows=[{"name": "seven_day", "utilization": .1}]) | {"ts": viejo}, "antigravity-flash": row() | {"ts": viejo}}
    assert choose(rows, NOW).provider == ""


def test_una_ventana_reiniciada_ya_no_cuenta():
    reset = (NOW - timedelta(minutes=1)).isoformat() + "Z"
    assert choose({"claude": row(windows=[{"name": "seven_day", "utilization": .99, "resets_at": reset}])}, NOW).provider == "claude"
    assert choose({"claude": row(windows=[{"name": "seven_day", "utilization": .99, "resets_at": "2026-11-05T00:00:00+01:00"}])}, NOW).emergency


def test_el_bucle_sobrevive_a_un_error(monkeypatch):
    n = []

    async def boom():
        n.append(1)
        if len(n) == 1:
            raise RuntimeError("database is locked")

    real = asyncio.sleep

    async def fast(_):
        await real(0)

    async def run():
        monkeypatch.setattr(model_usage, "probe_all", boom)
        monkeypatch.setattr(model_usage, "latest", lambda: {"claude": {}})
        monkeypatch.setattr(model_usage.asyncio, "sleep", fast)
        t = asyncio.ensure_future(model_usage.loop())
        while len(n) < 2:
            await real(0)
        assert not t.done()
        t.cancel()

    asyncio.run(run())


def test_claude_se_pregunta_una_vez_y_se_publica(client, monkeypatch):
    calls = []
    # Reinicios siempre en el futuro: con fechas fijas la prueba caducaba (la ventana ya "reiniciada" no cuenta).
    ahora = int(time.time())
    cinco_h, semanal = ahora + 3 * 3600, ahora + 3 * 86400

    async def usage(path, **_):
        calls.append(path)
        if path == "/v1/claude/usage":
            return {"five_hour": {"utilization": .02, "resets_at": cinco_h}, "seven_day": {"utilization": .9, "resets_at": semanal}, "cached": False}
        if path.endswith("antigravity-flash/usage"):
            return {"available": True, "windows": [{"name": "weekly", "utilization": .04, "resets_at": "2026-11-10T13:31:10+01:00"}]}
        return {"available": False, "windows": [], "error": "x"}

    monkeypatch.setattr(model_usage.hostagent, "call", usage)
    monkeypatch.setattr(model_usage.claude_usage.hostagent, "call", usage)
    asyncio.run(model_usage.probe_all())
    assert sum("claude" in c for c in calls) == 1 and "/v1/models/claude/usage" not in calls
    d = json.loads((config.get_settings().data_dir / "models-status.json").read_text())
    assert d["choice"]["provider"] == "antigravity-flash"
    assert [w["name"] for w in d["providers"]["claude"]["windows"]] == ["five_hour", "seven_day"]
    # La zona del reinicio se convierte a UTC, no se tira
    assert d["providers"]["antigravity-flash"]["windows"][0]["resets_at"] == "2026-11-10T12:31:10Z"


def test_cuota_vieja_conserva_la_hora_de_medida(client):
    from datetime import datetime, timedelta, timezone

    from app import model_usage
    hace = datetime.now(timezone.utc) - timedelta(days=3)
    raw = {"available": True, "windows": [{"name": "monthly", "utilization": 0.1}], "measured_at": hace.timestamp()}
    out = model_usage.record("codex-terra", raw)
    ts = datetime.fromisoformat(out["ts"].rstrip("Z"))
    assert abs((ts - hace.replace(tzinfo=None)).total_seconds()) < 2
