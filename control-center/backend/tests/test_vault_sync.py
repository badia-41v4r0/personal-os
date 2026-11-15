import json

import pytest

from app import db as dbm
from app.models import (Assessment, DecisionRecord, GradeItem, JobApplication, JobLead, JournalDay, StudyBlock, Subject, Task, VaultRecord,
                        Workout, WorkoutExercise, WorkoutSet)
from app.modules import vault_sync as vs

GYM = "# Gym\n## Registro\n\n### 2026-11-03 · Push\n- Press banca: 80×8, 80×8\n- Curl: 12×10\n"
NOTAS = """# N
## Resumen
| Asignatura | Fórmula | Mínimos | Nota actual | Estado |
|---|---|---|---|---|
| FP | 30 % PEC | PEC ≥ 4 | 7,5 | Bien |

---

## FP · Fundamentos
| Entregable | Peso | Entrega | Nota |
|---|---|---|---|
| PEC 1 | 18 % | 07/10 | 8 |
| PEC 2 | 18 % | 14/10 | |
"""
TAREAS = "## Pendientes\n- [ ] Llamar 📅 2026-11-10 #uni\n- [ ] Igual #personal\n- [ ] Igual #personal\n- [x] Hecha ✅ 2026-11-01\n"


@pytest.fixture()
def v(client, settings, monkeypatch):
    import gym_stats
    import tareas
    j = settings.vault / "Jarvis"
    (j / "Areas").mkdir(parents=True)
    (j / "Sistema").mkdir()
    (j / "Diario").mkdir()
    (j / "Areas/Gym.md").write_text(GYM)
    (j / "Areas/Notas-Uni.md").write_text(NOTAS)
    (j / "Areas/Trabajo.md").write_text("## Pipeline de candidaturas\n| Empresa | Puesto | Estado |\n|---|---|---|\n| ACME | SE | aplicado |\n\n## Otra\n")
    (j / "Tareas.md").write_text(TAREAS)
    (j / "Sistema/ofertas-vistas.json").write_text(json.dumps({"1": {"titulo": "SE", "empresa": "X", "puntos": "4", "visto": "2026-11-01"}}))
    (j / "Sistema/hechos.json").write_text(json.dumps({"tarea|2026-11-01|x": "2026-11-01"}))
    (j / "Diario/2026-11-03.md").write_text("# día\nbien")
    (j / "Diario/Semana 2026-10-26.md").write_text("# semana")
    (j / "Diario/2026-11-03.sync-conflict-1.md").write_text("no")
    monkeypatch.setattr(vs, "get_settings", lambda: settings)
    monkeypatch.setattr(tareas, "TAREAS", j / "Tareas.md", raising=False)
    monkeypatch.setattr(gym_stats, "gym_md", lambda: j / "Areas/Gym.md")
    return j


def n(m, **f):
    with dbm.session_scope() as s:
        return s.query(m).filter_by(**f).count()


def test_migra_todo(v, settings):
    (settings.root / "x") if False else None
    r = vs.run_all()
    assert not [k for k, x in r.items() if "error" in x and k not in ("uni",)], r
    assert n(Task) == 4 and n(Task, done=True) == 1  # las dos iguales son dos
    assert n(Workout) == 1 and n(WorkoutExercise) == 2 and n(WorkoutSet) == 3
    assert n(Subject) == 1 and n(GradeItem) == 2
    assert n(JobLead) == 1 and n(JobApplication) == 1
    assert n(JournalDay) == 2 and n(VaultRecord, kind="hecho") == 1


def test_repetir_no_duplica(v):
    vs.run_all()
    vs.run_all()
    assert n(Task) == 4 and n(WorkoutSet) == 3 and n(GradeItem) == 2 and n(JobApplication) == 1


def test_la_vault_no_se_toca(v):
    """Salvo el diario, que pasa a ser una copia: solo gana el aviso, sin perder nada."""
    from app.modules import mirror
    antes = {p: p.read_bytes() for p in v.rglob("*") if p.is_file()}
    vs.run_all()
    despues = {p: p.read_bytes() for p in v.rglob("*") if p.is_file()}
    assert antes.keys() == despues.keys()
    for p in antes:
        if p.name == "Gym.md":
            assert mirror.AVISO_GYM in despues[p].decode() and despues[p].decode().split("## Registro")[0].rstrip() == antes[p].decode().split("## Registro")[0].rstrip()
        elif "Diario" in p.parts and "sync-conflict" not in p.name:
            assert mirror.strip_journal_notice(despues[p].decode()) == antes[p].decode() and mirror.AVISO_DIARIO in despues[p].decode()
        else:
            assert antes[p] == despues[p], p


