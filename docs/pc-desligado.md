# Ligar o PC com palmas (PC desligado)

Com o PC desligado mas na tomada, o **tablet** escuta as palmas pelo próprio microfone. Com **5 palmas**, ele
pergunta com a voz do Jarvis: *"Você quer ligar o computador? Não responda nada caso não queira."*
Se você **falar qualquer coisa** nos 6 segundos seguintes, ele liga o PC pela rede (Wake-on-LAN). Se ficar em silêncio,
ele não liga.

[← voltar ao README](../README.md)

## Como funciona
* O agente manda ao tablet, a cada conexão, o endereço da placa de rede do PC (MAC e broadcast da rede).
  O tablet guarda esses dados.
* Sem o PC por mais de 20 s, o tablet mostra **"PC desligado"** e abre o microfone. Com o PC ligado, o microfone
  do tablet fica fechado: as palmas passam a ser ouvidas pelo PC, na aba Jarvis.
* O detector de palmas é o mesmo do PC (`agent/palmas.py`, portado para `android/.../Palmas.java`).
  No microfone do tablet, as palmas chegam a −3 a −7 dB, bem acima do ruído (−31 a −40 dB).
* O tablet **não entende palavras**: ele não roda reconhecimento de voz sem internet. Qualquer fala depois da
  pergunta conta como "sim".
* As falas vêm prontas no APK (`android/assets/voz/`), com a mesma voz e o mesmo efeito do Jarvis.
  Se você trocar a voz, rode `python agent/gerar_falas_tablet.py` e recompile o APK.
* A tela "PC desligado" também tem um botão **Ligar PC**, que liga direto, sem perguntar.

## O que precisa estar pronto (uma vez)
1. **PC no cabo de rede** com Wake-on-LAN ligado no driver (no Gerenciador de Dispositivos → placa de rede →
   Avançado: "Pacote Wake on Magic" = Ativado).
2. **BIOS** (ex.: Gigabyte): **ErP = Disabled** e **Wake on LAN** (ou "Resume by PCI-E") = **Enabled**.
   O ErP desativado também mantém a energia das portas USB com o PC desligado.
3. **Tablet com energia** com o PC desligado: confira se ele continua carregando pelo cabo. Se não, use um
   carregador de tomada.
4. **Tablet no Wi-Fi da mesma rede do PC**:
   ```powershell
   .\tablet\enxugar_tablet.ps1 -ConectarWifi   # abre a tela do Wi-Fi: escolha a rede e digite a senha no tablet
   .\tablet\enxugar_tablet.ps1 -WifiPronto     # desativa de novo Configurações e teclado (o Wi-Fi fica ligado)
   ```

## Ajustes (pelo adb)
```powershell
adb shell am start -n br.local.painelpc/.MainActivity --ez claps false        # desliga a escuta com o PC desligado
adb shell am start -n br.local.painelpc/.MainActivity --ef clap_level -40     # palmas mais fracas também contam
adb shell am start -n br.local.painelpc/.MainActivity --ez guard_test true    # teste: escuta mesmo com o PC ligado
adb logcat -s PainelVigia                                                     # ver o nível do microfone e cada estalo
```
