@echo off
set PROJECT_DIR=D:\GoPro\SportCamComparator
set OUT_DIR=%LOCALAPPDATA%\Packages\Malcerz.SportCamComparator_qd1bkbsbzd9mc\LocalState
bin\KomparatorGpuExporter.exe --config "%PROJECT_DIR%\tests\artifacts\export_4k_test.json" > "%OUT_DIR%\export_log.txt" 2>&1
echo EXIT_CODE=%ERRORLEVEL% >> "%OUT_DIR%\export_log.txt"
bin\ffprobe.exe -v error -show_format -show_streams "%PROJECT_DIR%\tests\artifacts\export_output.mp4" > "%OUT_DIR%\probe_log.txt" 2>&1
