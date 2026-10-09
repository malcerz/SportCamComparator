#include "Config.h"
#include "ExportPipeline.h"
#include "TelemetryRenderer.h"
#include <iostream>
#include <thread>
#include <memory>
#include <string>
#include "../third_party/json.hpp"

int main(int argc, char* argv[]) {
    // Disable stdio synchronization for fast throughput
    std::ios_base::sync_with_stdio(false);
    std::cin.tie(NULL);

    std::string configPath;
    std::string jsonStr;
    bool debugCopies = false;
    bool probeMode = false;
    bool testOverlayMode = false;
    std::string probeEncoder = "auto", probeCodec = "hevc", probePreset = "balanced";
    int probeWidth = 3840, probeHeight = 2160;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--encoder" && i+1 < argc) probeEncoder = argv[++i];
        else if (arg == "--codec" && i+1 < argc) probeCodec = argv[++i];
        else if (arg == "--preset" && i+1 < argc) probePreset = argv[++i];
        else if (arg == "--width" && i+1 < argc) probeWidth = std::atoi(argv[++i]);
        else if (arg == "--height" && i+1 < argc) probeHeight = std::atoi(argv[++i]);
        else if (arg == "--config" && i + 1 < argc) {
            configPath = argv[++i];
        } else if (arg == "--json" && i + 1 < argc) {
            jsonStr = argv[++i];
        } else if (arg == "--debug-gpu-copies") {
            debugCopies = true;
        } else if (arg == "--probe") {
            probeMode = true;
        } else if (arg == "--test-overlay") {
            testOverlayMode = true;
        }
    }

    if (testOverlayMode) {
        D3D11Context ctx;
        if (!ctx.Initialize("auto", false)) {
            std::cout << nlohmann::json({{"status","error"},{"reason","D3D11_DEVICE_INIT_FAILED"}}).dump() << std::endl;
            return 1;
        }
        TelemetryRenderer renderer(ctx, 1);
        if (!renderer.Initialize(700, 240, 24.0f)) {
            std::cout << nlohmann::json({{"status","error"},{"reason","OVERLAY_INIT_FAILED"}}).dump() << std::endl;
            return 1;
        }
        std::string sample = "DJI Osmo Action 6\n2026-10-05 06:38:47\nTIME : 585.362s\nISO  : 3200\nEXP  : 1/100";
        if (!renderer.UpdateText(sample, nullptr)) {
            std::cout << nlohmann::json({{"status","error"},{"reason","OVERLAY_RENDER_FAILED"}}).dump() << std::endl;
            return 1;
        }
        const uint32_t* p = reinterpret_cast<const uint32_t*>(renderer.GetPixelData());
        int total = renderer.GetWidth() * renderer.GetHeight();
        int transparentCount = 0, outlineCount = 0, whiteCount = 0;
        for (int i = 0; i < total; ++i) {
            uint32_t val = p[i];
            uint8_t a = (val >> 24) & 0xFF;
            uint8_t r = (val >> 16) & 0xFF;
            uint8_t g = (val >> 8) & 0xFF;
            uint8_t b = val & 0xFF;
            if (a == 0) transparentCount++;
            else if (r > 200 && g > 200 && b > 200 && a > 100) whiteCount++;
            else if (r < 50 && g < 50 && b < 50 && a > 100) outlineCount++;
        }
        std::cout << nlohmann::json({
            {"status", "ok"},
            {"total_pixels", total},
            {"background_alpha_zero", transparentCount > 0},
            {"outline_pixel", outlineCount > 0},
            {"white_glyph_pixel", whiteCount > 0},
            {"transparent_pixels", transparentCount},
            {"outline_pixels", outlineCount},
            {"white_pixels", whiteCount}
        }).dump() << std::endl;
        return 0;
    }

    if (probeMode) {
        D3D11Context ctx;
        if (!ctx.Initialize(probeEncoder, false)) {
            std::cout << nlohmann::json({
                {"status","error"},
                {"reason","D3D11_DEVICE_INIT_FAILED"},
                {"message","D3D11 device creation failed for requested vendor"}
            }).dump() << std::endl;
            return 1;
        }
        HwEncoder encoder(ctx);
        if (!encoder.Initialize(probeEncoder, probeCodec, probeWidth, probeHeight, {1001,30000}, {30000,1001}, 20000000, probePreset)) {
            char luidStr[64] = "0:0";
            LUID luid = ctx.GetAdapterLuid();
            snprintf(luidStr, sizeof(luidStr), "%08x:%08x", (unsigned)luid.HighPart, (unsigned)luid.LowPart);
            std::string reason = encoder.GetLastFailureReason();
            if (reason.empty()) reason = "ENCODER_INIT_FAILED";
            std::cout << nlohmann::json({
                {"status","error"},
                {"encoder",encoder.GetActualEncoderName()},
                {"reason",reason},
                {"message",encoder.GetLastFailureDetails().empty() ? "Encoder initialization failed" : encoder.GetLastFailureDetails()},
                {"luid",luidStr},
                {"vendor_id",ctx.GetVendorId()},
                {"device_id",ctx.GetDeviceId()}
            }).dump() << std::endl;
            return 1;
        }
        char luidStr[64] = "0:0";
        LUID luid = ctx.GetAdapterLuid();
        snprintf(luidStr, sizeof(luidStr), "%08x:%08x", (unsigned)luid.HighPart, (unsigned)luid.LowPart);
        std::cout << nlohmann::json({
            {"status","ok"},
            {"d3d11",true},
            {"encoder",encoder.GetActualEncoderName()},
            {"hardware_frames",true},
            {"luid",luidStr},
            {"vendor_id",ctx.GetVendorId()},
            {"device_id",ctx.GetDeviceId()}
        }).dump() << std::endl;
        return 0;
    }

    ExportConfig config;
    std::string err;

    if (!configPath.empty()) {
        if (!ExportConfig::LoadFromFile(configPath, config, err)) {
            std::cerr << nlohmann::json({{"type","error"},{"message",err}}).dump() << std::endl;
            return 1;
        }
    } else if (!jsonStr.empty()) {
        if (!ExportConfig::LoadFromString(jsonStr, config, err)) {
            std::cerr << nlohmann::json({{"type","error"},{"message",err}}).dump() << std::endl;
            return 1;
        }
    } else {
        std::cerr << "{\"type\":\"error\",\"message\":\"Usage: KomparatorGpuExporter --config <config.json> [--debug-gpu-copies]\"}" << std::endl;
        return 1;
    }

    if (debugCopies) {
        config.debug_gpu_copies = true;
    }

    auto pipeline = std::make_shared<ExportPipeline>(config);

    // Stdin monitoring thread for cancel commands
    std::thread cancelThread([pipeline]() {
        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.find("cancel") != std::string::npos) {
                pipeline->RequestCancel();
                break;
            }
        }
    });
    cancelThread.detach();

    int ret = pipeline->Run();
    return ret;
}
