"""Esquema del panel. SQLite guarda solo datos propios del panel; el conocimiento sigue en Obsidian
y las conversaciones de Jarvis siguen en las transcripciones de Claude Code (aquí solo referencias)."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="admin")  # admin | viewer
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # El usuario inicial (admin/admin) tiene que cambiar usuario y contraseña antes de usar el panel
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthSession(Base):
    """Sesión de navegador. Solo se guarda el hash del token de la cookie."""
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class Event(Base):
    """Bus de eventos persistente: el id es secuencial y sirve para reanudar tras una desconexión."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="backend")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))  # usuario, agente o sistema
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="ok")  # ok | denied | error
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    # Trazabilidad y cadena: cada fila incluye la huella de la anterior, así que borrar o cambiar una se detecta
    actor_type: Mapped[str] = mapped_column(String(12), default="user")
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    action_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")

class ChatSession(Base):
    """Conversación. kind=main es la sesión compartida con Telegram (tmux 'jarvis')."""
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # main | independent | runtime
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent_definitions.id"), nullable=True)
    workdir: Mapped[str] = mapped_column(String(512), default="")
    model: Mapped[str] = mapped_column(String(32), default="sonnet")
    claude_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle | running | error | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    """Mensajes enviados desde el panel y referencias a los de la transcripción (no se copian enteros)."""
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    channel: Mapped[str] = mapped_column(String(16))  # web | telegram | voz | sistema
    content: Mapped[str] = mapped_column(Text, default="")
    transcript_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug, igual que el nombre en Claude Code
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(16), default="panel")  # repo (agent/.claude/agents) | panel
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active | inactive
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_definitions.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON)  # instrucciones, herramientas, capacidades (read/propose/execute)…
    rendered: Mapped[str] = mapped_column(Text, default="")  # el .md en el formato real de Claude Code
    author: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|error|interrupted
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    """Índice de aprobaciones. La fuente sigue siendo la de siempre (Propuestas/, colas); aquí se guarda
    la decisión tomada desde el panel y su resultado."""
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # propuesta | encargo | ayudante | repo | vc | agente
    ref: Mapped[str] = mapped_column(String(255))
    requested_by: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected|done|error
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VirtualComputer(Base):
    __tablename__ = "virtual_computers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    profile: Mapped[str] = mapped_column(String(32))  # terminal | browser | desktop
    owner_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persistence: Mapped[str] = mapped_column(String(16), default="ephemeral")  # ephemeral|persistent|ttl
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    internet: Mapped[bool] = mapped_column(Boolean, default=False)
    container_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="created")
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VirtualComputerEvent(Base):
    __tablename__ = "virtual_computer_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vc_id: Mapped[str] = mapped_column(ForeignKey("virtual_computers.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    type: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(512))  # dentro de data/control-center/attachments
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class MetricSample(Base):
    """Una muestra por minuto de las métricas del host (se guardan 14 días)."""
    __tablename__ = "metric_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    cpu: Mapped[float] = mapped_column(default=0.0)
    mem: Mapped[float] = mapped_column(default=0.0)
    swap: Mapped[float] = mapped_column(default=0.0)
    temp: Mapped[float | None] = mapped_column(nullable=True)
    gpu: Mapped[float | None] = mapped_column(nullable=True)
    vram: Mapped[float | None] = mapped_column(nullable=True)
    gpu_temp: Mapped[float | None] = mapped_column(nullable=True)
    disk: Mapped[float] = mapped_column(default=0.0)  # el disco más lleno
    net_sent: Mapped[int] = mapped_column(BigInteger, default=0)
    net_recv: Mapped[int] = mapped_column(BigInteger, default=0)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), index=True)  # regla:objeto, una abierta por clave
    severity: Mapped[str] = mapped_column(String(16))  # info | warning | critical
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)


class ClaudeUsage(Base):
    """Uso del límite de la suscripción de Claude (lo devuelve Claude Code en cada respuesta: rate_limit_event)."""
    __tablename__ = "claude_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    five_hour: Mapped[float | None] = mapped_column(nullable=True)  # 0–1
    five_hour_resets: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seven_day: Mapped[float | None] = mapped_column(nullable=True)
    seven_day_resets: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="probe")  # probe | session


class ProviderUsage(Base):
    """Una lectura real de la cuota de cada proveedor/modelo."""
    __tablename__ = "provider_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(48), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(96))
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    windows: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(16), default="probe")


