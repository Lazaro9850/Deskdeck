# Plano: aba "Jarvis" no SteamDeck

## Objetivo

Criar um assistente de voz no PC, no estilo Jarvis, que usa o **Claude Code** (a assinatura que você já tem) como cérebro e
o **tablet como rosto e controle**. O tablet ganha uma 4ª aba com o "reator" animado, o que foi ouvido e respondido,
um botão grande para falar e as confirmações de ações.

## Arquitetura proposta

```
 Microfone do PC ──▶ jarvis_service.py ─────────────────────────────┐
  (headset)          · wake word "hey jarvis" (openWakeWord, local) │
                     · fala → texto: faster-whisper (local, PT-BR)  │
                     · cérebro: Claude Code via Agent SDK/CLI       │  eventos JSON
                       (login da assinatura, sem chave de API)      │  (estado, texto,
                     · ferramentas: MCP "painel" (abrir apps,       │   resposta,
                       mídia, volume, processos...)                 │   confirmações)
                     · texto → fala: Kokoro PT-BR (local) ou        ▼
                       voz Maria do Windows (SAPI, reserva)   painel_agent.py ──USB──▶ aba Jarvis no tablet
 Alto-falante do PC ◀── resposta falada                         (já existente)         (reator, texto, botão
                                                                                          "Falar", Permitir/Negar)
```

* **Processo separado** (`jarvis_service.py`): o agente do painel continua leve. O Jarvis só carrega modelos quando está ligado.
* **Ativação:** "Hey Jarvis" pelo microfone do PC, **ou** o botão "Falar" no tablet (push-to-talk), que funciona mesmo com a wake word desligada.
* **Modo jogo:** com um jogo em tela cheia (VALORANT etc.), a wake word fica pausada e a CPU volta a ~0%. O botão do tablet continua funcionando.
* **Segurança:** ações que mudam o PC passam pelo **hook de permissões já existente**, que mostra Permitir/Negar no tablet. Nada de modo "pular permissões".
* **Custo:** sem API paga. As respostas usam o limite do seu plano Pro, que o próprio painel já mostra.
  Pedidos simples vão para o **Haiku**, que é rápido e barato no limite. Pedidos complexos vão para o **Sonnet**.

## Fases

| Fase | Entrega | Como validar |
|---|---|---|
| 0. Decisões | Voz, modo de ativação e modelos definidos (ver "Escolhas" abaixo) | — |
| 1. Esqueleto | `jarvis_service.py` falando com o agente por 127.0.0.1; aba Jarvis no tablet com reator e estados (parado/ouvindo/pensando/falando) e botão "Falar" | Tocar "Falar" no tablet muda os estados na tela (com respostas simuladas) |
| 2. Ouvido e voz | faster-whisper (PT-BR) + Kokoro/SAPI; teste "repita o que eu falei" | Frase falada aparece no tablet e é repetida em voz |
| 3. Cérebro | Claude Code via Agent SDK (ou `claude -p --output-format stream-json`), memória da conversa, resposta falada **frase a frase** enquanto o texto chega; roteamento Haiku/Sonnet | "Que horas são em Tóquio?" responde em < 4 s |
| 4. Mãos | Servidor MCP `painel` reaproveitando as ações do agente: abrir apps da barra de tarefas, play/pause/próxima, volume, mudo, recorte, top processos, uso de CPU/GPU | "Jarvis, abre o Discord e pausa a música" funciona; ações de risco pedem confirmação no tablet |
| 5. Wake word e modo jogo | openWakeWord "hey_jarvis", pausa automática com jogo em tela cheia, descarrega modelos após 5 min parado | Medir CPU/RAM parado, ouvindo e em jogo |
| 6. Acabamento | Interromper a fala ("Jarvis, para"), histórico curto na aba, README, instalador atualizado | Teste completo + reinício do PC e do tablet |

## Escolhas a confirmar

1. **Voz:** Kokoro (local, natural; voz feminina `pf_dora` ou masculina `pm_alex`) ou a voz "Maria" do Windows (já instalada, mais robótica).
2. **Ativação:** wake word sempre ligada (exceto em jogo) **ou** só pelo botão do tablet.
3. **Microfone:** o do PC/headset (recomendado). O do tablet daria para usar, mas é fraco e exigiria gravar áudio no app Android 4.1.
4. **Pasta de trabalho do Jarvis:** onde o Claude Code roda (por exemplo `%USERPROFILE%\Jarvis`, com um `CLAUDE.md` de personalidade e regras).

## Prompt de implantação

Cole numa sessão nova do Claude Code aberta na pasta do repositório `SteamDeck`:

