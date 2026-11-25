#!/usr/bin/env python3
"""
Baixa os modelos do Jarvis de fontes oficiais, conferindo o SHA-256 de cada arquivo grande.
Uso: python jarvis_models.py [pasta_dos_modelos]   (padrao: <raiz>\\models)

* Whisper small (fala -> texto): Systran/faster-whisper-small, Hugging Face
* Kokoro v1.0 (fp32) + vozes (texto -> fala): thewh1teagle/kokoro-onnx, release model-files-v1.1 (GitHub)
"""
import hashlib
import os
import sys
import urllib.request

HF = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/"
GH = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"

# (pasta, arquivo, url, sha256 ou None para arquivos pequenos de configuracao)
FILES = [
    ("whisper-small", "model.bin", HF + "model.bin", "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
    ("whisper-small", "config.json", HF + "config.json", None),
    ("whisper-small", "tokenizer.json", HF + "tokenizer.json", None),
    ("whisper-small", "vocabulary.txt", HF + "vocabulary.txt", None),
    # fp32: no Ryzen 5 5600G gera fala a ~4x o tempo real; a versao int8 ficou 10x mais lenta (0,4x)
    ("kokoro", "kokoro-v1.0.onnx", GH + "kokoro-v1.0.onnx", "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"),
    ("kokoro", "voices-v1.0.bin", GH + "voices-v1.0.bin", "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
    # wake word "hey jarvis" (openWakeWord v0.5.1). O GitHub nao publica hash para esse release antigo:
    # os valores abaixo foram fixados no primeiro download e barram qualquer arquivo diferente depois.
    ("wakeword", "melspectrogram.onnx", OWW + "melspectrogram.onnx", "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"),
    ("wakeword", "embedding_model.onnx", OWW + "embedding_model.onnx", "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"),
    ("wakeword", "hey_jarvis_v0.1.onnx", OWW + "hey_jarvis_v0.1.onnx", "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, expected):
    if os.path.isfile(dest) and (expected is None or sha256(dest) == expected):
        print("ok (ja existe):", os.path.basename(dest))
        return
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "deskdeck-jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done % (50 << 20) < (1 << 20):
                print("  %s: %d%%" % (os.path.basename(dest), done * 100 // total))
    if expected is not None:
        got = sha256(tmp)
        if got != expected:
            os.remove(tmp)
            raise SystemExit("HASH NAO CONFERE em %s (esperado %s, veio %s)" % (dest, expected, got))
    os.replace(tmp, dest)
    print("ok (baixado%s):" % (" e conferido" if expected else ""), os.path.basename(dest))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(here), "models")
    for folder, name, url, expected in FILES:
        d = os.path.join(root, folder)
        os.makedirs(d, exist_ok=True)
        fetch(url, os.path.join(d, name), expected)
    print("modelos prontos em", root)


if __name__ == "__main__":
    main()
