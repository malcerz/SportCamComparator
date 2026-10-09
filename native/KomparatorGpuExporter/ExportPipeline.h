#pragma once

#include "Config.h"
#include "D3D11Context.h"
#include "DemuxerDecoder.h"
#include "GpuCompositor.h"
#include "TelemetryRenderer.h"
#include "HwEncoder.h"
#include "AudioMuxer.h"
#include <atomic>
#include <chrono>

class ExportPipeline {
public:
    ExportPipeline(const ExportConfig& config);
    ~ExportPipeline();

    // Runs the export pipeline. Returns 0 on success, 1 on error, 2 on cancel.
    int Run();

    void RequestCancel() { m_cancelRequested = true; }

private:
    std::string LookupTelemetryText(const TelemetryData& data, double timeSec);

    ExportConfig m_config;
    D3D11Context m_d3dContext;
    std::atomic<bool> m_cancelRequested{ false };
};
