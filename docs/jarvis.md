# Jarvis: assistente de voz

Tudo sobre a 4ª aba: o que ele faz, como instalar, opções e consumo.

[← voltar ao README](../README.md)


A 4ª aba do tablet é o **Jarvis**: um reator animado que mostra o estado (em espera, ouvindo, pensando, falando),
a conversa e um botão grande **Falar/Parar**. O plano de implantação está em [PLANO-JARVIS.md](PLANO-JARVIS.md).

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
