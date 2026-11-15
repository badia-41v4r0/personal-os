"""Si la nota de origen se rompe, la base no la sigue: ni notas ni entregas de la uni se retiran de golpe."""
import pytest

from app import db as dbm
from app.models import Assessment, GradeItem
from app.modules import vault_sync as vs

NOTAS = """# N
## Resumen
| Asignatura | Fórmula | Mínimos | Nota actual | Estado |
|---|---|---|---|---|
| FP | 30 % PEC | PEC ≥ 4 | 7,5 | Bien |

## FP · Fundamentos
| Entregable | Peso | Entrega | Nota |
|---|---|---|---|
| PEC 1 | 18 % | 07/10 | 8 |
| PEC 2 | 18 % | 14/10 | |
"""


@pytest.fixture()
def sin_semanas(client, monkeypatch):
    import uni
    monkeypatch.setattr(uni, "_semanas", lambda: [])
    vs._avisadas.clear()
    return uni


def _entregas(n):
    return {"entregas": [{"fecha": f"2026-11-{5 + i:02d}", "hora": "23:59", "texto": f"PEC {i}", "hecho": False} for i in range(n)]}


def _activas(model):
    with dbm.session_scope() as s:
        return s.query(model).filter(model.removed_at.is_(None)).count()


def test_una_nota_de_entregas_rota_no_retira_nada(sin_semanas, settings, monkeypatch):
    monkeypatch.setattr(sin_semanas, "recoger", lambda h, d: _entregas(6))
    with dbm.session_scope() as s:
        vs.sync_uni(s)
    monkeypatch.setattr(sin_semanas, "recoger", lambda h, d: _entregas(1))  # de 6 a 1: una nota rota, no una edición
    with dbm.session_scope() as s:
        assert vs.sync_uni(s)["retiradas"] == 0
    assert _activas(Assessment) == 6
    avisos = list((settings.data_dir / "avisos").glob("*.json"))
    assert len(avisos) == 1 and "No he retirado nada" in avisos[0].read_text()
    with dbm.session_scope() as s:  # otra pasada con lo mismo: no repite el aviso
        vs.sync_uni(s)
    assert len(list((settings.data_dir / "avisos").glob("*.json"))) == 1


def test_una_edicion_normal_si_retira(sin_semanas, monkeypatch):
    monkeypatch.setattr(sin_semanas, "recoger", lambda h, d: _entregas(6))
    with dbm.session_scope() as s:
        vs.sync_uni(s)
    monkeypatch.setattr(sin_semanas, "recoger", lambda h, d: _entregas(4))  # quita dos de seis: edición legítima
    with dbm.session_scope() as s:
        assert vs.sync_uni(s)["retiradas"] == 2
    assert _activas(Assessment) == 4


def test_pocas_filas_no_activan_la_proteccion(sin_semanas, monkeypatch):
    monkeypatch.setattr(sin_semanas, "recoger", lambda h, d: _entregas(3))
    with dbm.session_scope() as s:
        vs.sync_uni(s)
    monkeypatch.setattr(sin_semanas, "recoger", lambda h, d: _entregas(0))  # con menos de 4 no hay umbral
    with dbm.session_scope() as s:
        assert vs.sync_uni(s)["retiradas"] == 3


def test_notas_de_la_uni_vaciadas_se_conservan(client, settings):
    vs._avisadas.clear()
    nota = settings.vault / "Jarvis/Areas/Notas-Uni.md"
    nota.parent.mkdir(parents=True)
    nota.write_text(NOTAS)
    with dbm.session_scope() as s:
        vs.sync_grades(s)
        for i in range(5):
            s.add(GradeItem(external_id=f"x{i}", subject="FP", title=f"Extra {i}"))
    with dbm.session_scope() as s:
        assert vs.sync_grades(s)["retiradas"] == 0  # el origen solo tiene 2 de 7 entregables
    assert _activas(GradeItem) == 7
