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
| 5. Chamar sem tocar e modo jogo | ✅ bata **5 palmas** e ele responde com um bipe; com um jogo ou vídeo em tela cheia, a escuta pausa sozinha e os modelos de voz saem da memória |
| 6. Acabamento | ✅ o botão **Parar** interrompe a fala; "para", "chega" ou "obrigado" encerram sem gastar o plano; histórico das últimas conversas salvo no PC |

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

* **5 palmas**: ligue na chave "5 PALMAS" da aba Jarvis (fica salvo). Funciona com a aba Jarvis aberta no tablet. Enquanto você bate, o tablet mostra "palmas: 3 de 5".
  A escuta não usa IA: um estalo só conta se o volume subir de uma vez, cair em menos de 40 ms e tiver som de "chiado".
  Assim, assobio, fala e teclado não contam. Gasta ~0,15% de um núcleo e ~35 MB; em **modo jogo** pausa sozinha.
  O botão Falar funciona sempre.
* O Jarvis roda num processo separado que **só existe com a aba Jarvis aberta**: abre ao entrar na aba e fecha 5 s depois
  de sair dela. Se você trocar de aba no meio de uma resposta, ele termina de falar e então fecha. Nas outras abas, gasta zero.
  Com os modelos carregados, ocupa ~750 MB, e eles saem da memória depois de 5 min sem uso.
* O áudio é processado **no PC**: nada de voz sai do computador. Só o **texto** do pedido vai para o Claude Code.
* Opções em `config.json`, bloco `"jarvis"`:

```json
"jarvis": { "mic": "AB13X", "voice": "pm_alex", "voice_fx": 0.5, "speed": 1.05, "game_mode": true, "model": "",
            "claps": 5, "clap_rise": 25, "clap_level": -36, "clap_decay": 10, "clap_flat": 0.01 }
```

  `mic` é parte do nome do microfone; se ficar vazio, ele usa o padrão do Windows, ou o headset se o padrão for virtual (DroidCam etc.).
  `voice` aceita `pm_alex` (padrão) ou `pm_santa` (masculinas) e `pf_dora` (feminina).
  `voice_fx`: efeito de "voz de IA" (sala curta + toque eletrônico): `0` desliga, `0.5` é o padrão, `1` fica bem robótico.
  `game_mode`: pausar a escuta com app em tela cheia (padrão `true`).
  `model`: fixa o modelo (`haiku` ou `sonnet`); vazio = escolhe pelo pedido.
  `claps`: quantas palmas abrem o Jarvis (padrão 5). Se algo ainda disparar por engano, aumente `clap_decay`
  (queda mínima em 40 ms, em dB) ou `clap_flat` (quanto "chiado" o som precisa ter); se suas palmas não
  forem reconhecidas, diminua `clap_rise` ou `clap_level`.

**Arquivos locais do Jarvis** (em `%USERPROFILE%\PainelPC\data`): `jarvis.log` (diagnóstico),
`jarvis_historico.json` (últimas 20 conversas, só no seu PC) e `jarvis_state.json` (se as palmas estão ligadas).
A personalidade fica em `agent/jarvis_persona.md`; a pasta de trabalho do Claude Code do Jarvis é `%USERPROFILE%\Jarvis`.

**Consumo medido** (Ryzen 5 5600G): ~90 MB de RAM no total com a aba Jarvis aberta escutando as palmas; nas outras abas, só o painel (~55 MB). Durante uma conversa, os modelos de voz ocupam ~750 MB e saem da memória após 5 min parados
ou na hora em que um jogo entra em tela cheia.
