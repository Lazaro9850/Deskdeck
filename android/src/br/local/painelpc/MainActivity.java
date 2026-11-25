package br.local.painelpc;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.graphics.PixelFormat;
import android.view.Display;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.FrameLayout;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** Tela cheia com um WebView que mostra o painel (assets/panel.html). */
public class MainActivity extends Activity implements Link.Listener {
    private WebView web;
    private FrameLayout root;
    private volatile boolean covered;
    private Link link;
    private Vigia vigia;
    private SharedPreferences prefs;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean pumpQueued;
    private volatile boolean pageReady;

    private final Runnable pump = new Runnable() {
        public void run() {
            pumpQueued = false;
            if (web != null && pageReady) web.loadUrl("javascript:window.PB&&PB.pump()");
        }
    };

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);

        prefs = getSharedPreferences("painel", MODE_PRIVATE);
        applyExtras(getIntent());

        web = new WebView(this);
        web.setBackgroundColor(0xFF0B0F14);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setRenderPriority(WebSettings.RenderPriority.HIGH);
        s.setAllowFileAccess(true);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, String url) { return true; }
            @Override public void onPageFinished(WebView v, String url) { pageReady = true; schedulePump(); }
        });
        web.addJavascriptInterface(new Bridge(), "Bridge");
        root = new FrameLayout(this);
        root.addView(web, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        applyCover(prefs.getBoolean("cover", true));
        web.loadUrl("file:///android_asset/panel.html");

        link = Link.get(prefs);
        link.setListener(this);
        link.start();
        // PC desligado: o tablet escuta as palmas e liga o PC pela rede (Vigia.java)
        vigia = new Vigia(this, prefs, new Vigia.Events() {
            public void onGuard(String json) { link.local(json); }
        });
        vigia.setLink(link.isConnected());
        link.setVigia(vigia);
        vigia.start();
        dimBars();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        applyExtras(intent);
    }

    /** Configuracao via adb: am start -n br.local.painelpc/.MainActivity --ez wifi true --es token XYZ */
    private void applyExtras(Intent i) {
        if (i == null || i.getExtras() == null) return;
        SharedPreferences.Editor e = prefs.edit();
        boolean rebind = false;
        if (i.hasExtra("wifi")) { e.putBoolean("wifi", i.getBooleanExtra("wifi", false)); rebind = true; }
        if (i.hasExtra("token")) { e.putString("token", i.getStringExtra("token")); rebind = true; }
        if (i.hasExtra("autostart")) e.putBoolean("autostart", i.getBooleanExtra("autostart", true));
        if (i.hasExtra("cover")) e.putBoolean("cover", i.getBooleanExtra("cover", true));
        if (i.hasExtra("claps")) e.putBoolean("claps", i.getBooleanExtra("claps", true));  // escuta com o PC desligado
        if (i.hasExtra("guard_test")) e.putBoolean("guard_test", i.getBooleanExtra("guard_test", false));
        if (i.hasExtra("clap_level")) e.putFloat("clap_level", i.getFloatExtra("clap_level", -36));
        if (i.hasExtra("clap_rise")) e.putFloat("clap_rise", i.getFloatExtra("clap_rise", 25));
        e.commit();
        if (i.hasExtra("cover") && root != null) applyCover(i.getBooleanExtra("cover", true));
        if (rebind && link != null) link.rebind();
        if (i.getBooleanExtra("reload", false) && web != null) { pageReady = false; web.reload(); }
    }

    private void dimBars() {
        web.setSystemUiVisibility(View.SYSTEM_UI_FLAG_LOW_PROFILE);
    }

    /**
     * Modo "cobrir a barra": o painel vai para uma janela de sistema (TYPE_SYSTEM_ERROR)
     * que fica por cima da barra do Android. Nada no sistema e alterado; desligar
     * o modo (toque longo no relogio) devolve o painel para a janela normal.
     */
    private void applyCover(boolean on) {
        // WindowManager da *aplicacao*: sem o token da activity, a janela e ordenada pela
        // camada de sistema e recebe os toques antes de qualquer dialogo escondido atras dela.
        WindowManager wm = (WindowManager) getApplicationContext().getSystemService(WINDOW_SERVICE);
        if (root.getParent() != null) {
            if (covered) wm.removeView(root);
            else ((ViewGroup) root.getParent()).removeView(root);
        }
        covered = false;
        if (on) {
            int[] wh = landscapeSize(wm);
            WindowManager.LayoutParams lp = new WindowManager.LayoutParams(wh[0], wh[1],
                    WindowManager.LayoutParams.TYPE_SYSTEM_ERROR,
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                            | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                            | WindowManager.LayoutParams.FLAG_FULLSCREEN
                            | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                    PixelFormat.OPAQUE);
            lp.gravity = Gravity.TOP | Gravity.LEFT;
            lp.x = 0; lp.y = 0;
            try {
                wm.addView(root, lp);
                covered = true;
            } catch (Exception e) {
                covered = false;
            }
        }
        if (!covered) setContentView(root);
        prefs.edit().putBoolean("cover", on).commit();
    }

    /**
     * Tamanho fisico da tela em paisagem, incluindo a area da barra (API oculta no 4.1).
     * No boot a tela ainda pode estar em retrato; como o painel so roda deitado,
     * usamos sempre largura = maior lado e altura = menor lado.
     */
    private static int[] landscapeSize(WindowManager wm) {
        int w = WindowManager.LayoutParams.MATCH_PARENT, h = WindowManager.LayoutParams.MATCH_PARENT;
        try {
            Display d = wm.getDefaultDisplay();
            int a = (Integer) Display.class.getMethod("getRawWidth").invoke(d);
            int b = (Integer) Display.class.getMethod("getRawHeight").invoke(d);
            w = Math.max(a, b);
            h = Math.min(a, b);
        } catch (Exception ignored) {}
        return new int[]{w, h};
    }

    @Override
    public void onConfigurationChanged(android.content.res.Configuration c) {
        super.onConfigurationChanged(c);
        if (!covered) return;
        try { // garante o tamanho certo depois de girar a tela
            WindowManager wm = (WindowManager) getApplicationContext().getSystemService(WINDOW_SERVICE);
            WindowManager.LayoutParams lp = (WindowManager.LayoutParams) root.getLayoutParams();
            int[] wh = landscapeSize(wm);
            lp.width = wh[0]; lp.height = wh[1];
            wm.updateViewLayout(root, lp);
        } catch (Exception ignored) {}
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) dimBars();
    }

    @Override
    public void onMessages() { schedulePump(); }

    private void schedulePump() {
        if (pumpQueued) return;
        pumpQueued = true;
        ui.postDelayed(pump, 30);
    }

    @Override
    public void onBackPressed() {
        // Painel de mesa: o botao Voltar nao fecha o app (use Home para sair).
        moveTaskToBack(true);
    }

    @Override
    protected void onDestroy() {
        if (link != null) link.setListener(null);
        if (covered) {
            try { ((WindowManager) getApplicationContext().getSystemService(WINDOW_SERVICE)).removeView(root); } catch (Exception ignored) {}
            covered = false;
        }
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** Ponte JavaScript <-> Java. So carregamos paginas locais (assets). */
    public class Bridge {
        @JavascriptInterface public String take() { return link.drain(); }
        @JavascriptInterface public void send(String line) { link.send(line); }
        @JavascriptInterface public boolean connected() { return link.isConnected(); }
        @JavascriptInterface public String mode() { return prefs.getBoolean("wifi", false) ? "wifi" : "usb"; }
        @JavascriptInterface public boolean covered() { return covered; }
        @JavascriptInterface public void wakePc() { if (vigia != null) vigia.wakeFromButton(); }
        @JavascriptInterface public void toggleCover() {
            ui.post(new Runnable() { public void run() { applyCover(!covered); } });
        }
    }
}
