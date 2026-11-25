# Plano v2: 5 palmas, "Oh Jarvis" em português e repositório apresentável

Três frentes independentes. Cada etapa termina com teste no PC/tablet real e um commit (branch `feat/v2`).

---

## A. Abrir o Jarvis com 5 palmas

**Como funciona:** o mesmo fluxo de microfone que já escuta o "Hey Jarvis" passa também por um **detector de palmas**
leve (processamento de sinal, sem IA). Uma palma é um estalo curto, forte e de som "chiado" (energia espalhada nas
frequências altas), muito diferente da fala. Cinco palmas seguidas em ritmo regular disparam o Jarvis.

| Etapa | O que fazer | Como validar |
|---|---|---|
| A0. Medir | Gravar 15 s com você batendo palmas e 15 s de ruído normal (teclado, mouse, fala, jogo) pelo **headset** | Ver se o microfone do headset capta as palmas com força suficiente (microfone de headset é feito para pegar só a boca) |
| A1. Detector | Detecção de "início de som" (energia sobe >12 dB em <10 ms), duração <120 ms, maioria da energia acima de 2 kHz | Palmas gravadas detectadas; teclado e fala ignorados |
| A2. Sequência | 5 palmas com intervalos de 0,15 a 0,8 s, total < 4 s, ritmo parecido entre elas (evita batidas aleatórias) | 5 palmas disparam; 3 ou 4 não; batucar na mesa não |
| A3. Integração | Compartilha o fluxo do microfone com o "Hey Jarvis" (1 só stream); chave própria na aba Jarvis ("Palmas"); pausa no modo jogo | Bipe + escuta do pedido ao bater 5 palmas; custo extra ≈ 0 de CPU |
| A4. Ajuste | Sensibilidade no `config.json` (`clap_threshold`, `claps: 5`) e modo "calibrar" que mostra no tablet cada palma detectada | Você bate palmas e vê o contador no tablet |

**Risco principal:** o microfone do headset pode captar mal as palmas (ele é direcional). Se a A0 mostrar isso, as
alternativas são: aumentar a sensibilidade, usar outro microfone só para as palmas (ex.: a webcam/DroidCam) ou o
**microfone do tablet** (exigiria gravar áudio no app Android 4.1 — possível, mas é mais trabalho).

---

## B. "Oh Jarvis" em português

O modelo atual ("hey jarvis") foi treinado com pronúncia em inglês. Há dois caminhos:

### B1. Recomendado primeiro: escuta por transcrição (sem treinar nada)
1. Um detector de voz pequeno (**Silero VAD**, ~2 MB, ~1% de um núcleo) fica atento a **falas curtas** (até ~2 s).
2. Só quando aparece uma fala curta, o **Whisper tiny** (~75 MB) transcreve em ~0,3 s.
3. Se o texto bater com `oh/ó/ô/ei/hey + jarvis` (com variações comuns de transcrição: "jarvis", "jarves", "járvis"),
   o Jarvis dispara. Como compara **texto**, quase não dá alarme falso.
4. Convive com o "Hey Jarvis" atual (os dois ligados).

| Etapa | Validação |
|---|---|
| B1.1 VAD + filtro de falas curtas | medir CPU em silêncio e com música/vídeo tocando |
| B1.2 Whisper tiny + regra de texto | 20 gravações suas dizendo "Oh Jarvis" (≥ 18 acertos) e 20 frases comuns (0 disparos) |
| B1.3 Integração (chave "Oh Jarvis" na aba) | tempo da fala até o bipe < 1,2 s |

**Custo esperado:** quase zero em silêncio; picos curtos só quando há fala. Com você falando muito (call no Discord
fora de jogo), o Whisper tiny roda mais vezes — por isso a regra só aceita falas curtas e o modo jogo continua pausando.

### B2. Se B1 não ficar bom: treinar um modelo próprio "oh jarvis"
- Usa o processo oficial de treino do openWakeWord (notebook no Google Colab, GPU gratuita, ~1–2 h).
- Gera milhares de exemplos sintéticos da frase com vozes PT-BR + **gravações suas** (≈ 30–50 repetições) para ajustar.
- Resultado: um arquivo `oh_jarvis.onnx` (~1 MB) que roda igual ao "Hey Jarvis" atual (~2% de um núcleo, resposta instantânea).
- Exige sua participação (gravar as repetições e rodar o notebook). Fica como plano B.

---

## C. Repositório apresentável

| Etapa | Conteúdo |
|---|---|
| C1. Modo demonstração | `--demo` no agente: dados fictícios (apps genéricos, música de exemplo, uso de Claude simulado) para tirar **prints sem nenhum dado seu** |
| C2. Imagens | Prints das 4 abas + uma montagem (tablet na mesa) e um **GIF curto** do Jarvis respondendo; imagem de "social preview" do GitHub |
| C3. README novo | Topo com imagem e uma frase do que é; "Funciona em tablets de 2012"; seções curtas (Recursos, Instalação em 3 passos, Jarvis, Personalizar, FAQ); detalhes técnicos movidos para `docs/` |
| C4. Documentação | `docs/arquitetura.md` (diagrama), `docs/jarvis.md`, `docs/tablet-antigo.md` (enxugar, Android 4.1), `docs/solucao-de-problemas.md` |
| C5. Licença | **Decisão sua** — recomendado **MIT** (permite usar e modificar, mantendo seu crédito) |
| C6. Release v1.0 | GitHub Release com o `PainelPC.apk`, o `.zip` do projeto e notas da versão (`CHANGELOG.md`) |
| C7. Detalhes | Descrição e tópicos do repositório (android, stream-deck, jarvis, claude-code, windows), modelos de issue, apagar o branch já mesclado |

**Sobre o nome:** "Steam Deck" é marca registrada da Valve. O README já avisa que não há relação, mas, se o projeto
ganhar visibilidade, vale considerar um nome próprio (ex.: "DeskDeck", "PainelPC", "MesaDeck"). Decisão sua.

---

## Ordem sugerida
1. **C1–C3** (rápido, repositório já fica bonito) · 2. **A0** (medir se o headset ouve palmas) · 3. **B1** ·
4. **A1–A4** · 5. **C4–C7** · 6. **B2** só se precisar.

## Decisões que preciso de você
1. **Licença:** MIT (recomendado) ou outra?
2. **Palmas:** posso pedir que você bata palmas durante a medição (A0)? Sem isso não dá para calibrar.
3. **Nome do projeto:** mantém "SteamDeck" ou troca?
4. **Prints:** ok usar o modo demonstração (dados fictícios) em vez dos seus dados reais?
