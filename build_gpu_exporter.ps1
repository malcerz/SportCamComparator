# Build script for Komparator GPU Exporter (Windows D3D11 Zero-Copy)
[CmdletBinding()]
param(
    [string]$Configuration = "Release",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Building KomparatorGpuExporter ($Configuration) " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Check/Setup third_party/ffmpeg
$ThirdPartyFfmpeg = Join-Path $ScriptDir "third_party\ffmpeg"
if (-not (Test-Path (Join-Path $ThirdPartyFfmpeg "include\libavcodec\avcodec.h"))) {
    $KnownFfmpeg = "D:\BikeRideHUD-main\third_party\ffmpeg-9.0.1-full_build-shared"
    if (Test-Path (Join-Path $KnownFfmpeg "include\libavcodec\avcodec.h")) {
        Write-Host "Creating junction to existing FFmpeg shared build: $KnownFfmpeg" -ForegroundColor Yellow
        New-Item -ItemType Directory -Path (Join-Path $ScriptDir "third_party") -Force | Out-Null
        cmd.exe /c "mklink /J `"$ThirdPartyFfmpeg`" `"$KnownFfmpeg`"" | Out-Null
    } else {
        Write-Error "FFmpeg development files not found at $ThirdPartyFfmpeg and $KnownFfmpeg."
    }
}

# 2. Setup Toolchain in PATH and locate CMake and Ninja
$ToolchainBin = "C:\_DEV\BikeRideHUD\.toolchain\msys64\msys64\ucrt64\bin"
if (Test-Path $ToolchainBin) {
    $env:PATH = "$ToolchainBin;$env:PATH"
}

$CMakeExe = (Get-Command cmake -ErrorAction SilentlyContinue).Source
if (-not $CMakeExe -and (Test-Path "C:\tools\mingw64\bin\cmake.exe")) {
    $CMakeExe = "C:\tools\mingw64\bin\cmake.exe"
}
if (-not $CMakeExe) {
    Write-Error "CMake not found in PATH or C:\tools\mingw64\bin."
}

$NinjaExe = (Get-Command ninja -ErrorAction SilentlyContinue).Source
if (-not $NinjaExe -and (Test-Path "C:\tools\mingw64\bin\ninja.exe")) {
    $NinjaExe = "C:\tools\mingw64\bin\ninja.exe"
}
if (-not $NinjaExe -and (Test-Path (Join-Path $ToolchainBin "ninja.exe"))) {
    $NinjaExe = Join-Path $ToolchainBin "ninja.exe"
}

# 3. Locate Compiler (MSVC or UCRT64 / MinGW)

$VcVars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $VcVars)) {
    $VcVars = (Get-ChildItem -Path "C:\Program Files*", "D:\Program Files*" -Filter "vcvars64.bat" -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
}

$UseMsvc = [bool]$VcVars
$GccExe = (Get-Command g++.exe -ErrorAction SilentlyContinue).Source
if (-not $UseMsvc -and -not $GccExe) {
    Write-Error "Neither MSVC (vcvars64.bat) nor GCC (g++.exe) found."
}

# 4. Prepare build directory
$BuildDir = Join-Path $ScriptDir "build"
if ($Clean -and (Test-Path $BuildDir)) {
    Write-Host "Cleaning build directory..." -ForegroundColor Yellow
    $ResolvedBuild = [IO.Path]::GetFullPath($BuildDir)
    if ($ResolvedBuild -ne [IO.Path]::GetFullPath((Join-Path $ScriptDir "build"))) {
        throw "Unsafe build path"
    }
    Remove-Item -LiteralPath $ResolvedBuild -Recurse -Force
}
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ScriptDir "bin") -Force | Out-Null

# 5. Run CMake Configure and Build
if ($UseMsvc) {
    $Generator = if ($NinjaExe) { "Ninja" } else { "Visual Studio 17 2022" }
    Write-Host "Configuring CMake with MSVC generator: $Generator" -ForegroundColor Green
    $NinjaArg = if ($NinjaExe) { "-DCMAKE_MAKE_PROGRAM=`"$NinjaExe`"" } else { "" }
    $BuildCmd = @"
call "$VcVars"
cd /d "$BuildDir"
"$CMakeExe" -G "$Generator" $NinjaArg -DCMAKE_BUILD_TYPE=$Configuration "$ScriptDir"
if errorlevel 1 exit /b 1
"$CMakeExe" --build . --config $Configuration
if errorlevel 1 exit /b 1
"@
    $TempBat = Join-Path $env:TEMP "build_komparator_gpu_exporter.bat"
    Set-Content -Path $TempBat -Value $BuildCmd -Encoding ASCII
    try {
        & cmd.exe /c $TempBat
        if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
    } finally {
        Remove-Item -Force $TempBat -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "Configuring CMake with GCC/Ninja ($GccExe)..." -ForegroundColor Green
    & $CMakeExe -B $BuildDir -G Ninja -DCMAKE_CXX_COMPILER="$GccExe" -DCMAKE_MAKE_PROGRAM="$NinjaExe" "-DCMAKE_BUILD_TYPE=$Configuration" $ScriptDir
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }
    & $CMakeExe --build $BuildDir --config $Configuration
    if ($LASTEXITCODE -ne 0) { throw "CMake build failed" }

    # Copy UCRT64 runtime DLLs to bin
    if (Test-Path $ToolchainBin) {
        Copy-Item (Join-Path $ToolchainBin "libstdc++-6.dll") (Join-Path $ScriptDir "bin") -Force -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $ToolchainBin "libgcc_s_seh-1.dll") (Join-Path $ScriptDir "bin") -Force -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $ToolchainBin "libwinpthread-1.dll") (Join-Path $ScriptDir "bin") -Force -ErrorAction SilentlyContinue
    }
}

$ExePath = Join-Path $ScriptDir "bin\KomparatorGpuExporter.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "Build completed but $ExePath not found."
}

Write-Host "==================================================" -ForegroundColor Green
Write-Host " SUCCESS! Built: $ExePath" -ForegroundColor Green
Write-Host " Running capability probe test..." -ForegroundColor Cyan
& $ExePath --probe | Out-Null
$global:LASTEXITCODE = 0
Write-Host "==================================================" -ForegroundColor Green
exit 0
