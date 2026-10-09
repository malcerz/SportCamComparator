#pragma once

#include <string>
#include <vector>
#include <cstdint>

struct TelemetrySample {
    double timestamp = 0;
    int iso = -1;
    double exposure = 0;
};
struct TelemetryData {
    std::string camera, start_datetime;
    std::vector<TelemetrySample> samples;
};

struct ExportConfig {
    std::string video1;
    std::string video2;
    std::string output;
    std::string layout = "left_right"; // "left_right" or "top_bottom"
    double offset_seconds = 0.0;       // Positive = video2 delayed, Negative = video1 delayed
    int width = 3840;
    int height = 2160;
    double fps = 0;
    double duration_limit_seconds = 0;
    int diagnostic_fail_frame = -1;
    // Developer-only isolation switch: -1 follows show_overlay, 0 disables,
    // 1 enables only the first BGRA telemetry stream, 2 enables both.
    int diagnostic_overlay_count = -1;
    std::string encoder = "auto";      // "nvenc", "amf", "qsv", "auto"
    std::string codec = "hevc";        // "hevc" (forced HEVC)
    std::string encoder_preset = "balanced"; // "speed", "balanced", "quality"
    int64_t bitrate = 20000000;        // in bits per second
    std::string audio = "left";        // "mute", "left", "right", "both"
    bool show_overlay = true;
    float overlay_font_scale = 1.0f;
    float overlay_opacity = 1.0f;
    bool pad_to_4k = false;
    bool debug_gpu_copies = false;
    // Explicit Python/FFprobe orientation decision. -1 keeps decoder metadata.
    int input_rotation1 = -1;
    int input_rotation2 = -1;

    bool export_preview = true;
    std::string preview_pipe;
    int preview_width = 640;
    int preview_height = 360;
    double preview_fps = 5.0;
    bool diagnostic_preview_failure = false;

    TelemetryData telemetry1;
    TelemetryData telemetry2;

    static bool LoadFromFile(const std::string& path, ExportConfig& outConfig, std::string& outError);
    static bool LoadFromString(const std::string& jsonStr, ExportConfig& outConfig, std::string& outError);
};
