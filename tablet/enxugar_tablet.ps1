# Deixa o tablet so com o essencial para o Painel PC.
# Tudo e DESATIVADO (pm disable), nao apagado: volta com .\enxugar_tablet.ps1 -Restaurar
# Requer adb com acesso root (o DL 1603 tem build "eng", entao o adbd ja roda como root).
#
# Wi-Fi (para o tablet ligar o PC pela rede quando ele estiver desligado):
#   .\enxugar_tablet.ps1 -ConectarWifi   reativa so Configuracoes + teclado e abre a tela do Wi-Fi;
#                                        voce escolhe a rede e digita a senha NO TABLET
#   .\enxugar_tablet.ps1 -WifiPronto     desativa de novo Configuracoes + teclado (o Wi-Fi fica ligado)
param([switch]$Restaurar, [switch]$ConectarWifi, [switch]$WifiPronto)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$adb = @("$env:USERPROFILE\PainelPC\platform-tools\adb.exe", (Get-Command adb -ErrorAction SilentlyContinue).Source) |
       Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $adb) { throw 'adb nao encontrado' }
$lista = Join-Path $here 'desativados.txt'

function Set-Animacoes([string]$v) {
  # roda o sqlite3 por um script no tablet (evita problemas de aspas entre PowerShell e adb)
  $t = Join-Path $env:TEMP 'painel_anim.sh'
  [IO.File]::WriteAllText($t, "sqlite3 /data/data/com.android.providers.settings/databases/settings.db " +
    """update system set value='$v' where name in ('window_animation_scale','transition_animation_scale','animator_duration_scale');""`n")
  & $adb push $t /data/local/tmp/painel_anim.sh 2>&1 | Out-Null
  & $adb shell sh /data/local/tmp/painel_anim.sh
  & $adb shell rm /data/local/tmp/painel_anim.sh
  Remove-Item $t
}

# O que FICA ativo: nucleo do Android + o painel. (Todo o resto pode ser desativado.)
$manter = @(
  'android', 'br.local.painelpc',
  'com.android.systemui',            # barra/sistema (o painel cobre a barra)
  'com.android.phone', 'com.android.providers.telephony',   # servico permanente do sistema
  'com.android.providers.settings',  # banco de configuracoes do sistema
  'com.android.providers.media',     # usado pelo sistema (sons, toques)
  'com.android.defcontainer', 'com.android.packageinstaller', # necessarios para instalar/atualizar o painel
  'com.android.keychain', 'com.android.inputdevices', 'com.android.certinstaller'
)

$wifiApps = @('com.android.settings', 'com.android.inputmethod.latin')
if ($ConectarWifi) {
  foreach ($p in $wifiApps) { & $adb shell pm enable $p | Out-Null }
  & $adb shell svc wifi enable
  & $adb shell am start -n br.local.painelpc/.MainActivity --ez cover false | Out-Null   # painel sai da frente
  Start-Sleep 2
  & $adb shell am start -a android.settings.WIFI_SETTINGS | Out-Null
  Write-Host 'Escolha a rede e digite a senha no tablet. Depois rode: .\enxugar_tablet.ps1 -WifiPronto'
  return
}
if ($WifiPronto) {
  & $adb shell am force-stop com.android.settings
  foreach ($p in $wifiApps) { & $adb shell pm disable $p | Out-Null }
  & $adb shell am start -n br.local.painelpc/.MainActivity --ez cover true | Out-Null
  $ok = (& $adb shell dumpsys wifi) -match 'Wi-Fi is enabled' -and ((& $adb shell dumpsys connectivity) -match 'WIFI.*CONNECTED')
  Write-Host ("Wi-Fi " + $(if ($ok) { 'conectado' } else { 'ligado, mas NAO conectado (rode -ConectarWifi de novo)' }) + '; Configuracoes e teclado desativados.')
  return
}

if ($Restaurar) {
  if (-not (Test-Path $lista)) { throw "Lista $lista nao encontrada" }
  foreach ($p in Get-Content $lista) { if ($p) { & $adb shell pm enable $p | Out-Null; "reativado: $p" } }
  & $adb shell svc wifi enable
  Set-Animacoes '1.0'
  # Skype: app de sistema "persistente" (o Android o reabria mesmo desativado); o APK foi so renomeado
  & $adb remount | Out-Null
  & $adb shell "if [ -f /system/app/Skype.apk.desativado ]; then mv /system/app/Skype.apk.desativado /system/app/Skype.apk; fi"
  Write-Host 'Pronto. Reinicie o tablet (adb reboot) para aplicar.'
  return
}

$ativos = (& $adb shell pm list packages -e) -replace 'package:', '' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$alvo = $ativos | Where-Object { $manter -notcontains $_ } | Sort-Object
$ja = if (Test-Path $lista) { Get-Content $lista } else { @() }
($ja + $alvo | Sort-Object -Unique) | Set-Content $lista -Encoding ascii
foreach ($p in $alvo) {
  $r = (& $adb shell pm disable $p) -join ' '
  if ($r -match 'disabled') { "desativado: $p" } else { "FALHOU: $p -> $r" }
}

# Wi-Fi: fica ligado se ja houver uma rede salva (para ligar o PC pela rede); senao, desligado.
# Animacoes do sistema desligadas.
if ((& $adb shell "grep -c network= /data/misc/wifi/wpa_supplicant.conf 2>/dev/null") -match '^[1-9]') {
  & $adb shell svc wifi enable
} else {
  & $adb shell svc wifi disable
}
Set-Animacoes '0'
# Skype vem como app de sistema "persistente": o Android o reabre mesmo desativado.
# O APK so e renomeado (copia de seguranca em backup_sistema\ no PC).
& $adb remount | Out-Null
& $adb shell "if [ -f /system/app/Skype.apk ]; then mv /system/app/Skype.apk /system/app/Skype.apk.desativado; fi"
Write-Host "Lista salva em $lista. Reinicie o tablet (adb reboot) para aplicar tudo."