```text
Você vai adicionar ao projeto SteamDeck (este repositório) um assistente de voz "Jarvis" e uma 4ª aba "Jarvis" no tablet.
Leia o README.md inteiro antes de começar e preserve tudo o que já funciona.

## Contexto do projeto (não quebre)
- agent/painel_agent.py: agente Windows em Python. Conversa com o app Android por USB (adb forward, JSON por linha,
  porta 7001 no tablet). Já existe protocolo de mensagens: hello, stats, media, claude, procs, approval, toast, key.
  O tablet manda: press, media, decide, page, procsort, launch, ready.
- O agente coleta SÓ o que a aba aberta mostra (self.page: 0 Apps, 1 Painel, 2 Processos). A nova aba será a 3.
- Instalado em %USERPROFILE%\PainelPC (NUNCA em AppData: apps MSIX virtualizam o AppData). Tarefa agendada "Painel PC"
  inicia o agente no login. Instância única via mutex "Local\PainelPCAgent".
- android/assets/panel.html: interface em HTML/CSS/JS **ES5** para o WebView do Android 4.1 (sem let/const, arrow,
  fetch, Promise, flexbox moderno, classList não é garantido). Tela 800x480, escala por rem (1rem = 10px).
  Abas em #strip (largura 300% hoje → passe para 400%), goPage(n), tabs no topo (#tab0..#tab2 → adicione #tab3).
  Alto contraste: fundo #030507, cartões #141d27 com borda 2px #34465a, texto branco, destaque #4fd8f0, roxo #b18cff.
- android/build_apk.ps1 compila o APK sem Gradle (minSdk 16). Depois de mudar o app: compilar, copiar para
  agent/PainelPC.apk e `adb install -r`. Teste visual: `adb shell screencap -p` + `adb pull` e olhe a imagem.
- Já existe hook de permissões do Claude Code → tablet (agent/claude_hook.py, POST 127.0.0.1:8765/approval).
- O PC é usado para jogar (VALORANT): consumo de CPU/RAM em repouso precisa continuar perto de zero.

## O que construir
1. agent/jarvis_service.py: processo separado (o agente o inicia/encerra quando o Jarvis é ligado/desligado
   pelo tablet ou pelo config.json "jarvis": {"enabled": true, ...}). Comunicação com o agente por
   127.0.0.1 (uma conexão local, JSON por linha). Estados: parado, ouvindo, transcrevendo, pensando, falando, erro.
2. Ouvido: faster-whisper, modelo "small" int8 em CPU, idioma pt. Gravação do microfone padrão do PC com detecção
   de fim de fala (VAD do próprio faster-whisper ou webrtcvad). Carregar o modelo só quando o Jarvis estiver ligado
   e descarregar após 5 min sem uso.
3. Ativação: (a) botão "Falar" no tablet (push-to-talk: o tablet envia {"t":"jarvis","cmd":"listen"});
   (b) wake word "hey jarvis" com openWakeWord (modelo pronto "hey_jarvis"), desligável. Pausar a wake word
   automaticamente quando houver um app em tela cheia exclusiva/jogo em primeiro plano.
4. Cérebro: Claude Code pela assinatura do usuário, SEM chave de API: usar o Claude Agent SDK (Python) ou o CLI
   (`claude -p ... --output-format stream-json --resume <sessão>`), rodando na pasta %USERPROFILE%\Jarvis com um
   CLAUDE.md que define a persona (Jarvis, português do Brasil, respostas curtas e faladas, sem markdown).
   Roteamento: pedidos simples → --model haiku; complexos → sonnet. Manter a conversa (sessão) por 10 min de inatividade.
   Enviar o texto ao tablet conforme chega (streaming) e começar a falar na primeira frase completa.
5. Voz: Kokoro (kokoro-onnx, voz PT-BR configurável) com reserva na voz SAPI "Maria" do Windows.
   Comando "Jarvis, para" interrompe a fala. Baixar os modelos de fontes oficiais com checagem de hash.
6. Mãos: servidor MCP local "painel" (stdio, registrado só na pasta do Jarvis) que reaproveita as ações existentes do
   agente: abrir app da barra de tarefas pelo nome, mídia (play/pause/próxima/anterior), volume +/-/mudo, recorte de tela,
   ler CPU/GPU/RAM e top processos. Ações que alteram o PC devem passar pelo fluxo de permissão já existente
   (Permitir/Negar no tablet). Nunca usar bypass de permissões.
7. Aba Jarvis no tablet (página 3): reator/orbe animado em canvas leve (≤ 15 fps, pausar quando a aba não está visível),
   cor por estado; linha "Você: ..." e "Jarvis: ..." (últimas 3 trocas, rolagem automática); botão grande "Falar"
   (segurar = ouvir enquanto segura; toque = ouvir até a pausa); chave "Wake word" liga/desliga; indicador de modelo
   (Haiku/Sonnet) e de "modo jogo".
8. Instalação: requirements separados (agent/requirements-jarvis.txt), instalados por install_pc.ps1 -Jarvis em
   %USERPROFILE%\PainelPC\libs-jarvis; modelos em %USERPROFILE%\PainelPC\models. Atualizar README (seção Jarvis,
   requisitos, privacidade: áudio processado localmente; só o texto vai para a Anthropic via Claude Code).

## Regras
- Português do Brasil em textos e comentários. Nada de dados pessoais, tokens ou caminhos do usuário no repositório.
- Faça em fases, validando cada uma no PC e no tablet real antes de seguir (screencap do tablet, logs, medições).
- Meça e informe: CPU e RAM do PC com Jarvis desligado, ligado em espera (wake word), ouvindo/respondendo e em jogo.
  Meta: em espera < 2% de um núcleo e sem impacto quando desligado.
- Não faça commit/push sem eu pedir. Ao final, resuma o que foi feito, como testar e as limitações.
```
