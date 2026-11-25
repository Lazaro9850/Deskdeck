"""
Detector de palmas para abrir o Jarvis (processamento de sinal, sem IA, ~0% de CPU).

Uma palma no microfone e um estalo: o volume sobe dezenas de dB em poucos milissegundos.
Fala, teclado e mouse sobem bem menos ou ficam mais baixos. Valores medidos no headset do
autor (16 kHz): palmas com subida de 28-58 dB e pico de -34 a -9 dBFS; ruido normal com
subida de no maximo ~38 dB, mas sempre mais baixo e sem ritmo regular.

Regra da sequencia: N palmas (padrao 5) em ate 4 s, intervalos de 0,12 a 0,8 s e ritmo
parecido (diferenca entre o maior e o menor intervalo <= 35% da media).
Na gravacao de teste: 8 de 8 sequencias detectadas e 0 disparos falsos.
"""
import numpy as np

HOP = 80          # 5 ms a 16 kHz
LOOKBACK = 20     # compara com o nivel mais baixo dos 100 ms anteriores
REFRACT = 24      # 120 ms sem novo ataque (o eco da mesma palma nao conta)


class ClapDetector:
    def __init__(self, claps=5, rise_db=25.0, level_db=-36.0):
        self.need = max(2, int(claps))
        self.rise, self.level = float(rise_db), float(level_db)
        self.hist = np.full(LOOKBACK + 1, -120.0)  # niveis (dB) dos ultimos quadros
        self.tail = np.zeros(0, np.float32)
        self.t = 0            # quadros processados
        self.last = -10 ** 9  # quadro do ultimo ataque
        self.times = []       # instantes (s) das palmas recentes

    def reset(self):
        self.__init__(self.need, self.rise, self.level)

    def feed(self, block):
        """block: int16 (ou float -1..1) mono a 16 kHz. Retorna (palmas_agora, disparou)."""
        x = np.asarray(block)
        x = x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32)
        x = np.concatenate([self.tail, x])
        n = len(x) // HOP
        self.tail = x[n * HOP:]
        if n == 0:
            return 0, False
        db = 20 * np.log10(np.sqrt((x[:n * HOP].reshape(n, HOP) ** 2).mean(1)) + 1e-6)
        new, fired = 0, False
        for v in db:
            h = self.hist
            base = h[:-1].min()  # quadros de 100 ms atras ate o anterior ao ultimo
            prev = h[-1]
            self.hist = np.append(h[1:], v)
            self.t += 1
            if self.t - self.last < REFRACT:
                continue
            if v > self.level and v - base > self.rise and v >= prev + 6:
                self.last = self.t
                now = self.t * HOP / 16000.0
                self.times = [s for s in self.times if now - s <= 4.0] + [now]
                new += 1
                if self._sequence():
                    self.times = []
                    fired = True
        return new, fired

    def count(self):
        return len(self.times)

    def _sequence(self):
        if len(self.times) < self.need:
            return False
        iv = np.diff(self.times[-self.need:])
        return iv.min() >= 0.12 and iv.max() <= 0.8 and (iv.max() - iv.min()) <= 0.35 * iv.mean()
