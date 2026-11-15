"""Transcribe el audio de un vídeo con el Whisper del contenedor, detectando el idioma y con marcas de tiempo.
Lo usa bin/video.sh desde el host (no está en la imagen):
  docker compose exec -T jarvis /opt/whisper/bin/python - /voz/video/<archivo>.wav < bin/transcribir-video.py
"""
import sys
from faster_whisper import WhisperModel

modelo = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=2)
segmentos, info = modelo.transcribe(sys.argv[1], vad_filter=True, beam_size=5)
lineas = [f"[{int(s.start) // 60}:{int(s.start) % 60:02d}] {s.text.strip()}" for s in segmentos if s.text.strip()]
print(f"Idioma: {info.language} ({info.language_probability:.0%})")
print("\n".join(lineas) or "(sin voz reconocible: solo música o silencio)")
