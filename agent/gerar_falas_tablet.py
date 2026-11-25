#!/usr/bin/env python3
"""
Gera as falas que o TABLET toca sozinho com o PC desligado (android/assets/voz/*.wav), com a mesma voz e
o mesmo efeito do Jarvis. Rode de novo se trocar a voz e recompile o APK (android/build_apk.ps1).
Uso: python gerar_falas_tablet.py   (precisa das libs e modelos do Jarvis instalados)
"""
import os
import sys
import wave

import numpy as np

ROOT = os.path.join(os.path.expanduser("~"), "PainelPC")
sys.path[:0] = [os.path.join(ROOT, "libs-jarvis"), os.path.dirname(os.path.abspath(__file__))]
import voz_fx  # noqa: E402
from jarvis_service import load_cfg  # noqa: E402

FALAS = {
    "pergunta": "Você quer ligar o computador? Não responda nada caso não queira.",
    "ligando": "Ligando o computador.",
    "sem_rede": "Não consegui ligar o computador. O tablet está sem Wi-Fi.",
}


def main():
    from kokoro_onnx import Kokoro
    cfg = load_cfg()
    k = os.path.join(ROOT, "models", "kokoro")
    tts = Kokoro(os.path.join(k, "kokoro-v1.0.onnx"), os.path.join(k, "voices-v1.0.bin"))
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "android", "assets", "voz")
    os.makedirs(out, exist_ok=True)
    for name, text in FALAS.items():
        a, sr = tts.create(text, voice=cfg["voice"], speed=float(cfg["speed"]), lang="pt-br")
        fx = float(cfg.get("voice_fx") or 0)
        if fx > 0:
            a = voz_fx.apply(a, sr, fx)
        a = np.interp(np.arange(0, len(a), sr / 16000.0), np.arange(len(a)), a)  # 16 kHz: APK menor
        a16 = (np.clip(a, -1, 1) * 32767).astype(np.int16)
        with wave.open(os.path.join(out, name + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(a16.tobytes())
        print("ok", name, "%.1f s" % (len(a16) / 16000))


if __name__ == "__main__":
    main()
