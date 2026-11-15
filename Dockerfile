# Imagen del Personal OS: CLI de IA (Claude Code, Codex, OpenCode) + Python + Whisper local
FROM oven/bun:1-debian AS bun

FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git tmux python3 jq tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

# Claude Code, Codex y OpenCode (motores de IA del panel) fijados en la imagen; se actualizan reconstruyendo
RUN npm install -g @anthropic-ai/claude-code @openai/codex opencode-ai && npm cache clean --force

# Whisper local (faster-whisper, modelo small) para transcribir notas de voz sin enviarlas fuera.
# El modelo se descarga al construir la imagen: en marcha no necesita red ni escribir en disco.
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/whisper \
 && /opt/whisper/bin/pip install --no-cache-dir faster-whisper==1.* \
 && HF_HOME=/opt/whisper/models /opt/whisper/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" \
 && chmod -R a+rX /opt/whisper
ENV HF_HOME=/opt/whisper/models HF_HUB_OFFLINE=1

COPY bin/ /opt/jarvis/bin/
RUN chmod +x /opt/jarvis/bin/*

# Usuario sin privilegios (uid 1000 = tu usuario en el host, así los archivos de la vault son tuyos)
USER node
WORKDIR /workspace

ENTRYPOINT ["/opt/jarvis/bin/entrypoint.sh"]
