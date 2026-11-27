package br.local.painelpc;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.AssetFileDescriptor;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.util.Log;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

/**
 * "Jarvis do tablet" com o PC desligado.
 *
 * Sem o PC conectado por mais de 20 s, escuta o microfone do tablet. Com 5 palmas, pergunta
 * (voz do Jarvis gravada no APK) se deve ligar o computador; se a pessoa falar qualquer coisa
 * nos 6 s seguintes, manda o "pacote magico" do Wake-on-LAN pelo Wi-Fi. Silencio = nao liga.
 * O endereco do PC (MAC e broadcast) chega do agente na mensagem "hello" e fica salvo.
 * Com o PC conectado, o microfone do tablet fica fechado.
 */
final class Vigia {
    private static final String TAG = "PainelVigia";
    private static final int SR = 16000;
    private static final long OFFLINE_MS = 20000;

    interface Events { void onGuard(String json); }

    private final Context ctx;
    private final SharedPreferences prefs;
    private final Events events;
    private volatile boolean linkUp = true;
    private volatile long downSince;
    private volatile boolean busy;
    private Thread thread;

    Vigia(Context c, SharedPreferences p, Events e) { ctx = c.getApplicationContext(); prefs = p; events = e; }

    void setLink(boolean up) {
        linkUp = up;
        if (!up) downSince = System.currentTimeMillis();
    }

    boolean known() { return prefs.getString("wol_mac", "").length() > 0; }

    synchronized void start() {
        if (thread != null) return;
        thread = new Thread(new Runnable() { public void run() { loop(); } }, "vigia");
        thread.setDaemon(true);
        thread.start();
    }

    private boolean shouldListen() {
        if (prefs.getBoolean("guard_test", false)) return true;  // teste/calibracao: escuta mesmo com o PC ligado
        return !linkUp && known() && prefs.getBoolean("claps", true)
                && System.currentTimeMillis() - downSince > OFFLINE_MS;
    }

    private void loop() {
        boolean announced = false;
        while (true) {
            try {
                if (!shouldListen()) {
                    if (announced && linkUp) { emit("idle", null); announced = false; }
                    Thread.sleep(1000);
                    continue;
                }
                emit("listen", null);
                announced = true;
                if (listenForClaps()) ask();
            } catch (Throwable e) {
                Log.w(TAG, "vigia: " + e);
                try { Thread.sleep(5000); } catch (InterruptedException ignored) {}
            }
        }
    }

    private AudioRecord openMic() {
        int min = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord r = new AudioRecord(MediaRecorder.AudioSource.MIC, SR, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, Math.max(min, SR));
        if (r.getState() != AudioRecord.STATE_INITIALIZED) { r.release(); throw new IllegalStateException("microfone indisponivel"); }
        r.startRecording();
        return r;
    }

    /** Escuta ate 5 palmas (true) ou ate o PC voltar (false). */
    private boolean listenForClaps() {
        Palmas p = new Palmas(prefs.getInt("claps_n", 3), prefs.getFloat("clap_rise", 25), prefs.getFloat("clap_level", -36),
                prefs.getFloat("clap_decay", 10), prefs.getFloat("clap_flat", 0.01f));
        AudioRecord mic = openMic();
        short[] buf = new short[1280];
        long logT = System.currentTimeMillis();
        String seen = null;
        try {
            while (shouldListen()) {
                int n = mic.read(buf, 0, buf.length);
                if (n <= 0) continue;
                int r = p.feed(buf, n);
                if (p.lastInfo != null && p.lastInfo != seen) { seen = p.lastInfo; Log.i(TAG, seen); }
                if (System.currentTimeMillis() - logT > 3000) {
                    Log.i(TAG, String.format(java.util.Locale.US, "nivel max %.1f dB", p.maxDb));
                    p.maxDb = -120; logT = System.currentTimeMillis();
                }
                if (r == 2) return true;
                if (r == 1) emit("clap", "{\"n\":" + p.count() + ",\"need\":" + p.need() + "}");
            }
            return false;
        } finally {
            mic.stop();
            mic.release();
        }
    }

