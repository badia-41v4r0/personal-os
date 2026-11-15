"""Jarvis por voz en el PC: escucha «hey/oye Jarvis», graba la orden y se la pasa a la sesión de Jarvis.

Flujo:
  micro (pw-record, 16 kHz) -> openWakeWord (hey_jarvis) -> bip -> graba hasta el silencio (Silero VAD)
  -> transcribe con Whisper large-v3-turbo en la GPU (cargado siempre; si falla, el Whisper del contenedor)
  -> lo teclea en la sesión tmux de Jarvis: "🎙️ [voz-pc id=…] texto", con un tono suave de «pensando»
  Jarvis responde escribiendo /voz/salida/<id>.md (= data/voz/salida en el host)
  -> Piper lo lee en voz alta frase a frase y se añade a la conversación (la ventana: voz/ventana.py).

Todo es local. Lo que se oye antes de la palabra de activación no se guarda.
Pausa: existe voz/estado/pausa (bin/voz pausa). Mientras está en pausa el micro queda libre.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import ctypes
import fcntl
import glob
import queue

import numpy as np
from openwakeword.model import Model
from openwakeword.vad import VAD
from piper import PiperVoice

ROOT = Path(__file__).resolve().parent.parent
VOZ = ROOT / "voz"
ESTADO = VOZ / "estado"
PAUSA = ESTADO / "pausa"
ACTIVAR = ESTADO / "activar"               # bin/voz hablar: activa sin palabra de activación
CONVERSACION = ESTADO / "conversacion.jsonl"
FASE = ESTADO / "fase"                     # escuchando | grabando | transcribiendo | hablando | pausa
COMPARTIDA = ROOT / "data" / "voz"           # /voz en el contenedor
ENTRADA, SALIDA = COMPARTIDA / "entrada", COMPARTIDA / "salida"
VOZ_PIPER = VOZ / "modelos" / "es_ES-davefx-medium.onnx"
WHISPER_DIR = VOZ / "modelos" / "whisper"
WHISPER = os.environ.get("JARVIS_WHISPER", "large-v3-turbo")

MIC = os.environ.get("JARVIS_MIC", "")  # nombre de la fuente de PipeWire (pactl list short sources); vacío = la predeterminada
UMBRAL = float(os.environ.get("JARVIS_UMBRAL", "0.3"))
CASI = 0.05                                # puntuaciones por encima se registran (para ajustar el umbral)
RATE, CHUNK = 16000, 1280                  # 80 ms, lo que espera openWakeWord
ESPERA_INICIO, SILENCIO_FIN, MAX_ORDEN = 5.0, 0.8, 30.0
PENSANDO_MAX = 90                          # s: tope del tono de «pensando» si Jarvis no responde

hablando = threading.Event()
esperando = threading.Event()              # orden enviada, sin respuesta todavía


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def fase(f: str):
    ESTADO.mkdir(parents=True, exist_ok=True)
    FASE.write_text(f)


def apuntar(quien: str, texto: str):
    with CONVERSACION.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"), "quien": quien, "texto": texto},
                           ensure_ascii=False) + "\n")


def bip(frecuencias=(880, 1320), dur=0.09):
    """Tono corto generado al vuelo (sin archivos)."""
    t = np.linspace(0, dur, int(22050 * dur), endpoint=False)
    onda = np.concatenate([np.sin(2 * np.pi * f * t) * np.hanning(len(t)) for f in frecuencias])
    tocar((onda * 0.25 * 32767).astype(np.int16), 22050)


def reproductor(rate: int) -> subprocess.Popen:
    """pw-play en modo bruto: se le va pasando audio por stdin y suena sin cortes.
    Búfer de 300 ms: mientras suena una frase, Piper genera la siguiente con toda la CPU y sin margen se oían cortes."""
    return subprocess.Popen(["pw-play", "--raw", "--latency", "300ms", "--rate", str(rate), "--channels", "1",
                             "--format", "s16", "-"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


def tocar(pcm: np.ndarray, rate: int):
    p = reproductor(rate)
    p.communicate(pcm.tobytes())


def pensando():
    """Tono suave cada 1,8 s mientras Jarvis piensa (hasta que responde o PENSANDO_MAX)."""
    t = np.linspace(0, 0.14, int(22050 * 0.14), endpoint=False)
    pulso = np.concatenate([np.sin(2 * np.pi * f * t) * np.hanning(len(t)) for f in (523, 659)])
    pulso = (pulso * 0.07 * 32767).astype(np.int16)
    while True:
        esperando.wait()
        inicio = time.time()
        while esperando.is_set() and not hablando.is_set() and time.time() - inicio < PENSANDO_MAX:
            if esperando.wait(0) and not hablando.is_set():
                tocar(pulso, 22050)
            for _ in range(18):  # 1,8 s, cortando enseguida si llega la respuesta
                if not esperando.is_set() or hablando.is_set():
                    break
                time.sleep(0.1)
        esperando.clear()


# ---------- Respuestas de Jarvis ----------

def limpiar_para_voz(texto: str) -> str:
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)       # enlaces markdown
    texto = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", texto)  # wikilinks
    texto = re.sub(r"[*_`#>|]", "", texto)
    texto = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", texto)  # emojis
    return re.sub(r"\s+", " ", texto).strip()


def decir(voz: PiperVoice, texto: str):
    """Frase a frase: Piper genera cada frase en un hilo y suenan seguidas por un único pw-play."""
    cola: queue.Queue = queue.Queue(maxsize=4)

    def generar():
        try:
            for c in voz.synthesize(limpiar_para_voz(texto)):  # un trozo por frase
                cola.put(c.audio_int16_bytes)
        except Exception as e:
            log("Error al generar la voz:", e)
        finally:
            cola.put(None)

    threading.Thread(target=generar, daemon=True).start()
    p = reproductor(voz.config.sample_rate)
    try:
        # 0,3 s de silencio: la salida (HDMI) despierta antes de la primera palabra
        p.stdin.write(bytes(int(voz.config.sample_rate * 0.3) * 2))
        while (trozo := cola.get()) is not None:
            p.stdin.write(trozo)
            p.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        try:
            p.stdin.close()
        except BrokenPipeError:
            pass
        p.wait()


def vigilar_respuestas(voz: PiperVoice):
    SALIDA.mkdir(parents=True, exist_ok=True)
    while True:
        for f in sorted(SALIDA.glob("*.md")):
            texto = f.read_text(encoding="utf-8").strip()
            if not texto:  # aún se está escribiendo
                continue
            f.unlink(missing_ok=True)
            esperando.clear()
            apuntar("jarvis", texto)
            log("Jarvis:", texto[:80])
            hablando.set()
            fase("hablando")
            try:
                decir(voz, texto)
            except Exception as e:
                log("Error al hablar:", e)
            finally:
                hablando.clear()
                fase("pausa" if PAUSA.exists() else "escuchando")
        time.sleep(0.1)


# ---------- Orden de voz ----------

def cargar_whisper():
    """Whisper en la GPU. Las librerías CUDA vienen del venv (nvidia-cublas/cudnn) y se precargan aquí."""
    base = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "nvidia"
    for patron in ("cublas/lib/libcublasLt.so.*", "cublas/lib/libcublas.so.*", "cudnn/lib/libcudnn*.so.*"):
        for f in sorted(glob.glob(str(base / patron))):
            ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
    from faster_whisper import WhisperModel
    m = WhisperModel(WHISPER, device="cuda", compute_type="int8_float16", download_root=str(WHISPER_DIR))
    m.transcribe(np.zeros(RATE, dtype=np.float32), language="es")  # calentar
    return m


def transcribir(pcm: np.ndarray, whisper) -> str:
    if whisper is not None:
        try:
            segs, _ = whisper.transcribe(pcm.astype(np.float32) / 32768, language="es", beam_size=1,
                                         without_timestamps=True, initial_prompt="Hey Jarvis.")
            texto = " ".join(s.text.strip() for s in segs).strip()
            # Frases que Whisper se inventa con ruido o silencio
            return "" if re.search(r"amara\.org|suscr[ií]bete|gracias por ver", texto, re.I) else texto
        except Exception as e:
            log("Whisper en GPU ha fallado; uso el del contenedor:", e)
    ENTRADA.mkdir(parents=True, exist_ok=True)
    nombre = datetime.now().strftime("%Y%m%d-%H%M%S") + ".wav"
    ruta = ENTRADA / nombre
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    try:
        r = subprocess.run(["docker", "compose", "exec", "-T", "jarvis", "/opt/jarvis/bin/transcribir",
                            f"/voz/entrada/{nombre}"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        texto = r.stdout.strip()
    finally:
        ruta.unlink(missing_ok=True)  # el audio no se guarda
    return "" if texto.startswith("(audio sin voz") else texto


def enviar(texto: str):
    ident = datetime.now().strftime("%Y%m%d-%H%M%S")
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"^(?:hey|oye|ey|hola)?[\s,]*jarvis[\s,.:]*", "", texto, flags=re.I) or texto
    apuntar("tu", texto)
    log("Tú:", texto)
    esperando.set()
    if (ROOT / "data/control-center/runtime").is_file() and (ROOT / "data/control-center/runtime").read_text().strip() == "runs":
        subprocess.run([str(ROOT / "bin/jarvis-run"), texto, "--voz", ident], check=False)
        return ident
    # Como bin/jarvis-prompt.sh, pero con 0,3 s antes del Intro (allí es 1 s; lo usan el briefing y el recordatorio)
    # Cerrojo común con bin/jarvis-prompt.sh y el Control Center: el texto y su Intro no se mezclan con otra orden
    tmux = ["docker", "exec", "jarvis", "tmux", "send-keys", "-t", "jarvis"]
    lock = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "jarvis-prompt.lock"
    with open(lock, "w") as fl:
        fcntl.flock(fl, fcntl.LOCK_EX)
        subprocess.run(tmux + ["-l", f"🎙️ [voz-pc id={ident}] {texto}"], check=False)
        time.sleep(0.3)
        subprocess.run(tmux + ["C-m"], check=False)
    return ident


# ---------- Bucle principal ----------

def micro():
    return subprocess.Popen(["pw-record", *(["--target", MIC] if MIC else []), "--rate", str(RATE), "--channels", "1",
                             "--format", "s16", "--latency", "80ms", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def leer(proc) -> np.ndarray | None:
    datos = proc.stdout.read(CHUNK * 2)
    if not datos or len(datos) < CHUNK * 2:
        return None
    return np.frombuffer(datos, dtype=np.int16)


def grabar_orden(proc, vad: VAD) -> np.ndarray:
    """Graba desde ya hasta SILENCIO_FIN segundos sin voz (o MAX_ORDEN)."""
    trozos, empezado, silencio, t = [], False, 0.0, 0.0
    dt = CHUNK / RATE
    while t < MAX_ORDEN:
        x = leer(proc)
        if x is None:
            break
        trozos.append(x)
        t += dt
        voz = vad.predict(x, frame_size=640) > 0.5
        if voz:
            empezado, silencio = True, 0.0
        else:
            silencio += dt
        if (empezado and silencio >= SILENCIO_FIN) or (not empezado and t >= ESPERA_INICIO):
            break
    return np.concatenate(trozos) if empezado else np.array([], dtype=np.int16)


def main():
    log("Cargando modelos…")
    modelo = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    vad = VAD()
    voz = PiperVoice.load(str(VOZ_PIPER))
    try:
        whisper = cargar_whisper()
        log(f"Whisper {WHISPER} en la GPU")
    except Exception as e:
        whisper = None
        log("Sin GPU; transcribe el Whisper del contenedor:", e)
    threading.Thread(target=vigilar_respuestas, args=(voz,), daemon=True).start()
    threading.Thread(target=pensando, daemon=True).start()
    CONVERSACION.parent.mkdir(parents=True, exist_ok=True)
    CONVERSACION.touch()
    proc, ultima, pico = None, 0.0, 0.0
    log("Listo. Micro:", MIC)
    while True:
        if PAUSA.exists():
            if proc:
                proc.terminate(), proc.wait()
                proc = None
                log("En pausa")
            fase("pausa")
            time.sleep(0.5)
            continue
        if proc is None:
            proc = micro()
            modelo.reset()
            fase("escuchando")
            log("Escuchando")
        x = leer(proc)
        if x is None:
            log("El micro se ha cerrado; reintento en 3 s")
            proc = None
            time.sleep(3)
            continue
        if hablando.is_set():  # no reaccionar a su propia voz
            continue
        puntos = modelo.predict(x)["hey_jarvis"]
        manual = ACTIVAR.exists()
        if manual:
            ACTIVAR.unlink(missing_ok=True)
        elif puntos >= CASI:
            pico = max(pico, puntos)
        if pico and puntos < CASI:  # fin de un pico: se apunta para poder ajustar el umbral
            log(f"Pico {pico:.2f} (umbral {UMBRAL})")
            pico = 0.0
        if not manual and (puntos < UMBRAL or time.time() - ultima < 2):
            continue
        log("Activado a mano" if manual else f"Activado ({puntos:.2f})")
        pico = 0.0
        fase("grabando")
        bip()
        vad.reset_states()
        pcm = grabar_orden(proc, vad)
        modelo.reset()
        ultima = time.time()
        if not len(pcm):
            bip((660, 440))
            fase("escuchando")
            continue
        # Se cierra el micro mientras transcribe: así no se acumula audio viejo
        proc.terminate(), proc.wait()
        proc = None
        fase("transcribiendo")
        t0 = time.time()
        texto = transcribir(pcm, whisper)
        log(f"Transcrito en {time.time() - t0:.1f} s")
        if not texto:
            apuntar("sistema", "No te he entendido.")
            bip((660, 440))
            continue
        enviar(texto)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
