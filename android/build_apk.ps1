# Compila o PainelPC.apk sem Gradle (aapt2 + javac + d8 + apksigner).
# Requisitos: Android SDK (build-tools e platforms) e um JDK 17.
# 'Continue': no PowerShell 5.1 avisos em stderr de programas nativos virariam erro fatal.
# Cada etapa confere $LASTEXITCODE.
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sdk  = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA\Android\Sdk" }
$bt   = Get-ChildItem "$sdk\build-tools" -Directory | Sort-Object { [version]($_.Name -replace '[^0-9.]','') } | Select-Object -Last 1 -ExpandProperty FullName
$plat = Get-ChildItem "$sdk\platforms" -Directory | Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
$jar  = "$plat\android.jar"
if (-not $env:JAVA_HOME) {
  $env:JAVA_HOME = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Directory -Filter 'jdk-17*' | Select-Object -First 1 -ExpandProperty FullName
}
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
$out = "$here\build"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force "$out\classes","$out\dex","$out\res" | Out-Null

Write-Host "build-tools: $bt"; Write-Host "platform: $plat"; Write-Host "JAVA_HOME: $env:JAVA_HOME"

# 1. icone + recursos
python "$here\make_icon.py" "$out\res"
& "$bt\aapt2.exe" compile --dir "$out\res" -o "$out\res.zip"
if ($LASTEXITCODE) { throw 'aapt2 compile falhou' }
& "$bt\aapt2.exe" link -o "$out\base.apk" -I $jar --manifest "$here\AndroidManifest.xml" -A "$here\assets" `
    --min-sdk-version 16 --target-sdk-version 22 --version-code 1 --version-name 1.0 "$out\res.zip"
if ($LASTEXITCODE) { throw 'aapt2 link falhou' }

# 2. Java -> .class (bytecode Java 8, compativel com d8 / API 16)
$src = Get-ChildItem "$here\src" -Recurse -Filter *.java | ForEach-Object FullName
& javac --release 8 -nowarn -encoding UTF-8 -classpath $jar -d "$out\classes" @src
if ($LASTEXITCODE) { throw 'javac falhou' }

# 3. .class -> classes.dex
$classes = Get-ChildItem "$out\classes" -Recurse -Filter *.class | ForEach-Object FullName
& "$bt\d8.bat" --release --min-api 16 --lib $jar --output "$out\dex" @classes
if ($LASTEXITCODE) { throw 'd8 falhou' }

# 4. junta o dex no apk
python -I -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'a'); z.write(sys.argv[2],'classes.dex'); z.close()" "$out\base.apk" "$out\dex\classes.dex"

# 5. alinhar e assinar (v1 obrigatoria para Android 4.1)
& "$bt\zipalign.exe" -p -f 4 "$out\base.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'zipalign falhou' }
$ks = "$here\painelpc.keystore"
if (-not (Test-Path $ks)) {
  & keytool -genkeypair -keystore $ks -storepass painelpc -keypass painelpc -alias painelpc -keyalg RSA -keysize 2048 `
      -validity 10000 -dname "CN=Painel PC, O=Local" | Out-Null
}
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:painelpc --key-pass pass:painelpc --min-sdk-version 16 `
    --out "$here\PainelPC.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'apksigner falhou' }
& "$bt\apksigner.bat" verify --min-sdk-version 16 --print-certs "$here\PainelPC.apk" | Select-Object -First 3
Write-Host "OK -> $here\PainelPC.apk ($((Get-Item "$here\PainelPC.apk").Length) bytes)"
