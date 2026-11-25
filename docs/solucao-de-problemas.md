# Solução de problemas

Sintomas comuns e limitações conhecidas.

[← voltar ao README](../README.md)

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
