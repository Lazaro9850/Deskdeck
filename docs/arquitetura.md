# Arquitetura

Como o PC e o tablet conversam, e onde fica cada coisa.

[← voltar ao README](../README.md)

## Visão geral

```
 PC (Windows)                                         Tablet (Android 4.1+)
 ┌──────────────────────────────┐    cabo USB        ┌──────────────────────────────┐
 │ agent\painel_agent.py        │  adb forward       │ app "Painel PC" (Java, 40 KB)│
 │  · CPU/GPU/RAM (psutil, PDH) │ ─────────────────▶ │  escuta 127.0.0.1:7001       │
 │  · música (Windows SMTC)     │  JSON por linha    │  WebView em tela cheia       │
 │  · apps da barra de tarefas  │ ◀───────────────── │  (HTML/JS ES5)               │
 │  · uso do Claude Code        │  toques/comandos   └──────────────────────────────┘
 │  · ações dos botões          │
 │ 127.0.0.1:8765 (só p/ hook)  │
 └──────────────────────────────┘
```

* O Android 4.1 não tem `adb reverse`. Por isso a conexão é invertida: **o tablet escuta** e o PC chega até ele com
  `adb forward`. Não fica nenhuma porta aberta na rede.
* **O agente só coleta o que a aba aberta mostra.** Na aba Apps, só a lista de programas abertos. Na aba Painel, sistema, música e Claude. Na aba Processos, só a tabela. Com o tablet desconectado, não coleta nada.
* **Consumo medido no PC (Ryzen 5 5600G):** ~0,01% de CPU e ~70 MB de RAM nas abas Apps e Painel, e ~0,3% de CPU com a aba Processos aberta.

## Estrutura

```
agent/
  painel_agent.py        agente do PC (coleta, conexão com o tablet, ações)
  usage_and_apps.py      uso do Claude Code e apps da barra de tarefas
  audio_helper.cs        auxiliar de áudio (Core Audio), compilado na instalação
  audio_helper.ps1       versão PowerShell do auxiliar (reserva)
  taskbar_apps.ps1       extrai ícones dos apps fixados
  claude_hook.py         hook de permissões do Claude Code -> tablet
  claude_statusline.py   status line do Claude Code (grava os limites)
  config.json            botões e opções
  PainelPC.apk           app pronto para o tablet
android/
  src/…                  MainActivity (WebView em tela cheia), Link (socket), BootReceiver
  assets/panel.html      a interface (ES5, roda no WebKit do Android 4.1)
  build_apk.ps1          compila o APK sem Gradle
tablet/
  enxugar_tablet.ps1     deixa o tablet só com o essencial (reversível)
install_pc.ps1           instala/atualiza/remove o agente no PC
install_claude_integration.ps1
```

## Nomes internos

O projeto se chama **DeskDeck**, mas alguns nomes internos continuam `PainelPC` para não quebrar instalações existentes: a pasta `%USERPROFILE%\PainelPC`, a tarefa agendada "Painel PC", o pacote Android `br.local.painelpc` e o arquivo `PainelPC.apk`.

## Modo demonstração

`pythonw painel_agent.py --demo` troca todos os dados por dados fictícios (apps genéricos, música de exemplo, uso do Claude simulado, processos inventados) e encena conversas do Jarvis ao tocar em Falar. Nenhum botão executa ações no PC. Os prints deste repositório foram feitos assim. Feche o agente normal antes (ou ele assume de novo em até 1 min pela tarefa agendada).
