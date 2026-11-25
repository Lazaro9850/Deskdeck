# SteamDeck — painel de mesa para o PC num tablet/Android antigo

Transforma um tablet ou celular Android **antigo** (a partir do **Android 4.1**) em um painel de mesa para o
computador Windows: atalhos dos seus apps, uso de CPU/GPU/RAM em tempo real, música tocando com controles,
botões estilo *Stream Deck*, consumo do **Claude Code** e um mini Gerenciador de Tarefas. Tudo pelo cabo USB, sem nuvem,
sem conta e sem root.

> Inspirado no [PhoneBox](https://github.com/ersinkoc/phonebox), que exige Android 5+ e `adb reverse`.
> Este projeto foi escrito do zero para funcionar em aparelhos bem mais antigos, como um tablet
> Rockchip RK2928 com Android 4.1.1, 390 MB de RAM e um núcleo de CPU.
>
> O nome é só o apelido do projeto. Ele não tem relação com a Valve nem com o Steam Deck.

---

## O que aparece no tablet

O painel tem três abas. Para trocar, arraste para o lado ou toque nas abas no topo.

| Aba | Conteúdo |
|---|---|
| **Apps** | Os apps **fixados na barra de tarefas do Windows**, com os ícones reais e na mesma ordem. Um traço azul marca os que estão abertos. Um toque abre o app no PC. |
| **Painel** | CPU (modelo e GHz) e GPU com gráfico, RAM, disco e rede · **Tocando agora** (capa, artista, app e barra de progresso, com anterior/play/próxima) · **Claude Code**: uso da sessão (5h) e semanal, com barra e horário de reinício · botões **Volume −/+**, **Mudo** e **Recorte de tela** |
| **Processos** | Os 7 programas que mais usam o PC, agrupados como no Gerenciador de Tarefas, com CPU, memória, disco e GPU. Toque no cabeçalho para ordenar. |

Extras:

- **Tela cheia de verdade:** o painel cobre a barra do Android sem mexer no sistema. Toque e segure o relógio por 1 s para mostrar ou esconder a barra.
- **Aprovações do Claude Code pelo tablet (opcional):** os pedidos de permissão aparecem no tablet com os botões **Permitir** e **Negar**.
- **Inicia sozinho:** o tablet abre o painel ao ligar, e o PC inicia o agente no login e o reabre se ele fechar.
- **Relógio:** usa a hora do PC, porque tablets velhos sem internet costumam estar com o relógio errado.

## Como funciona

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

## Requisitos

**PC**
* Windows 10 ou 11 (x64)
* [Python 3.10+](https://www.python.org/downloads/)
* [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) (o `adb`)
* Para compilar o auxiliar de áudio: .NET Framework 4 (já vem no Windows; o `install_pc.ps1` usa o `csc.exe`)

**Tablet/celular**
* Android 4.1 ou mais novo
* **Depuração USB** ligada: Configurações → Sobre → toque 7× em "Número da versão" → Opções do desenvolvedor → Depuração USB
* Cabo USB **de dados**

## Instalação

```powershell
git clone https://github.com/Lazaro9850/SteamDeck.git
cd SteamDeck
powershell -ExecutionPolicy Bypass -File .\install_pc.ps1
```

O instalador:
1. copia o agente para `%USERPROFILE%\PainelPC` (código, bibliotecas, ADB próprio e logs). A pasta fica fora do AppData de propósito, veja [Problemas comuns](#problemas-comuns);
2. instala as dependências Python dentro dessa pasta (`pip --target`);
3. compila o auxiliar de áudio (`audio_helper.exe`, ~12 MB de RAM);
4. registra a tarefa agendada **"Painel PC"**, que roda no login e reabre o agente se ele fechar;
5. inicia o agente.

Conecte o tablet. Na primeira vez, aceite o pedido de depuração USB na tela dele. O agente **instala o app no tablet
sozinho** (`agent\PainelPC.apk`) e o abre.

Para desinstalar no PC: `.\install_pc.ps1 -Uninstall`. Para remover o app do tablet: `adb uninstall br.local.painelpc`.

## Personalização

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

## Jarvis: assistente de voz

A 4ª aba do tablet é o **Jarvis**: um reator animado que mostra o estado (em espera, ouvindo, pensando, falando),
a conversa e um botão grande **Falar/Parar**. O plano completo está em [docs/PLANO-JARVIS.md](docs/PLANO-JARVIS.md).

| Fase | Situação |
|---|---|
| 1. Aba e serviço | ✅ |
| 2. Ouvir e falar de verdade | ✅ microfone do PC + **Whisper small** (fala → texto) + **Kokoro** (voz PT-BR), tudo local |
| 3. Cérebro (Claude Code) | ✅ pela sua assinatura do Claude Code (sem chave de API): Haiku para pedidos rápidos, Sonnet para os complexos; pesquisa na web; lembra da conversa por 10 min |
| 4. Ações no PC (MCP) | ✅ abrir e fechar apps, música, volume, recorte, estado do PC e processos; **fechar app pede Permitir/Negar no tablet** |
| 5. "Hey Jarvis" e modo jogo | ✅ diga **"Hey Jarvis"** (pronúncia em inglês) e ele responde com um bipe; com um jogo ou vídeo em tela cheia, a escuta pausa sozinha e os modelos de voz saem da memória |
| 6. Acabamento | ✅ **"Hey Jarvis" no meio da fala interrompe** e ele volta a ouvir; "para", "chega" ou "obrigado" encerram sem gastar o plano; histórico das últimas conversas salvo no PC |

**O que dá para pedir:** "abre o Discord", "pausa a música", "próxima", "aumenta o volume", "tira um print",
"como está o PC?", "o que está pesando agora?", "fecha o Paint" (pede confirmação no tablet), além de perguntas
em geral, contas e pesquisas (clima, notícias…).

As ações passam pelo servidor MCP `agent/mcp_painel.py`, que só repassa pedidos ao agente do painel por
127.0.0.1 com um token renovado a cada execução. O Jarvis não tem acesso a terminal, arquivos ou instalação
de programas.

As respostas usam o **limite do seu plano** (o mesmo das barras da aba Painel). Uma pergunta simples no Haiku gasta muito pouco.

```powershell
.\install_pc.ps1 -Jarvis   # libs de voz (~320 MB) e modelos (~800 MB, SHA-256 conferido)
```

* **"Hey Jarvis"**: ligue na chave da aba Jarvis (fica salvo). Escutando, gasta ~4% de um núcleo (~0,3% de um Ryzen 5 5600G) e ~125 MB; em **modo jogo** a escuta pausa e o custo vai a zero. O botão Falar funciona sempre.
* O Jarvis roda num processo separado, aberto só quando a aba é usada (ou no login, se o "Hey Jarvis" estiver ligado). Parado, ele ocupa ~10 MB.
  Com os modelos carregados, ocupa ~750 MB, e eles saem da memória depois de 5 min sem uso.
* O áudio é processado **no PC**: nada de voz sai do computador. Só o **texto** do pedido vai para o Claude Code.
* Opções em `config.json`, bloco `"jarvis"`:

```json
"jarvis": { "mic": "AB13X", "voice": "pf_dora", "speed": 1.05, "wake_threshold": 0.5,
            "game_mode": true, "barge_in": true, "model": "" }
```

  `mic` é parte do nome do microfone; se ficar vazio, ele usa o padrão do Windows, ou o headset se o padrão for virtual (DroidCam etc.).
  `voice` aceita `pf_dora` (feminina), `pm_alex` ou `pm_santa` (masculinas).
  `wake_threshold`: sensibilidade do "Hey Jarvis" (menor = dispara mais fácil; padrão 0,5).
  `game_mode`: pausar a escuta com app em tela cheia (padrão `true`).
  `barge_in`: dizer "Hey Jarvis" enquanto ele fala o interrompe (padrão `true`; com caixas de som em vez de
  headset, desligue se ele se interromper sozinho).
  `model`: fixa o modelo (`haiku` ou `sonnet`); vazio = escolhe pelo pedido.

**Arquivos locais do Jarvis** (em `%USERPROFILE%\PainelPC\data`): `jarvis.log` (diagnóstico),
`jarvis_historico.json` (últimas 20 conversas, só no seu PC) e `jarvis_state.json` (se o "Hey Jarvis" está ligado).
A personalidade fica em `agent/jarvis_persona.md`; a pasta de trabalho do Claude Code do Jarvis é `%USERPROFILE%\Jarvis`.

**Consumo medido** (Ryzen 5 5600G, tudo ligado, incluindo o "Hey Jarvis" escutando): ~0,35% de CPU e ~200 MB de RAM.
Sem o "Hey Jarvis", ~70 MB. Durante uma conversa, os modelos de voz ocupam ~750 MB e saem da memória após 5 min parados
ou na hora em que um jogo entra em tela cheia.

## Deixar o tablet leve (opcional, para tablets dedicados)

Se o aparelho vai servir **só** de painel, o `tablet\enxugar_tablet.ps1` desativa tudo que não é essencial:
apps do Google, apps de fábrica, teclado, launcher (o painel vira a tela inicial), Wi-Fi e animações.

```powershell
.\tablet\enxugar_tablet.ps1              # desativa (pm disable): nada é apagado
.\tablet\enxugar_tablet.ps1 -Restaurar   # volta tudo
```

No tablet de teste, a RAM livre foi de **21 MB para 182 MB** e o boot caiu de 42 s para 34 s.

> ⚠️ O script precisa de `adb` com root, o que é o caso em builds "eng" como a de muitos tablets genéricos. Apps de sistema
> marcados como *persistentes*, como o Skype de fábrica de alguns modelos, só param se o APK for renomeado em
> `/system/app`. O script faz isso e desfaz no `-Restaurar`. Use só num aparelho dedicado ao painel.

## Compilar o app Android

Não precisa de Gradle. Requer Android SDK (build-tools e platforms) e JDK 17:

```powershell
.\android\build_apk.ps1          # gera android\PainelPC.apk (minSdk 16, assinatura v1)
adb install -r android\PainelPC.apk
```

Na primeira compilação, o script cria uma chave de assinatura nova (`android\painelpc.keystore`, que o `.gitignore` ignora).
Atualizações do app precisam da mesma chave. Se você trocar de chave, desinstale o app do tablet antes.

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

## Problemas comuns

| Sintoma | Solução |
|---|---|
| Tablet mostra "Sem PC" | Veja o log em `%USERPROFILE%\PainelPC\data\agent.log`. Confira se `adb devices` lista o aparelho como `device`. |
| `unauthorized` no `adb devices` | Aceite o pedido de depuração USB na tela do tablet. |
| Não reconecta depois de reiniciar o PC | Abra o Agendador de Tarefas, confira a tarefa "Painel PC" e rode `.\install_pc.ps1` de novo. |
| Instalado por dentro de um app empacotado (MSIX) e "some" fora dele | Apps MSIX virtualizam o `AppData`. Por isso o projeto instala em `%USERPROFILE%\PainelPC`. |
| Barras do Claude vazias | Login do Claude Code vencido ou limite de consultas da Anthropic (HTTP 429). O agente tenta de novo sozinho, com espera crescente. |
| Falha nativa do agente | O rastro fica em `%USERPROFILE%\PainelPC\data\crash.log`. |

## Limitações conhecidas

* Só Windows no PC (usa APIs do Windows para mídia, áudio, ícones e contadores de desempenho).
* A coluna "Rede por processo" não existe, porque o Windows não fornece esse dado sem privilégios de administrador.
* O modo Wi-Fi existe (`--ez wifi true --es token …` no app e `wifi_host`/`wifi_token` no `config.json`), mas não
  tem criptografia, porque o Android 4.1 não suporta TLS moderno. O USB é o modo recomendado.
