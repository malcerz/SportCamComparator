import subprocess
import os
import time

app_dir = r"C:\Program Files\WindowsApps\Malcerz.SportCamComparator_1.0.0.0_x64__qd1bkbsbzd9mc"
exporter = os.path.join(app_dir, "bin", "KomparatorGpuExporter.exe")
ffprobe = os.path.join(app_dir, "bin", "ffprobe.exe")

config = "tests/artifacts/export_4k_test.json"
print(f"Running exporter from: {exporter}")

t0 = time.time()
p = subprocess.run([exporter, "--config", config], capture_output=True, text=True)
t1 = time.time()

print("--- EXPORTER OUTPUT ---")
print(p.stderr[-1000:])
print("-----------------------")

if p.returncode == 0:
    print(f"Export successful in {t1-t0:.2f}s")
    out_mp4 = "tests/artifacts/export_output.mp4"
    probe = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", out_mp4], capture_output=True, text=True)
    print("--- FFPROBE OUTPUT ---")
    print(probe.stdout[:1000])
else:
    print(f"Export failed with code {p.returncode}")
