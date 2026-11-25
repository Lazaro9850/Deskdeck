# Instala o agente do Painel PC neste computador, em %USERPROFILE%\PainelPC:
#   agent\  codigo + config.json (mantido se ja existir)
#   libs\   bibliotecas Python (pip --target), independentes do Python do usuario
#   data\   log, caches e crash.log
# e registra a tarefa agendada "Painel PC" (inicia no login e reabre o agente se ele fechar).
#
# Fica fora do AppData de proposito: apps empacotados (MSIX), como o Claude desktop,
# virtualizam o AppData. O que um deles grava ali nao existe para o resto do Windows.
# Desinstalar: .\install_pc.ps1 -Uninstall
# Jarvis (assistente de voz, opcional): .\install_pc.ps1 -Jarvis
#   instala libs de voz em libs-jarvis\ (~320 MB) e baixa os modelos em models\ (~800 MB, SHA-256 conferido)
param([switch]$Uninstall, [switch]$Jarvis)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = "$env:USERPROFILE\PainelPC"
$dest = "$root\agent"
$task = 'Painel PC'

function Stop-Agent {
  Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*painel_agent.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Agente parado (PID $($_.ProcessId))" }
}
function Remove-Old {
  # instalacoes anteriores (atalho de Inicializar e tarefa "vigia")
  $lnk = [Environment]::GetFolderPath('Startup') + '\Painel PC.lnk'
  if (Test-Path $lnk) { Remove-Item $lnk -Force }
  Unregister-ScheduledTask -TaskName 'Painel PC (vigia)' -Confirm:$false -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName 'Painel PC (diag)' -Confirm:$false -ErrorAction SilentlyContinue
}

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
  Remove-Old; Stop-Agent
  Write-Host "Tarefa removida. Arquivos mantidos em $root (apague a pasta se quiser)."
  return
}

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw 'Python 3 nao encontrado. Instale em https://www.python.org/downloads/' }
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }

Remove-Old; Stop-Agent
New-Item -ItemType Directory -Force $dest, "$root\libs", "$root\data" | Out-Null

Write-Host "Instalando bibliotecas Python em $root\libs ..."
& $py -m pip install --disable-pip-version-check -q --upgrade --target "$root\libs" -r "$here\agent\requirements.txt"

foreach ($f in 'painel_agent.py','jarvis_service.py','palmas.py','demo.py','jarvis_persona.md','mcp_painel.py','jarvis_models.py','requirements-jarvis.txt','usage_and_apps.py','taskbar_apps.ps1','audio_helper.ps1','audio_helper.cs','claude_hook.py','claude_statusline.py','requirements.txt','PainelPC.apk') {
  Copy-Item "$here\agent\$f" "$dest\$f" -Force
}

if ($Jarvis) {
  Write-Host "Jarvis: instalando bibliotecas de voz em $root\libs-jarvis ..."
  & $py -m pip install --disable-pip-version-check -q --upgrade --target "$root\libs-jarvis" -r "$here\agent\requirements-jarvis.txt"
  Write-Host "Jarvis: baixando modelos em $root\models (Whisper small + Kokoro) ..."
  & $py "$dest\jarvis_models.py" "$root\models"
  if ($LASTEXITCODE) { Write-Warning 'Jarvis: falha ao baixar ou conferir os modelos.' }
}
# ADB proprio (adb.exe + DLLs) dentro da pasta do Painel
$adbSrc = @((Get-Command adb -ErrorAction SilentlyContinue).Source, "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe") |
          Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($adbSrc) {
  New-Item -ItemType Directory -Force "$root\platform-tools" | Out-Null
  & $adbSrc kill-server 2>$null
  foreach ($f in 'adb.exe','AdbWinApi.dll','AdbWinUsbApi.dll') { Copy-Item (Join-Path (Split-Path $adbSrc) $f) "$root\platform-tools\$f" -Force }
  Write-Host "ADB copiado para $root\platform-tools"
} else { Write-Warning 'ADB nao encontrado: instale o Android SDK Platform-Tools.' }

# auxiliar de audio compilado (~12 MB de RAM em vez de ~60 MB do PowerShell)
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (Test-Path $csc) { & $csc /nologo /optimize /target:winexe "/out:$dest\audio_helper.exe" "$dest\audio_helper.cs" | Out-Null }

if (-not (Test-Path "$dest\config.json")) { Copy-Item "$here\agent\config.json" "$dest\config.json" }
else { Write-Host 'config.json existente mantido.' }
Copy-Item "$here\README.md" "$root\README.md" -Force -ErrorAction SilentlyContinue

# Tarefa: no login + a cada 1 min. Se o agente ja estiver rodando, a copia nova sai
# na hora (porta 8765 ocupada); se ele tiver sido fechado, volta sozinho.
$act = New-ScheduledTaskAction -Execute "`"$pyw`"" -Argument "`"$dest\painel_agent.py`""
$t1  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$t2  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
         -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $act -Trigger @($t1, $t2) -Settings $set -Force | Out-Null
Write-Host "Tarefa agendada '$task' registrada (login + vigia a cada 1 min)."

Start-ScheduledTask -TaskName $task
Write-Host "Agente iniciado pela tarefa. Log: $root\data\agent.log"
