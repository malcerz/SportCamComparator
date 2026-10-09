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

# 1. Check FFmpeg development files. Set FFMPEG_DIR to a shared FFmpeg
# development package containing include, lib, and (optionally) bin folders.
$ThirdPartyFfmpeg = Join-Path $ScriptDir "third_party\ffmpeg"
$FfmpegRoot = if ($env:FFMPEG_DIR) { $env:FFMPEG_DIR } else { $ThirdPartyFfmpeg }
if (-not (Test-Path (Join-Path $FfmpegRoot "include\libavcodec\avcodec.h"))) {
    throw "FFmpeg development headers not found under '$FfmpegRoot'. Set FFMPEG_DIR to a shared FFmpeg development package."
}

# 2. Setup Toolchain in PATH and locate CMake and Ninja
$ToolchainBin = $null

$CMakeExe = (Get-Command cmake -ErrorAction SilentlyContinue).Source
if (-not $CMakeExe) {
    throw "CMake not found. Install CMake and add it to PATH."
}

$NinjaExe = (Get-Command ninja -ErrorAction SilentlyContinue).Source

# 3. Locate Compiler (MSVC or UCRT64 / MinGW)

$VcVars = $null
$VsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $VsWhere) {
    $VsInstall = & $VsWhere -latest -products * -property installationPath
    if ($VsInstall) {
        $Candidate = Join-Path $VsInstall "VC\Auxiliary\Build\vcvars64.bat"
        if (Test-Path $Candidate) { $VcVars = $Candidate }
    }
}
$KnownVcVars = Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if (-not $VcVars -and (Test-Path $KnownVcVars)) { $VcVars = $KnownVcVars }

$UseMsvc = [bool]$VcVars
$GccExe = (Get-Command g++.exe -ErrorAction SilentlyContinue).Source
$GccBin = if ($GccExe) { Split-Path -Parent $GccExe } else { $null }
if (-not $UseMsvc -and -not $GccExe) {
    throw "Neither Visual Studio C++ Build Tools nor g++.exe was found."
}
if (-not $UseMsvc -and -not $NinjaExe) {
    throw "Ninja is required when building with GCC. Install it and add it to PATH."
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
"$CMakeExe" -G "$Generator" $NinjaArg -DFFMPEG_ROOT_SEARCH=`"$FfmpegRoot`" -DCMAKE_BUILD_TYPE=$Configuration "$ScriptDir"
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
    if ($GccBin) {
        Copy-Item (Join-Path $GccBin "libstdc++-6.dll") (Join-Path $ScriptDir "bin") -Force -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $GccBin "libgcc_s_seh-1.dll") (Join-Path $ScriptDir "bin") -Force -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $GccBin "libwinpthread-1.dll") (Join-Path $ScriptDir "bin") -Force -ErrorAction SilentlyContinue
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