    private void ask() throws InterruptedException {
        busy = true;
        try {
            if (!wifiUp()) { emit("nowifi", null); play("voz/sem_rede.wav"); return; }
            emit("ask", null);
            play("voz/pergunta.wav");
            if (heardVoice(6000)) {
                wake();
                emit("waking", null);
                play("voz/ligando.wav");
                Thread.sleep(8000);
            } else {
                emit("cancel", null);
                Thread.sleep(2500);
            }
        } finally {
            busy = false;
        }
    }

    /** Qualquer fala (>= 300 ms de som acima do ruido) dentro do tempo = "sim". */
    private boolean heardVoice(long ms) {
        AudioRecord mic = openMic();
        short[] buf = new short[320];  // 20 ms
        try {
            long end = System.currentTimeMillis() + ms;
            double floor = 0; int nFloor = 0, voiced = 0;
            while (System.currentTimeMillis() < end) {
                int n = mic.read(buf, 0, buf.length);
                if (n <= 0) continue;
                double sum = 0;
                for (int i = 0; i < n; i++) { double x = buf[i] / 32768.0; sum += x * x; }
                double db = 20 * Math.log10(Math.sqrt(sum / n) + 1e-6);
                if (nFloor < 15) { floor = (floor * nFloor + db) / (nFloor + 1); nFloor++; continue; }  // 300 ms de ruido
                if (db > floor + 12 && db > -50) { if (++voiced >= 15) return true; }
                else if (voiced > 0) voiced--;
            }
            return false;
        } finally {
            mic.stop();
            mic.release();
        }
    }