def test_lo_que_desaparece_de_la_nota_no_se_borra_de_la_base(v):
    vs.run_all()
    lineas = (v / "Tareas.md").read_text().splitlines()
    (v / "Tareas.md").write_text("\n".join(x for i, x in enumerate(lineas) if i != next(j for j, y in enumerate(lineas) if y.startswith("- ["))) + "\n")
    r = vs.run_all()
    assert r["tareas"]["descartados"] == 1 and n(Task) == 4  # la base manda: la línea borrada a mano se rehace
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.removed_at.is_(None)).count() == 4
    assert sum(1 for x in (v / "Tareas.md").read_text().splitlines() if x.startswith("- [")) == 4


def test_lo_que_vuelve_se_recupera(v):
    vs.run_all()
    (v / "Tareas.md").write_text("")
    vs.run_all()
    (v / "Tareas.md").write_text(TAREAS)
    vs.run_all()
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.removed_at.is_(None)).count() == 4


def test_marcar_hecha_se_refleja(v):
    vs.run_all()
    (v / "Tareas.md").write_text(TAREAS.replace("- [ ] Llamar", "- [x] Llamar"))
    vs.run_all()
    assert n(Task, done=True) == 2 and n(Task) == 4


def test_entreno_cambiado_a_mano_se_descarta(v, settings):
    """Desde el corte del 07/11 manda la base: lo editado en el registro de Gym.md se descarta y se guarda."""
    vs.run_all()
    (v / "Areas/Gym.md").write_text(GYM + "- Remo: 50×10\n")
    vs.run_all()
    assert n(Workout) == 1 and n(WorkoutExercise) == 2 and n(WorkoutSet) == 3
    assert "Remo" not in (v / "Areas/Gym.md").read_text()
    assert any("Remo" in f.read_text() for f in (settings.data_dir / "descartes/gym").iterdir())


def test_seccion_rota_no_para_las_demas(v, monkeypatch):
    def rota(db):
        raise RuntimeError("rota")
    monkeypatch.setattr(vs, "SECTIONS", tuple((k, rota if k == "registros" else f) for k, f in vs.SECTIONS))
    r = vs.run_all()
    assert "error" in r["registros"] and n(Task) == 4


def test_hechos_roto_no_se_da_por_vacio(v, settings):
    vs.run_all()
    (v / "Sistema/hechos.json").write_text("roto")
    r = vs.run_all()
    assert r["hechos"]["rehecha"] is True
    assert json.loads((v / "Sistema/hechos.json").read_text()) == {"tarea|2026-11-01|x": "2026-11-01"}
    assert any(f.read_text() == "roto" for f in (settings.data_dir / "descartes/uni").iterdir())


def test_decisiones_del_registro(client, settings, monkeypatch):
    from dataclasses import replace
    root = settings.data_dir / "raiz"
    root.mkdir()
    (root / "CLAUDE.md").write_text("# P\n## Registro\n### 2026-10-01 · Una\n- Texto\n### 2026-10-02 · Otra\n- Más\n## Fin\n")
    s2 = replace(settings, root=root)
    monkeypatch.setattr(vs, "get_settings", lambda: s2)
    with dbm.session_scope() as s:
        assert vs.sync_decisions(s)["origen"] == 2
    with dbm.session_scope() as s:
        vs.sync_decisions(s)
    assert n(DecisionRecord) == 2


def test_bloques_y_entregas(v, settings, monkeypatch):
    import uni
    (settings.vault / "Uni").mkdir(exist_ok=True)
    txt = "---\ninicio: 2026-11-02\nfin: 2026-11-08\n---\n## Plan diario\n| Lunes 02/11 | ARD · VM | — | FP · PEC |\n"
    from datetime import date
    monkeypatch.setattr(uni, "_semanas", lambda: [(date(2026, 11, 2), date(2026, 11, 8), txt)])
    monkeypatch.setattr(uni, "recoger", lambda h, d: {"entregas": [{"fecha": "2026-11-05", "hora": "23:59", "texto": "PEC", "hecho": False}]})
    with dbm.session_scope() as s:
        r = vs.sync_uni(s)
    assert r["entregas"] == 1 and r["bloques"] == 2 and n(StudyBlock) == 2 and n(Assessment) == 1
