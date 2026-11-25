package br.local.painelpc;

import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * Canal com o agente do PC.
 *
 * O Android 4.1 nao tem "adb reverse", entao o tablet e quem escuta:
 * um ServerSocket em 127.0.0.1:7001 e o PC chega ate ele com
 * "adb forward tcp:7001 tcp:7001". Mensagens sao JSON, uma por linha.
 *
 * Modo Wi-Fi (opcional): escuta em todas as interfaces e exige token.
 */
public final class Link {
    public static final int PORT = 7001;
    private static final String TAG = "PainelLink";
    private static Link instance;

    public interface Listener { void onMessages(); }

    private final SharedPreferences prefs;
    private final ConcurrentLinkedQueue<String> inbox = new ConcurrentLinkedQueue<String>();
    private final LinkedBlockingQueue<String> outbox = new LinkedBlockingQueue<String>(200);
    private volatile Socket current;
    private volatile ServerSocket server;
    private volatile Listener listener;
    private volatile boolean connected;
    private volatile Vigia vigia;
    private Thread acceptThread;

    private Link(SharedPreferences p) { prefs = p; }

    public static synchronized Link get(SharedPreferences p) {
        if (instance == null) instance = new Link(p);
        return instance;
    }

    public void setListener(Listener l) { listener = l; }
    void setVigia(Vigia v) { vigia = v; }

    /** Mensagem gerada no proprio tablet (ex.: estado da escuta com o PC desligado). */
    public void local(String json) { deliver(json); }
    public boolean isConnected() { return connected; }

    public synchronized void start() {
        if (acceptThread != null) return;
        acceptThread = new Thread(new Runnable() { public void run() { acceptLoop(); } }, "link-accept");
        acceptThread.setDaemon(true);
        acceptThread.start();
        Thread w = new Thread(new Runnable() { public void run() { writeLoop(); } }, "link-write");
        w.setDaemon(true);
        w.start();
    }

    /** Fecha o socket de escuta para que ele seja recriado com a configuracao nova. */
    public void rebind() {
        ServerSocket s = server;
        if (s != null) try { s.close(); } catch (Exception ignored) {}
    }

    public String drain() {
        StringBuilder sb = new StringBuilder("[");
        String m; boolean first = true;
        while ((m = inbox.poll()) != null) {
            if (!first) sb.append(',');
            sb.append(m); first = false;
        }
        return sb.append(']').toString();
    }

    public void send(String line) {
        if (line == null || line.indexOf('\n') >= 0) return;
        if (!connected) return;
        outbox.offer(line);
    }

    private void deliver(String json) {
        inbox.add(json);
        if (inbox.size() > 300) inbox.poll();
        Listener l = listener;
        if (l != null) l.onMessages();
    }

    private void setConnected(boolean up) {
        connected = up;
        Vigia v = vigia;
        if (v != null) v.setLink(up);
        deliver("{\"t\":\"link\",\"up\":" + up + "}");
    }

    private void acceptLoop() {
        while (true) {
            try {
                boolean wifi = prefs.getBoolean("wifi", false);
                ServerSocket ss = new ServerSocket();
                ss.setReuseAddress(true);
                ss.bind(wifi ? new InetSocketAddress(PORT)
                             : new InetSocketAddress(InetAddress.getByName("127.0.0.1"), PORT));
                server = ss;
                Log.i(TAG, "escutando porta " + PORT + (wifi ? " (wifi)" : " (usb)"));
                while (!ss.isClosed()) {
                    final Socket s = ss.accept();
                    Socket old = current;
                    current = s;
                    if (old != null) try { old.close(); } catch (Exception ignored) {}
                    Thread t = new Thread(new Runnable() { public void run() { readLoop(s); } }, "link-read");
                    t.setDaemon(true);
                    t.start();
                }
            } catch (Exception e) {
                Log.w(TAG, "accept: " + e);
            }
            try { Thread.sleep(1500); } catch (InterruptedException ignored) {}
        }
    }

    private void readLoop(Socket s) {
        try {
            s.setTcpNoDelay(true);
            s.setKeepAlive(true);
            s.setSoTimeout(20000); // o PC manda dados a cada ~1,5 s
            OutputStream os = s.getOutputStream();
            os.write(("{\"t\":\"hi\",\"app\":\"painelpc\",\"ver\":1}\n").getBytes("UTF-8"));
            os.flush();
            BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), "UTF-8"), 16384);
            String token = prefs.getString("token", "");
            boolean wifi = prefs.getBoolean("wifi", false);
            boolean authed = !(wifi && token.length() > 0);
            String line;
            boolean announced = false;
            while ((line = in.readLine()) != null) {
                if (line.length() == 0) continue;
                if (!authed) {
                    try {
                        JSONObject o = new JSONObject(line);
                        authed = token.equals(o.optString("token"));
                    } catch (Exception ignored) {}
                    if (!authed) break;
                }
                if (!announced) { setConnected(true); announced = true; }
                if (line.startsWith("{\"t\": \"hello\"") || line.startsWith("{\"t\":\"hello\"")) saveWol(line);
                deliver(line);
            }
        } catch (Exception e) {
            Log.i(TAG, "conexao encerrada: " + e);
        } finally {
            try { s.close(); } catch (Exception ignored) {}
            if (current == s) {
                current = null;
                setConnected(false);
            }
        }
    }

    /** Guarda o endereco do PC (MAC + broadcast) para liga-lo pela rede quando estiver desligado. */
    private void saveWol(String line) {
        try {
            JSONObject w = new JSONObject(line).optJSONObject("wol");
            if (w == null) return;
            String mac = w.optString("mac", ""), bc = w.optString("bcast", "");
            if (mac.matches("([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"))
                prefs.edit().putString("wol_mac", mac).putString("wol_bcast", bc).commit();
        } catch (Exception e) {
            Log.w(TAG, "wol: " + e);
        }
    }

    private void writeLoop() {
        while (true) {
            try {
                String line = outbox.poll(30, TimeUnit.SECONDS);
                if (line == null) continue;
                Socket s = current;
                if (s == null) continue;
                OutputStream os = s.getOutputStream();
                os.write((line + "\n").getBytes("UTF-8"));
                os.flush();
            } catch (Exception e) {
                Log.w(TAG, "write: " + e);
            }
        }
    }
}
