# Tablet antigo

Deixar o aparelho leve e compilar o app Android.

[← voltar ao README](../README.md)

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
