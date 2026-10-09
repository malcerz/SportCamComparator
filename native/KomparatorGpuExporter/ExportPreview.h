#pragma once
#include "D3D11Context.h"
#include <array>
#include <memory>
#include "../third_party/json.hpp"

// The immediate context is used only by the export thread. The worker owns CPU
// thumbnails and IPC; it never touches the device, compositor or stdout.
class ExportPreview {
public:
    explicit ExportPreview(D3D11Context& context) : ctx(context) {}
    ~ExportPreview();
    void Initialize(ID3D11Texture2D* finalCanvas, const std::string& pipe, bool injectFailure,
                    int requestedWidth, int requestedHeight, double requestedFps);
    void Tick(double pts, int64_t frame);
    void Stop();
    nlohmann::json Metrics() const;
private:
    struct Worker;
    struct Slot {
        ComPtr<ID3D11Texture2D> staging;
        ComPtr<ID3D11Query> done, begin, end, disjoint;
        bool pending = false;
        double pts = 0;
        int64_t frame = 0;
    };
    D3D11Context& ctx;
    std::shared_ptr<Worker> worker;
    std::array<Slot, 3> slots;
    ComPtr<ID3D11VideoProcessorEnumerator> enumerator;
    ComPtr<ID3D11VideoProcessor> processor;
    ComPtr<ID3D11VideoProcessorInputView> input;
    ComPtr<ID3D11VideoProcessorOutputView> output;
    ComPtr<ID3D11Texture2D> thumbnailTexture;
    int width = 0, height = 0;
    bool enabled = false;
    double nextPts = 0, gpuMs = 0, sampleInterval = 0.2;
    uint64_t requests = 0, drops = 0, readbacks = 0, bytes = 0, gpuSamples = 0;
    void Disable(const std::string& reason);
};
