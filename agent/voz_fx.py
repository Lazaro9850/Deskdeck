"""
Efeito de "voz de assistente de IA" aplicado a fala do Kokoro (so numpy, ~1 ms por frase).

* corta os graves embolados (abaixo de ~110 Hz), deixando a voz mais limpa;
* timbre eletronico: uma copia atrasada 11 ms (efeito "dobrado") e uma modulacao bem leve;
* uma sala pequena (4 reflexoes curtas), para a voz nao soar "seca".

`amount` controla so a parte eletronica (0 = voz limpa com sala; 1 = bem robotica). Padrao 0,5.
"""
import numpy as np


def apply(audio, sr, amount=0.5):
    amount = max(0.0, min(1.0, float(amount)))
    a = np.concatenate([np.asarray(audio, np.float64), np.zeros(int(sr * 0.07))])  # espaco para a cauda da sala
    n = max(1, int(sr / 110))
    a = a - np.convolve(a, np.ones(n) / n, mode="same")
    d = int(sr * 0.011)
    dbl = np.zeros_like(a)
    dbl[d:] = a[:-d]
    t = np.arange(len(a)) / sr
    depth = 0.15 * amount
    ring = a * (1 - depth + depth * np.sin(2 * np.pi * 55 * t))
    y = 0.75 * ring + 0.32 * amount * dbl
    rev = np.zeros_like(y)
    for ms, g in ((29, .22), (37, .18), (43, .14), (53, .1)):
        k = int(sr * ms / 1000)
        rev[k:] += g * y[:-k]
    y = y + 0.6 * rev
    peak = np.abs(y).max()
    return (y / peak * 0.9 if peak > 0 else y).astype(np.float32)
