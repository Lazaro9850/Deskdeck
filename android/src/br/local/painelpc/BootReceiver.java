package br.local.painelpc;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Abre o painel automaticamente quando o tablet termina de ligar. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        if (!ctx.getSharedPreferences("painel", 0).getBoolean("autostart", true)) return;
        Intent i = new Intent(ctx, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ctx.startActivity(i);
    }
}
