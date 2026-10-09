#pragma once

#include "D3D11Context.h"
#include "NvencDirectEncoder.h"
#include <string>
#include <vector>
#include <memory>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/opt.h>
}

class HwEncoder {
public:
    HwEncoder(D3D11Context& d3dContext);
    ~HwEncoder();

    bool Initialize(
        const std::string& encoderName,
        const std::string& codecName,
        int width, int height,
        AVRational timeBase, AVRational framerate,
        int64_t bitrate,
        const std::string& preset = "balanced"
    );
    void Shutdown();

    // Sends composed GPU texture directly to hardware encoder without host memory copy
    int SendFrame(ID3D11Texture2D* composedTex, int64_t pts, bool retry = false, const std::atomic<bool>* cancelled = nullptr);
    int Flush();
    size_t RingDepth() const { return m_useDirectNvenc ? m_nvencDirect->RingDepth() : 0; }
    size_t PeakInFlight() const { return m_useDirectNvenc ? m_nvencDirect->PeakInFlight() : 0; }
    bool AsyncEvents() const { return m_useDirectNvenc && m_nvencDirect->AsyncEvents(); }
    int ReceivePacket(AVPacket* pkt);

    AVCodecContext* GetCodecContext() const { return m_codecCtx; }
    const std::string& GetActualEncoderName() const { return m_actualEncoderName; }
    const std::string& GetLastFailureReason() const { return m_lastFailureReason; }
    const std::string& GetLastFailureDetails() const { return m_lastFailureDetails; }

private:
    std::string SelectEncoder(const std::string& requestedEncoder, const std::string& codecName);

    D3D11Context& m_d3dContext;
    AVCodecContext* m_codecCtx = nullptr;
    AVBufferRef* m_hwFramesRef = nullptr;
    AVFrame* m_hwFrame = nullptr;
    std::string m_actualEncoderName;
    std::string m_lastFailureReason;
    std::string m_lastFailureDetails;
    int m_width = 0;
    int m_height = 0;

    bool m_useDirectNvenc = false;
    std::unique_ptr<NvencDirectEncoder> m_nvencDirect;
};
