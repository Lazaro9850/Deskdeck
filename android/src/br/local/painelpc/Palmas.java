package br.local.painelpc;

/**
 * Detector de palmas (mesmo algoritmo do agent/palmas.py do PC), para o microfone do tablet.
 *
 * Uma palma e um estalo: o volume sobe >= 25 dB de uma vez, cai >= 10 dB em 40 ms e o som e
 * "chiado" (flatness >= 0,01). Assobio e fala sao tonais e se sustentam, entao nao contam.
 * Sequencia: N palmas seguidas, cada uma ate 1 s depois da anterior, ritmo parecido (<= 50% da media).
 * Pausa maior que 1 s recomeca a contagem (o contador nunca passa de N).
 * Audio: 16 kHz, mono, PCM 16 bits.
 */
final class Palmas {
    private static final int SR = 16000, HOP = 80, LOOKBACK = 20, REFRACT = 24, CONFIRM = 9, FFT = 320;

    private final int need;
    private final double rise, level, decay, flatMin;
    private final double[] hist = new double[LOOKBACK + 1];
    private final short[] ring = new short[FFT];      // ultimos 20 ms de audio
    private final short[] frame = new short[HOP];
    private int fill, ringPos;
    private long t, last = -1000000;
    private long pT; private double pPeak, pMin, pFlat; private boolean pending;
    private final double[] times = new double[16];
    private int nTimes;
    volatile String lastInfo;   // diagnostico: ultimo estalo avaliado
    double maxDb = -120;        // diagnostico: maior nivel desde a ultima leitura

    // tabelas da DFT (so os bins de 150 a 6000 Hz) e da janela de Hann
    private static final int K0 = 3, K1 = 120;
    private static final double[] HANN = new double[FFT];
    private static final double[][] COS = new double[K1 + 1][], SIN = new double[K1 + 1][];
    static {
        for (int i = 0; i < FFT; i++) HANN[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (FFT - 1));
        for (int k = K0; k <= K1; k++) {
            COS[k] = new double[FFT]; SIN[k] = new double[FFT];
            for (int i = 0; i < FFT; i++) {
                COS[k][i] = Math.cos(2 * Math.PI * k * i / FFT);
                SIN[k][i] = Math.sin(2 * Math.PI * k * i / FFT);
            }
        }
    }

    Palmas(int claps, double riseDb, double levelDb, double decayDb, double flat) {
        need = Math.max(2, Math.min(claps, 15)); rise = riseDb; level = levelDb; decay = decayDb; flatMin = flat;
        java.util.Arrays.fill(hist, -120);
    }

    int count() { return nTimes; }
    int need() { return need; }

    /** Processa amostras; retorna 1 se uma palma foi confirmada, 2 se a sequencia completou, 0 senao. */
    int feed(short[] buf, int n) {
        int result = 0;
        for (int i = 0; i < n; i++) {
            short s = buf[i];
            frame[fill++] = s;
            ring[ringPos] = s; ringPos = (ringPos + 1) % FFT;
            if (fill == HOP) {
                fill = 0;
                int r = step(frame);
                if (r > result) result = r;
            }
        }
        return result;
    }

    private int step(short[] f) {
        double sum = 0;
        for (short s : f) { double x = s / 32768.0; sum += x * x; }
        double v = 20 * Math.log10(Math.sqrt(sum / HOP) + 1e-6);
        double base = 999;
        for (int i = 0; i < LOOKBACK; i++) base = Math.min(base, hist[i]);
        double prev = hist[LOOKBACK];
        System.arraycopy(hist, 1, hist, 0, LOOKBACK);
        hist[LOOKBACK] = v;
        if (v > maxDb) maxDb = v;
        t++;
        int result = 0;
        if (pending) {
            long age = t - pT;
            if (age <= 3) {
                pPeak = Math.max(pPeak, v);
                if (age == 3) pFlat = flatness();
            }
            if (age >= CONFIRM - 1) pMin = Math.min(pMin, v);
            if (age >= CONFIRM) {
                pending = false;
                boolean ok = pPeak - pMin >= decay && pFlat >= flatMin;
                lastInfo = String.format(java.util.Locale.US, "estalo pico=%.1f queda=%.1f chiado=%.3f %s",
                        pPeak, pPeak - pMin, pFlat, ok ? "PALMA" : "rejeitado");
                if (ok) result = add(pT * HOP / (double) SR) ? 2 : 1;
            }
        }
        if (t - last >= REFRACT && v > level && v - base > rise && v >= prev + 6) {
            last = t;
            pending = true; pT = t; pPeak = v; pMin = 0; pFlat = 0;
        }
        return result;
    }

    /** "Chiado": media geometrica / media aritmetica do espectro (1 = ruido, ~0 = tom). */
    private double flatness() {
        double logSum = 0, sum = 0;
        int n = 0;
        for (int k = K0; k <= K1; k++) {
            double re = 0, im = 0;
            double[] c = COS[k], sn = SIN[k];
            for (int i = 0; i < FFT; i++) {
                double x = ring[(ringPos + i) % FFT] / 32768.0 * HANN[i];
                re += x * c[i]; im -= x * sn[i];
            }
            double p = re * re + im * im + 1e-12;
            logSum += Math.log(p); sum += p; n++;
        }
        return Math.exp(logSum / n) / (sum / n);
    }

    private boolean add(double now) {
        if (nTimes > 0 && now - times[nTimes - 1] > 1.0) nTimes = 0;      // pausa longa: nova sequencia
        if (nTimes == need) { System.arraycopy(times, 1, times, 0, need - 1); nTimes = need - 1; }
        times[nTimes++] = now;
        if (nTimes == need) {
            double mn = 99, mx = 0, sum = 0;
            for (int i = 1; i < need; i++) {
                double iv = times[i] - times[i - 1];
                mn = Math.min(mn, iv); mx = Math.max(mx, iv); sum += iv;
            }
            double mean = sum / (need - 1);
            if (mn >= 0.12 && (mx - mn) <= 0.5 * mean) { nTimes = 0; return true; }
        }
        return false;
    }
}
