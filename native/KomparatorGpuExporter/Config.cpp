#include "Config.h"
#include "../third_party/json.hpp"
#include <fstream>
#include <sstream>

using json = nlohmann::json;

static void ParseTelemetryEvents(const json& value, TelemetryData& data) {
    if (!value.is_object()) throw std::runtime_error("Telemetry must be compact object, not frame events");
    data.camera = value.value("camera", "");
    data.start_datetime = value.value("start_datetime", "");
    if (value.contains("samples")) for (const auto& row : value["samples"]) {
        TelemetrySample sample;
        sample.timestamp = row.at(0).get<double>();
        if (!row.at(1).is_null()) sample.iso = row.at(1).get<int>();
        if (!row.at(2).is_null()) sample.exposure = row.at(2).get<double>();
        if (!data.samples.empty() && sample.timestamp < data.samples.back().timestamp)
            throw std::runtime_error("Telemetry samples must be sorted");
        data.samples.push_back(sample);
    }
}

bool ExportConfig::LoadFromString(const std::string& jsonStr, ExportConfig& outConfig, std::string& outError) {
    try {
        json j = json::parse(jsonStr);
        if (j.contains("video1") && j["video1"].is_string()) outConfig.video1 = j["video1"].get<std::string>();
        if (j.contains("video2") && j["video2"].is_string()) outConfig.video2 = j["video2"].get<std::string>();
        if (j.contains("output") && j["output"].is_string()) outConfig.output = j["output"].get<std::string>();
        if (j.contains("layout") && j["layout"].is_string()) outConfig.layout = j["layout"].get<std::string>();
        if (j.contains("offset_seconds") && j["offset_seconds"].is_number()) outConfig.offset_seconds = j["offset_seconds"].get<double>();
        if (j.contains("width") && j["width"].is_number_integer()) outConfig.width = j["width"].get<int>();
        if (j.contains("height") && j["height"].is_number_integer()) outConfig.height = j["height"].get<int>();
        if (j.contains("fps") && j["fps"].is_number()) outConfig.fps = j["fps"].get<double>();
        if (j.contains("encoder") && j["encoder"].is_string()) outConfig.encoder = j["encoder"].get<std::string>();
        outConfig.codec = "hevc";
        if (j.contains("encoder_preset") && j["encoder_preset"].is_string()) {
            outConfig.encoder_preset = j["encoder_preset"].get<std::string>();
        } else if (j.contains("preset") && j["preset"].is_string()) {
            outConfig.encoder_preset = j["preset"].get<std::string>();
        }
        if (j.contains("bitrate") && j["bitrate"].is_number()) outConfig.bitrate = j["bitrate"].get<int64_t>();
        if (j.contains("audio") && j["audio"].is_string()) outConfig.audio = j["audio"].get<std::string>();
        if (j.contains("show_overlay") && j["show_overlay"].is_boolean()) outConfig.show_overlay = j["show_overlay"].get<bool>();
        if (j.contains("overlay_font_scale") && j["overlay_font_scale"].is_number()) outConfig.overlay_font_scale = j["overlay_font_scale"].get<float>();
        if (j.contains("overlay_opacity") && j["overlay_opacity"].is_number()) outConfig.overlay_opacity = j["overlay_opacity"].get<float>();
        if (j.contains("pad_to_4k") && j["pad_to_4k"].is_boolean()) outConfig.pad_to_4k = j["pad_to_4k"].get<bool>();
        if (j.contains("debug_gpu_copies") && j["debug_gpu_copies"].is_boolean()) outConfig.debug_gpu_copies = j["debug_gpu_copies"].get<bool>();
        if (j.contains("input_rotation1") && j["input_rotation1"].is_number_integer()) outConfig.input_rotation1 = j["input_rotation1"].get<int>();
        if (j.contains("input_rotation2") && j["input_rotation2"].is_number_integer()) outConfig.input_rotation2 = j["input_rotation2"].get<int>();

        if (j.contains("telemetry1")) ParseTelemetryEvents(j["telemetry1"], outConfig.telemetry1);
        if (j.contains("telemetry2")) ParseTelemetryEvents(j["telemetry2"], outConfig.telemetry2);

        outConfig.export_preview = j.value("export_preview", true);
        outConfig.preview_pipe = j.value("preview_pipe", "");
        outConfig.preview_width = j.value("preview_width", 640);
        outConfig.preview_height = j.value("preview_height", 360);
        outConfig.preview_fps = j.value("preview_fps", 5.0);
        if (outConfig.preview_width < 2 || outConfig.preview_width > 1600 ||
            outConfig.preview_height < 2 || outConfig.preview_height > 900 ||
            outConfig.preview_fps <= 0 || outConfig.preview_fps > 5.0)
            throw std::runtime_error("Invalid preview dimensions or sampling rate");
        outConfig.diagnostic_preview_failure = j.value("diagnostic_preview_failure", false);
        outConfig.duration_limit_seconds = j.value("duration_limit_seconds", 0.0);
        outConfig.diagnostic_fail_frame = j.value("diagnostic_fail_frame", -1);
        outConfig.diagnostic_overlay_count = j.value("diagnostic_overlay_count", -1);
        if (outConfig.diagnostic_overlay_count < -1 || outConfig.diagnostic_overlay_count > 2)
            throw std::runtime_error("diagnostic_overlay_count must be -1, 0, 1 or 2");
        if (outConfig.video1.empty() || outConfig.video2.empty() || outConfig.output.empty())
            throw std::runtime_error("video1, video2 and output are required");
        if (outConfig.width <= 0 || outConfig.height <= 0 || outConfig.width % 2 || outConfig.height % 2)
            throw std::runtime_error("Output dimensions must be positive and even");
        if (outConfig.audio != "mute" && outConfig.audio != "left" && outConfig.audio != "right" && outConfig.audio != "both")
            throw std::runtime_error("Invalid audio mode");
        return true;
    } catch (const std::exception& e) {
        outError = e.what();
        return false;
    }
}

bool ExportConfig::LoadFromFile(const std::string& path, ExportConfig& outConfig, std::string& outError) {
    std::ifstream file(path);
    if (!file.is_open()) {
        outError = "Cannot open config file: " + path;
        return false;
    }
    std::stringstream buffer;
    buffer << file.rdbuf();
    return LoadFromString(buffer.str(), outConfig, outError);
}
