# Personalizar

Botões do Painel e integração com o Claude Code.

[← voltar ao README](../README.md)

## Botões

Edite `%USERPROFILE%\PainelPC\agent\config.json`. A tarefa agendada reabre o agente em até 1 min (ou feche o `pythonw.exe`).

```json
{ "id": "notas", "label": "Notas", "icon": "note", "color": "#3ec7e0", "type": "run", "cmd": "notepad.exe" }
```

| `type` | Campos | Exemplo |
|---|---|---|
| `run` | `cmd` (texto ou lista de alternativas), `args` | `"cmd": ["wt.exe", "powershell.exe"]` |
| `url` | `url` | `"url": "https://youtube.com"` |
| `keys` | `keys` | `["ctrl","shift","esc"]`, `["win","shift","s"]` |
| `media` | `cmd`: `next` / `prev` / `playpause` | |
| `volume` | `cmd`: `up` / `down` / `mute` | |
| `mic` | — | liga/desliga o mudo do microfone |
| `lock` | — | bloqueia o Windows |
| `obs` | usa `obs.host/port/password` | precisa do OBS 28+ com WebSocket e de `pip install obsws-python` |

Ícones disponíveis: `app note calc folder globe term tasks camera mic mute voldn volup rec lock play bolt`.

A aba **Apps** não precisa de configuração: ela acompanha os apps fixados na sua barra de tarefas.

## Claude Code (opcional)

O cartão do Claude mostra a **Sessão (5h)** e a **Semanal**:

* **Uso real do plano (Pro/Max):** o agente lê o login do Claude Code (`~/.claude/.credentials.json`) e consulta
  `api.anthropic.com/api/oauth/usage` no máximo a cada 5 minutos, e só com a aba Painel aberta. O token vai
  **apenas para a Anthropic**: não aparece no log, não vai para o tablet e não é salvo em outro lugar.
* **Login vencido** (dura ~8 h): o agente roda `claude -p "ok" --model haiku` uma vez em segundo plano, e o próprio
  Claude Code renova o login. Isso acontece no máximo 1× a cada 30 min e gasta uma fração mínima do plano.
* **Sem login:** o cartão mostra os tokens contados nos logs locais (`~/.claude/projects`).

Para receber os **pedidos de permissão** do Claude Code no tablet e gravar os limites pela status line:

```powershell
.\install_claude_integration.ps1          # faz backup do ~/.claude/settings.json antes
.\install_claude_integration.ps1 -Uninstall
```
