[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [ValidateSet("Dev", "Store")]
    [string]$Configuration = "Dev"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Set-Location $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SportCamComparator - MSIX Package Builder ($Configuration)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Sprawdzić narzędzia
if (-not (Get-Command "makeappx.exe" -ErrorAction SilentlyContinue)) { throw "makeappx.exe not found" }
if (-not (Get-Command "signtool.exe" -ErrorAction SilentlyContinue)) { throw "signtool.exe not found" }
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) { throw "python not found" }

# 2. Sprawdzić wymagane zależności
if (-not (Test-Path "third_party\ffmpeg\bin\ffmpeg.exe")) { throw "FFmpeg missing in third_party" }

if (-not $SkipBuild) {
    # 3. Zbudować natywnego helpera
    Write-Host "Building C++ helpers..."
    .\build_gpu_exporter.ps1 -Configuration Release -Clean
    .\build_gpu_exporter_nvidia_compat.ps1 -Configuration Release -Clean

    # 4. Skompilować aplikację przez Nuitkę
    # 5. Skopiować wymagany runtime
    Write-Host "Building Python app with Nuitka..."
    .\packaging\windows\build_nuitka.ps1
}

$DistDir = "dist\SportCamComparator"

# Manually copy bin directory because Nuitka ignores .exe and .dll in data dirs
if (-not (Test-Path "$DistDir\bin")) { New-Item -ItemType Directory -Path "$DistDir\bin" | Out-Null }
Copy-Item -Path "bin\*" -Destination "$DistDir\bin\" -Recurse -Force
Remove-Item -Path "$DistDir\bin\*.json" -ErrorAction SilentlyContinue
Remove-Item -Path "$DistDir\bin\*.png" -ErrorAction SilentlyContinue
Remove-Item -Path "$DistDir\bin\ffplay.exe" -ErrorAction SilentlyContinue

# Also copy preview_video.qml to dist root because __file__ resolves to dist root
Copy-Item -Path "src\preview_video.qml" -Destination "$DistDir\" -Force
if (Test-Path "LICENSE.txt") {
    Copy-Item -Path "LICENSE.txt" -Destination "$DistDir\" -Force
}

Write-Host "Overwriting Qt FFmpeg DLLs with Full versions to prevent MSIX DLL shadowing..."
Copy-Item -Path "third_party\ffmpeg\bin\*.dll" -Destination "$DistDir\" -Force


# 6. Sprawdzić kompletność plików
if (-not (Test-Path "$DistDir\SportCamComparator.exe")) { throw "SportCamComparator.exe not found in dist" }
if (-not (Test-Path "$DistDir\bin\KomparatorGpuExporter.exe")) { throw "KomparatorGpuExporter missing in dist" }
if (-not (Test-Path "$DistDir\bin\ffmpeg.exe")) { throw "ffmpeg missing in dist" }

# 7. Przygotować manifest i zasoby
Write-Host "Preparing MSIX layout..."
$MsixLayout = "dist\msix_layout"
if (Test-Path $MsixLayout) { Remove-Item -Recurse -Force $MsixLayout }
New-Item -ItemType Directory -Path $MsixLayout | Out-Null

Copy-Item -Path "$DistDir\*" -Destination $MsixLayout -Recurse -Force
Copy-Item -Path "packaging\windows\msix\AppxManifest.xml" -Destination $MsixLayout -Force
Copy-Item -Path "packaging\windows\msix\Assets" -Destination $MsixLayout -Recurse -Force

# 8. Utworzyć pakiet MSIX
$Version = "1.0.0.0"
$MsixSuffix = if ($Configuration -eq "Store") { "_Store" } else { "_Dev" }
$MsixFile = "dist\store\SportCamComparator_${Version}_x64${MsixSuffix}.msix"
if (-not (Test-Path "dist\store")) { New-Item -ItemType Directory -Path "dist\store" | Out-Null }
if (Test-Path $MsixFile) { Remove-Item -Force $MsixFile }

Write-Host "Creating MSIX package..."
& makeappx.exe pack /d $MsixLayout /p $MsixFile /o
if ($LASTEXITCODE -ne 0) { throw "MakeAppx failed" }

# 9. Podpisywanie
if ($Configuration -eq "Dev") {
    Write-Host "Signing MSIX package with dev cert..."
    $Publisher = "CN=E2A524DB-9E81-4D08-A86B-40EA6B42DED4"
    $Cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $Publisher } | Select-Object -First 1
    if (-not $Cert) {
        Write-Host "Generating Dev Certificate..."
        $Cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher -KeyUsage DigitalSignature -FriendlyName "SportCamComparator Dev" -CertStoreLocation "Cert:\CurrentUser\My" -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
    }
    & signtool.exe sign /sha1 $($Cert.Thumbprint) /fd SHA256 /a $MsixFile
    if ($LASTEXITCODE -ne 0) { throw "SignTool failed" }
} else {
    Write-Host "Skipping local signing for Store configuration."
}

Write-Host "Running pytest verification..."
python -m pytest tests/
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

$Hash = Get-FileHash $MsixFile -Algorithm SHA256
$SizeMB = [math]::Round((Get-Item $MsixFile).Length / 1MB, 2)

# 10. Wypisać ścieżkę do gotowego pliku
Write-Host "==================================================" -ForegroundColor Green
if ($Configuration -eq "Dev") {
    Write-Host " SUCCESS! MSIX created and signed. " -ForegroundColor Green
} else {
    Write-Host " SUCCESS! MSIX created for Store (Unsigned). " -ForegroundColor Green
}
Write-Host " Package: $(Resolve-Path $MsixFile)" -ForegroundColor Yellow
Write-Host " Size:    $SizeMB MB" -ForegroundColor Yellow
Write-Host " SHA-256: $($Hash.Hash)" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Green
