# OPCIONAL - integra o Claude Code ao Painel PC (altera ~/.claude/settings.json).
#  - statusLine: mostra modelo e limites na barra do Claude Code e grava os
#    percentuais reais (5h / 7 dias) para o tablet.
#  - hook PermissionRequest: os pedidos de permissao aparecem no tablet
#    (Permitir / Negar). Sem resposta em 60 s, o pedido normal aparece no PC.
# Faz backup antes. Para desfazer: .\install_claude_integration.ps1 -Uninstall
param([switch]$Uninstall, [switch]$NoHook, [switch]$NoStatusLine)
$ErrorActionPreference = 'Stop'
$settings = "$env:USERPROFILE\.claude\settings.json"
$agent    = "$env:USERPROFILE\PainelPC\agent"
$py       = (Get-Command python).Source
if (-not (Test-Path "$agent\claude_hook.py")) { throw 'Rode primeiro o install_pc.ps1.' }

$raw  = if (Test-Path $settings) { Get-Content $settings -Raw -Encoding UTF8 } else { '{}' }
$backup = "$settings.painelpc-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
if (Test-Path $settings) { Copy-Item $settings $backup; Write-Host "Backup: $backup" }

# Edita o JSON em Python para preservar todas as outras chaves.
$code = @'
import json, sys
path, mode, py, agent, hook, sl = sys.argv[1:7]
try:
    cfg = json.load(open(path, encoding="utf-8"))
except FileNotFoundError:
    cfg = {}
hook_cmd = '"%s" "%s\\claude_hook.py"' % (py, agent)
sl_cmd = '"%s" "%s\\claude_statusline.py"' % (py, agent)
hooks = cfg.setdefault("hooks", {})
lst = [h for h in hooks.get("PermissionRequest", []) if "claude_hook.py" not in json.dumps(h)]
if mode == "install" and hook == "1":
    lst.append({"matcher": "*", "hooks": [{"type": "command", "command": hook_cmd, "timeout": 90}]})
if lst: hooks["PermissionRequest"] = lst
else: hooks.pop("PermissionRequest", None)
if not hooks: cfg.pop("hooks", None)
if mode == "install" and sl == "1":
    if cfg.get("statusLine") and "claude_statusline.py" not in json.dumps(cfg["statusLine"]):
        print("Ja existe uma statusLine sua; nao foi alterada.")
    else:
        cfg["statusLine"] = {"type": "command", "command": sl_cmd}
elif mode == "uninstall" and "claude_statusline.py" in json.dumps(cfg.get("statusLine", "")):
    cfg.pop("statusLine", None)
json.dump(cfg, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("settings.json atualizado (%s)." % mode)
'@
$tmp = Join-Path $env:TEMP 'painelpc_claude_cfg.py'
Set-Content -Path $tmp -Value $code -Encoding UTF8
$mode = if ($Uninstall) { 'uninstall' } else { 'install' }
& $py -I $tmp $settings $mode $py $agent ($(if ($NoHook) {'0'} else {'1'})) ($(if ($NoStatusLine) {'0'} else {'1'}))
Remove-Item $tmp -Force
Write-Host 'Reinicie as sessoes do Claude Code para aplicar.'
