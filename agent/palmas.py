"""
Detector de palmas para abrir o Jarvis (processamento de sinal, sem IA, ~0,1% de CPU).

Uma palma e um ESTALO: o volume sobe dezenas de dB em poucos milissegundos, cai quase tao rapido
e o som e um "chiado" (energia espalhada, sem tom). Medido no headset do autor (16 kHz):

                          palmas         assobio / fala rapida ("oi oi oi")
  subida do volume        28-58 dB       ate ~35 dB
  queda em 40 ms          13-24 dB       mediana 6 dB (o som se sustenta)
  "chiado" (flatness)     > 0,01         ~0,000 (tom puro / voz com tom)

Cada ataque so conta como palma depois de 40 ms, quando da para conferir a queda e o chiado.
Regra da sequencia: N palmas (padrao 5) em ate 4 s, intervalos de 0,12 a 0,8 s e ritmo
parecido (diferenca entre o maior e o menor intervalo <= 35% da media).
"""
import numpy as np

SR = 16000
HOP = 80          # 5 ms
LOOKBACK = 20     # compara com o nivel mais baixo dos 100 ms anteriores
REFRACT = 24      # 120 ms sem novo ataque (o eco da mesma palma nao conta)
CONFIRM = 9       # 45 ms depois do ataque: confere queda e chiado
FFT = 320         # 20 ms analisados no ataque


def _flatness(seg):
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2 + 1e-12
    f = np.fft.rfftfreq(len(seg), 1.0 / SR)
    s = sp[(f >= 150) & (f <= 6000)]
    return float(np.exp(np.log(s).mean()) / s.mean())  # 1 = chiado puro, ~0 = tom


class ClapDetector:
    def __init__(self, claps=5, rise_db=25.0, level_db=-36.0, decay_db=10.0, flat_min=0.01):
        self.need = max(2, int(claps))
        self.rise, self.level = float(rise_db), float(level_db)
        self.decay, self.flat_min = float(decay_db), float(flat_min)
        self.hist = np.full(LOOKBACK + 1, -120.0)  # niveis (dB) dos ultimos quadros
        self.tail = np.zeros(0, np.float32)
        self.ring = np.zeros(HOP * 40, np.float32)  # ultimos 200 ms de audio (para o chiado)
        self.t = 0            # quadros processados
        self.last = -10 ** 9  # quadro do ultimo ataque
        self.pending = None   # ataque esperando confirmacao: [quadro, pico_db, nivel_apos, flatness]
        self.times = []       # instantes (s) das palmas confirmadas recentes

    def reset(self):
        self.__init__(self.need, self.rise, self.level, self.decay, self.flat_min)

    def feed(self, block):
        """block: int16 (ou float -1..1) mono a 16 kHz. Retorna (palmas_novas, disparou)."""
        x = np.asarray(block)
        x = x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32)
        x = np.concatenate([self.tail, x])
        n = len(x) // HOP
        self.tail = x[n * HOP:]
        if n == 0:
            return 0, False
        frames = x[:n * HOP].reshape(n, HOP)
        db = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-6)
        new, fired = 0, False
        for k in range(n):
            v = db[k]
            self.ring = np.concatenate([self.ring[HOP:], frames[k]])
            h = self.hist
            base, prev = h[:-1].min(), h[-1]
            self.hist = np.append(h[1:], v)
            self.t += 1
            p = self.pending
            if p is not None:
                age = self.t - p[0]
                if age <= 3:
                    p[1] = max(p[1], v)                      # pico nos primeiros 15 ms
                    if age == 3:
                        p[3] = _flatness(self.ring[-FFT:])   # 20 ms a partir do ataque
                if age >= CONFIRM - 1:
                    p[2] = min(p[2], v)
                if age >= CONFIRM:
                    self.pending = None
                    if p[1] - p[2] >= self.decay and p[3] >= self.flat_min:
                        new += 1
                        if self._add(p[0] * HOP / SR):
                            fired = True
            if self.t - self.last < REFRACT:
                continue
            if v > self.level and v - base > self.rise and v >= prev + 6:
                self.last = self.t
                self.pending = [self.t, v, 0.0, 0.0]
        return new, fired

    def _add(self, now):
        self.times = [s for s in self.times if now - s <= 4.0] + [now]
        if len(self.times) >= self.need:
            iv = np.diff(self.times[-self.need:])
            if iv.min() >= 0.12 and iv.max() <= 0.8 and (iv.max() - iv.min()) <= 0.35 * iv.mean():
                self.times = []
                return True
        return False

    def count(self):
        return len(self.times)