    boolean wifiUp() {
        try {
            ConnectivityManager cm = (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
            NetworkInfo w = cm.getNetworkInfo(ConnectivityManager.TYPE_WIFI);
            return w != null && w.isConnected();
        } catch (Exception e) { return false; }
    }

    /** Pacote magico: 6 x 0xFF + 16 x MAC, por broadcast (rede do PC e geral), portas 9 e 7, 3 vezes. */
    boolean wake() {
        String mac = prefs.getString("wol_mac", "");
        String[] parts = mac.split("[:-]");
        if (parts.length != 6) return false;
        byte[] pkt = new byte[102];
        for (int i = 0; i < 6; i++) pkt[i] = (byte) 0xFF;
        for (int r = 0; r < 16; r++)
            for (int i = 0; i < 6; i++) pkt[6 + r * 6 + i] = (byte) Integer.parseInt(parts[i], 16);
        boolean ok = false;
        DatagramSocket s = null;
        try {
            s = new DatagramSocket();
            s.setBroadcast(true);
            String[] dests = {prefs.getString("wol_bcast", "255.255.255.255"), "255.255.255.255"};
            for (int rep = 0; rep < 3; rep++)
                for (String d : dests)
                    for (int port : new int[]{9, 7}) {
                        try { s.send(new DatagramPacket(pkt, pkt.length, InetAddress.getByName(d), port)); ok = true; }
                        catch (Exception e) { Log.w(TAG, "wol " + d + ": " + e); }
                    }
        } catch (Exception e) {
            Log.w(TAG, "wol: " + e);
        } finally {
            if (s != null) s.close();
        }
        Log.i(TAG, "wake-on-lan enviado: " + ok);
        return ok;
    }

    /** Toca uma fala do APK no volume de midia (sobe para 80% se estiver mais baixo) e espera terminar. */
    private void play(String asset) throws InterruptedException {
        AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
        int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        if (am.getStreamVolume(AudioManager.STREAM_MUSIC) < max * 8 / 10)
            am.setStreamVolume(AudioManager.STREAM_MUSIC, max * 8 / 10, 0);
        Log.i(TAG, "fala " + asset + ": volume " + am.getStreamVolume(AudioManager.STREAM_MUSIC) + "/" + max
                + " modo=" + am.getMode() + " fone=" + am.isWiredHeadsetOn() + " viva-voz=" + am.isSpeakerphoneOn()
                + " mudo=" + am.isMicrophoneMute());
        final Object done = new Object();
        MediaPlayer mp = new MediaPlayer();
        try {
            AssetFileDescriptor fd = ctx.getAssets().openFd(asset);
            mp.setDataSource(fd.getFileDescriptor(), fd.getStartOffset(), fd.getLength());
            fd.close();
            mp.setAudioStreamType(AudioManager.STREAM_MUSIC);
            mp.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                public void onCompletion(MediaPlayer m) { synchronized (done) { done.notifyAll(); } }
            });
            mp.prepare();
            int dur = mp.getDuration();
            mp.start();
            synchronized (done) { done.wait(Math.max(1000, dur + 1500)); }
            Thread.sleep(250);  // o fim da fala nao entra no microfone
        } catch (InterruptedException e) {
            throw e;
        } catch (Exception e) {
            Log.w(TAG, "fala " + asset + ": " + e);
        } finally {
            mp.release();
        }
    }

    /** Teste do alto-falante (adb ... --ei beep 1|2|3), volume maximo:
     *  1 = tom de 1 kHz pelo AudioTrack (musica), 2 = o mesmo pelo canal de alarme, 3 = bipes do sistema (ToneGenerator). */
    void beep(final int mode) {
        new Thread(new Runnable() {
            public void run() {
                AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
                int stream = mode == 2 ? AudioManager.STREAM_ALARM : mode == 3 ? AudioManager.STREAM_SYSTEM : AudioManager.STREAM_MUSIC;
                am.setStreamVolume(stream, am.getStreamMaxVolume(stream), 0);
                Log.i(TAG, "teste de som " + mode + " volume " + am.getStreamVolume(stream) + "/" + am.getStreamMaxVolume(stream));
                if (mode == 3) {
                    android.media.ToneGenerator tg = new android.media.ToneGenerator(stream, 100);
                    for (int i = 0; i < 3; i++) {
                        tg.startTone(android.media.ToneGenerator.TONE_PROP_BEEP2, 400);
                        try { Thread.sleep(700); } catch (InterruptedException ignored) {}
                    }
                    tg.release();
                    return;
                }
                int sr = 44100, n = sr * 2;
                short[] pcm = new short[n * 2];
                for (int i = 0; i < n; i++) {
                    short v = (short) (Math.sin(2 * Math.PI * 1000 * i / sr) * 30000 * ((i / (sr / 4)) % 2 == 0 ? 1 : 0));
                    pcm[2 * i] = v; pcm[2 * i + 1] = v;
                }
                android.media.AudioTrack at = new android.media.AudioTrack(stream, sr, AudioFormat.CHANNEL_OUT_STEREO,
                        AudioFormat.ENCODING_PCM_16BIT, pcm.length * 2, android.media.AudioTrack.MODE_STATIC);
                at.write(pcm, 0, pcm.length);
                at.play();
                try { Thread.sleep(2300); } catch (InterruptedException ignored) {}
                at.release();
            }
        }, "vigia-teste").start();
    }

    /** Diagnostico (adb ... --es say pergunta): toca uma fala do APK. */
    void say(final String name) {
        new Thread(new Runnable() {
            public void run() { try { play("voz/" + name + ".wav"); } catch (InterruptedException ignored) {} }
        }, "vigia-fala").start();
    }

    /** Botao "Ligar PC" da tela: liga direto, sem perguntar. */
    void wakeFromButton() {
        new Thread(new Runnable() {
            public void run() {
                if (busy) return;
                busy = true;
                try {
                    if (!wifiUp()) { emit("nowifi", null); play("voz/sem_rede.wav"); return; }
                    wake();
                    emit("waking", null);
                    play("voz/ligando.wav");
                } catch (InterruptedException ignored) {
                } finally { busy = false; }
            }
        }, "vigia-botao").start();
    }

    private void emit(String st, String extra) {
        String j = "{\"t\":\"guard\",\"st\":\"" + st + "\",\"wifi\":" + wifiUp() + ",\"known\":" + known()
                + (extra != null ? ",\"x\":" + extra : "") + "}";
        events.onGuard(j);
    }
}