# ---------- Gym 2.0 ----------
# Los entrenos siguen en Areas/Gym.md (fuente de verdad, la rellenan Telegram y el importador de Hevy). Aquí solo
# lo que es del entrenador: rutinas y sesiones planificadas (con versiones), ajustes y alias de ejercicios,
# sensaciones, decisiones, informes y la trazabilidad de lo importado de Hevy.

class GymRoutine(Base):
    __tablename__ = "gym_routines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active | archived
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymRoutineVersion(Base):
    __tablename__ = "gym_routine_versions"
    __table_args__ = (UniqueConstraint("routine_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    routine_id: Mapped[str] = mapped_column(ForeignKey("gym_routines.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON)  # {"dias": {"0": {"nombre", "ejercicios": [...]}}, "notas"}
    author: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, default="")
    changes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymPlannedSession(Base):
    __tablename__ = "gym_planned_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # aceptada | pospuesta | hecha | omitida | descartada | sustituida
    status: Mapped[str] = mapped_column(String(16), default="aceptada")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    workout_id: Mapped[str | None] = mapped_column(String(80), nullable=True)  # id de la sesión de Gym.md
    link_mode: Mapped[str] = mapped_column(String(8), default="none")  # auto | manual | none
    origin_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # si se reprogramó
    routine_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    routine_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymPlannedVersion(Base):
    __tablename__ = "gym_planned_versions"
    __table_args__ = (UniqueConstraint("planned_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_id: Mapped[str] = mapped_column(ForeignKey("gym_planned_sessions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    exercises: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymExerciseSetting(Base):
    """Ajustes por ejercicio (rango, series, incremento, método, descanso, músculos). Vacío = valores por categoría."""
    __tablename__ = "gym_exercise_settings"
    exercise_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymExerciseAlias(Base):
    """Une un nombre (normalizado) a un ejercicio: corrige asociaciones sin tocar Gym.md."""
    __tablename__ = "gym_exercise_aliases"
    alias: Mapped[str] = mapped_column(String(160), primary_key=True)
    exercise_id: Mapped[str] = mapped_column(String(120), index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymPause(Base):
    """Periodo sin entrenar (enfermedad, lesión, vacaciones…). Sin fin = en curso. El motor lo usa para no leerlo
    como abandono y para proponer una vuelta prudente."""
    __tablename__ = "gym_pauses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start: Mapped[str] = mapped_column(String(10), index=True)
    end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(String(16), default="enfermedad")  # enfermedad | lesion | vacaciones | otro
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymRecoveryLog(Base):
    __tablename__ = "gym_recovery_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), unique=True)
    energia: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1–5
    sueno: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sueno_horas: Mapped[float | None] = mapped_column(nullable=True)
    agujetas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    motivacion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estres: Mapped[int | None] = mapped_column(Integer, nullable=True)
    molestia_zona: Mapped[str] = mapped_column(String(64), default="")
    molestia_intensidad: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1–5
    notas: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymCoachDecision(Base):
    """Historial de decisiones del entrenador: qué vio, con qué datos, qué recomendó, por qué y qué pasó después."""
    __tablename__ = "gym_coach_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    apply_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), default="ejercicio")  # ejercicio | musculo | rutina | general
    target: Mapped[str] = mapped_column(String(160), default="")
    exercise_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # subir_peso | mantener | bajar_peso | mas_reps | reducir_volumen | cambiar_ejercicio | frecuencia | reorganizar | descarga | otro
    kind: Mapped[str] = mapped_column(String(24))
    situation: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[dict] = mapped_column(JSON, default=dict)  # {"peso", "reps"} si aplica
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # p. ej. la rutina propuesta
    status: Mapped[str] = mapped_column(String(16), default="propuesta")  # propuesta | aceptada | rechazada | aplicada
    source: Mapped[str] = mapped_column(String(16), default="motor")  # motor | coach | usuario
    evaluation: Mapped[dict] = mapped_column(JSON, default=dict)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class GymReport(Base):
    __tablename__ = "gym_reports"
    __table_args__ = (UniqueConstraint("kind", "period_start"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # semanal | mensual
    period_start: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[str] = mapped_column(String(10))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class GymImport(Base):
    __tablename__ = "gym_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(16), default="hevy_csv")
    filename: Mapped[str] = mapped_column(String(255), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="preview")  # preview | applied | error
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(64), default="")


class GymHevyWorkout(Base):
    """Trazabilidad de cada entreno de Hevy: id externo (hash de título + inicio), duración y filas originales."""
    __tablename__ = "gym_hevy_workouts"
    external_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    title: Mapped[str] = mapped_column(String(160))
    start_time: Mapped[str] = mapped_column(String(32))
    end_time: Mapped[str] = mapped_column(String(32), default="")
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    in_gym_md: Mapped[bool] = mapped_column(Boolean, default=False)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    import_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """Aviso para el usuario. La bandeja del panel es la fuente: el push solo es una forma de entregarlo."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(12), default="info")  # critical | action | info | silent
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(255), default="/avisos/")
    source: Mapped[str] = mapped_column(String(48), default="sistema", index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    pushed: Mapped[int] = mapped_column(Integer, default=0)  # dispositivos que lo aceptaron


class PushSubscription(Base):
    """Un dispositivo suscrito a Web Push. El endpoint lo da el navegador (en iPhone, el servicio de Apple)."""
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(1024), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")


class Action(Base):
    """Toda escritura de un agente pasa por aquí: qué pidió, por qué, quién decidió y qué ocurrió."""
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    capability: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[int] = mapped_column(Integer)  # 1 automático | 2 con reglas | 3 con aprobación
    status: Mapped[str] = mapped_column(String(16), index=True)  # pending|executing|done|failed|rejected|expired|denied|undone
    actor: Mapped[str] = mapped_column(String(80))
    actor_type: Mapped[str] = mapped_column(String(12))  # user | agent | system
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(String(300), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    tainted: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(500), default="")
    decided_by: Mapped[str] = mapped_column(String(80), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Policy(Base):
    """Ajuste del usuario sobre el nivel de una capacidad. Ningún agente puede escribir aquí."""
    __tablename__ = "policies"
    capability: Mapped[str] = mapped_column(String(80), primary_key=True)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(80), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Revocation(Base):
    """Permiso retirado a un agente, a una capacidad o a ambos ("*" = todos)."""
    __tablename__ = "revocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent: Mapped[str] = mapped_column(String(80), default="*")
    capability: Mapped[str] = mapped_column(String(80), default="*")
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemFlag(Base):
    __tablename__ = "system_flags"
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")
    updated_by: Mapped[str] = mapped_column(String(80), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Source(Base):
    """De dónde sale un dato. Sin procedencia no hay forma de distinguir lo dicho de lo supuesto."""
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # user | agent | import | vault | system
    uri: Mapped[str] = mapped_column(String(500), default="")
    external_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    trust: Mapped[str] = mapped_column(String(12), default="system")  # user | system | external
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Fact(Base):
    """Un hecho con dos tiempos: cuándo fue cierto (valid_*) y cuándo lo supo el sistema (recorded_at)."""
    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(80), index=True)
    predicate: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification: Mapped[str] = mapped_column(String(12), default="reported")  # inferred|reported|imported|confirmed
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)


class LifeEvent(Base):
    """Lo que pasó. Solo se añade: una corrección es otro evento que apunta al anterior."""
    __tablename__ = "life_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    corrects_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EntityLink(Base):
    __tablename__ = "entity_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_type: Mapped[str] = mapped_column(String(40), index=True)
    from_id: Mapped[str] = mapped_column(String(64), index=True)
    to_type: Mapped[str] = mapped_column(String(40), index=True)
    to_id: Mapped[str] = mapped_column(String(64), index=True)
    relation: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("from_type", "from_id", "to_type", "to_id", "relation"),)


class DecisionRecord(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decided_on: Mapped[str] = mapped_column(String(10), index=True)
    domain: Mapped[str] = mapped_column(String(32), default="general", index=True)
    title: Mapped[str] = mapped_column(String(200))
    context: Mapped[str] = mapped_column(Text, default="")
    choice: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | pending | abandoned | replaced
    review_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    outcome: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeDoc(Base):
    """Documento indexado (la vault manda: aquí solo el rastro para reindexar lo que cambia)."""
    __tablename__ = "knowledge_docs"
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RunToken(Base):
    """Credencial de una ejecución: dura lo que el turno y solo abre sus herramientas."""
    __tablename__ = "run_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent: Mapped[str] = mapped_column(String(80))
    tools: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    tainted: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class LedgerAccount(Base):
    """Plan de cuentas. Las categorías de gasto e ingreso son cuentas: `expense:comida:super`."""
    __tablename__ = "ledger_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(12), index=True)  # asset | liability | equity | income | expense
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    institution: Mapped[str] = mapped_column(String(80), default="")
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class JournalEntry(Base):
    """Asiento. Una vez `posted` no cambia: se corrige con otro asiento que lo revierte (lo impone la base de datos)."""
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_date: Mapped[str] = mapped_column(String(10), index=True)
    description: Mapped[str] = mapped_column(String(300))
    counterparty: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(10), default="posted", index=True)  # pending | posted
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Posting(Base):
    __tablename__ = "postings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(8), default="EUR")


class BalanceAssertion(Base):
    """Saldo real según el banco en una fecha: si el ledger no llega a esa cifra, hay un descuadre."""
    __tablename__ = "balance_assertions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"), index=True)
    as_of: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))
    filename: Mapped[str] = mapped_column(String(200), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CategoryRule(Base):
    """Regla de categorización: si la descripción contiene `pattern`, va a esa cuenta. Sin modelo."""
    __tablename__ = "category_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(120), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))


class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))
    month: Mapped[str] = mapped_column(String(7), index=True)  # AAAA-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    __table_args__ = (UniqueConstraint("account_id", "month"),)


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    area: Mapped[str] = mapped_column(String(32), default="personal", index=True)
    horizon: Mapped[str] = mapped_column(String(8), default="medio")  # corto | medio | largo
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active | done | abandoned
    target_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    why: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Habit(Base):
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HabitLog(Base):
    __tablename__ = "habit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    __table_args__ = (UniqueConstraint("habit_id", "day"),)


class HealthLog(Base):
    """Una medida con su fecha. Solo se añade: el historial es el dato."""
    __tablename__ = "health_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    metric: Mapped[str] = mapped_column(String(32), index=True)  # peso | cintura | sueno | energia…
    value: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CheckIn(Base):
    """Check-in de la mañana o de la noche: uno por día y franja (se puede corregir, no duplicar)."""
    __tablename__ = "checkins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    slot: Mapped[str] = mapped_column(String(8))  # manana | noche
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 (mal) a 5 (muy bien)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 a 5
    sleep_h: Mapped[float | None] = mapped_column(Float, nullable=True)  # horas dormidas (mañana)
    intention: Mapped[str] = mapped_column(String(300), default="")  # lo más importante de hoy (mañana)
    note: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("day", "slot"),)


class JobApplication(Base):
    __tablename__ = "job_applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="interés", index=True)
    link: Mapped[str] = mapped_column(String(500), default="")
    next_step: Mapped[str] = mapped_column(String(300), default="")
    follow_up: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LifestyleItem(Base):
    __tablename__ = "lifestyle_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # viaje | actividad | compra | garantia | suscripcion | interes
    title: Mapped[str] = mapped_column(String(200))
    day: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)  # fecha clave: salida, compra, vencimiento
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    """Tareas en la base de datos. `removed_at`: desapareció del origen; nunca se borra."""
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    text: Mapped[str] = mapped_column(Text)
    area: Mapped[str] = mapped_column(String(32), default="personal", index=True)
    due: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    done_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Workout(Base):
    __tablename__ = "workouts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(120))
    hevy_title: Mapped[str] = mapped_column(String(200), default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    source_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200), index=True)
    exercise_key: Mapped[str] = mapped_column(String(120), default="", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("workout_exercises.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    reps: Mapped[int] = mapped_column(Integer)
    warmup: Mapped[bool] = mapped_column(Boolean, default=False)
    failure: Mapped[bool] = mapped_column(Boolean, default=False)
    drop_set: Mapped[bool] = mapped_column(Boolean, default=False)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)


class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    formula: Mapped[str] = mapped_column(String(300), default="")
    minimums: Mapped[str] = mapped_column(String(300), default="")
    current_grade: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(300), default="")
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GradeItem(Base):
    __tablename__ = "grade_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    subject: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300))
    weight: Mapped[str] = mapped_column(String(120), default="")
    due: Mapped[str] = mapped_column(String(40), default="")
    grade: Mapped[str] = mapped_column(String(32), default="")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Assessment(Base):
    """Entregas de las notas semanales."""
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    due: Mapped[str] = mapped_column(String(10), index=True)
    due_time: Mapped[str] = mapped_column(String(5), default="")
    title: Mapped[str] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyBlock(Base):
    __tablename__ = "study_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    slot: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("day", "slot"),)


class JobLead(Base):
    __tablename__ = "job_leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200), default="")
    place: Mapped[str] = mapped_column(String(200), default="")
    link: Mapped[str] = mapped_column(String(500), default="")
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    seen_on: Mapped[str] = mapped_column(String(10), index=True)


class JournalDay(Base):
    """Copia del diario. La vault manda: aquí queda consultable junto a lo demás."""
    __tablename__ = "journal_days"
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # dia | semana
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


class VaultRecord(Base):
    """Datos tabulares sin módulo propio todavía (cobros, hechos marcados…): no se pierden ni se les fuerza un esquema."""
    __tablename__ = "vault_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("kind", "external_id"),)


class FinanceAnalysis(Base):
    """Análisis general del agente de finanzas. Se muestra solo el último; los anteriores quedan como historial."""
    __tablename__ = "finance_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    content: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(80), default="finanzas")


class EduCard(Base):
    """Tarjeta de repaso espaciado (SM-2). Nace de las notas de la uni o de lo que propone el tutor."""
    __tablename__ = "edu_cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="concepto")  # concepto | examen
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(300), default="")
    author: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    due: Mapped[str] = mapped_column(String(10), index=True)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval: Mapped[int] = mapped_column(Integer, default=0)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_review: Mapped[str] = mapped_column(String(10), default="")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class EduReview(Base):
    __tablename__ = "edu_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("edu_cards.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    grade: Mapped[int] = mapped_column(Integer)  # 0 otra vez · 3 difícil · 4 bien · 5 fácil
    mode: Mapped[str] = mapped_column(String(16), default="repaso")  # repaso | simulacro


class EduStudySession(Base):
    """Tiempo real de estudio de un bloque: calibra el plan, que asume bloques de 2 h."""
    __tablename__ = "edu_study_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    subject: Mapped[str] = mapped_column(String(32), default="", index=True)
    label: Mapped[str] = mapped_column(String(300), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seconds: Mapped[int] = mapped_column(Integer, default=0)


class EduDeliveryState(Base):
    """Estado de una entrega más fino que hecha/no hecha. Marcarla como entregada sigue yendo por uni.check."""
    __tablename__ = "edu_delivery_states"
    key: Mapped[str] = mapped_column(String(800), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="sin_empezar")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EduCanvasItem(Base):
    """Foto del calendario de Canvas (leído por Google Calendar) para detectar fechas nuevas o movidas."""
    __tablename__ = "edu_canvas_items"
    uid: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(400))
    start: Mapped[str] = mapped_column(String(40))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EduCanvasChange(Base):
    __tablename__ = "edu_canvas_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # nuevo | movido | retirado
    title: Mapped[str] = mapped_column(String(400))
    old: Mapped[str] = mapped_column(String(40), default="")
    new: Mapped[str] = mapped_column(String(40), default="")
    seen: Mapped[bool] = mapped_column(Boolean, default=False)


class EduCalendarBlock(Base):
    """Bloques del plan que ya están en Google Calendar (evento con la marca jarvis=1)."""
    __tablename__ = "edu_calendar_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    slot: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("day", "slot"),)


class CareerDocument(Base):
    """Un CV o una carta: el archivo vive en archivos/Carrera/ y se identifica por su huella."""
    __tablename__ = "career_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="cv")  # cv | carta | otro
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    path: Mapped[str] = mapped_column(String(500))  # relativa a la carpeta común de archivos
    language: Mapped[str] = mapped_column(String(8), default="es")
    size: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplicantProfile(Base):
    """Datos para rellenar formularios (una sola fila). Incluye la lista de lo que nunca se rellena."""
    __tablename__ = "applicant_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplicationRun(Base):
    """Una solicitud preparada por el agente: en_cola → preparando → listo_para_revisar → aprobada → enviada,
    o fallida / abortada / rechazada. Lo que se envía es exactamente lo aprobado (huella de la acción)."""
    __tablename__ = "application_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("job_applications.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    domains: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), index=True, default="en_cola")
    document_sha: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    screenshots: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(String(1000), default="")
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    vc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
