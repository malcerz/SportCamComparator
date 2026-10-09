#include "PipelineProfile.h"
#include "HwEncoder.h"
#include <iostream>

extern "C" {
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_d3d11va.h>
#include <libavutil/hwcontext_qsv.h>
}

HwEncoder::HwEncoder(D3D11Context& d3dContext)
    : m_d3dContext(d3dContext) {
    m_hwFrame = av_frame_alloc();
    m_nvencDirect = std::make_unique<NvencDirectEncoder>();
}

HwEncoder::~HwEncoder() {
    Shutdown();
    if (m_hwFrame) {
        av_frame_free(&m_hwFrame);
    }
}

void HwEncoder::Shutdown() {
    if (m_useDirectNvenc && m_nvencDirect) {
        m_nvencDirect->Shutdown();
        m_useDirectNvenc = false;
    }
    if (m_codecCtx) {
        avcodec_free_context(&m_codecCtx);
        m_codecCtx = nullptr;
    }
    if (m_hwFramesRef) {
        av_buffer_unref(&m_hwFramesRef);
        m_hwFramesRef = nullptr;
    }
}

std::string HwEncoder::SelectEncoder(const std::string& requestedEncoder, const std::string& /*codecName*/) {
    if (requestedEncoder == "amf" || requestedEncoder == "amd" || requestedEncoder == "AMD AMF") {
        return "hevc_amf";
    }
    if (requestedEncoder == "nvenc" || requestedEncoder == "nvidia" || requestedEncoder == "NVIDIA") {
        return "hevc_nvenc";
    }
    if (requestedEncoder == "qsv" || requestedEncoder == "intel" || requestedEncoder == "Intel QSV") {
        return "hevc_qsv";
    }

    if (requestedEncoder != "auto") return requestedEncoder;

    ComPtr<IDXGIDevice> device;
    ComPtr<IDXGIAdapter> adapter;
    DXGI_ADAPTER_DESC desc{};
    if (SUCCEEDED(m_d3dContext.GetDevice()->QueryInterface(IID_PPV_ARGS(&device))) &&
        SUCCEEDED(device->GetAdapter(&adapter)) && SUCCEEDED(adapter->GetDesc(&desc))) {
        if (desc.VendorId == 0x1002) return "hevc_amf";
        if (desc.VendorId == 0x10de) return "hevc_nvenc";
        if (desc.VendorId == 0x8086) return "hevc_qsv";
    }

    // Auto-detect based on what encoder can be found and initialized
    std::vector<std::string> candidates = { "hevc_amf", "hevc_nvenc", "hevc_qsv" };
    for (const auto& cand : candidates) {
        if (avcodec_find_encoder_by_name(cand.c_str())) {
            return cand;
        }
    }

    return "hevc_amf";
}

bool HwEncoder::Initialize(
    const std::string& encoderName,
    const std::string& codecName,
    int width, int height,
    AVRational timeBase, AVRational framerate,
    int64_t bitrate,
    const std::string& preset
) {
    Shutdown();
    m_width = width;
    m_height = height;
    m_actualEncoderName = SelectEncoder(encoderName, codecName);

    // -------------------------------------------------------------------------
    // 1. NVIDIA Direct NVENC API 13.0 (optional developer FFmpeg comparison)
    // -------------------------------------------------------------------------
    if (m_actualEncoderName.find("nvenc") != std::string::npos) {
        bool tryDirect = std::getenv("EXPORT_FFMPEG_NVENC") == nullptr;
        const AVCodec* codec = avcodec_find_encoder_by_name(m_actualEncoderName.c_str());
        if (tryDirect || !codec) {
            tryDirect = true;
        } else {
            m_codecCtx = avcodec_alloc_context3(codec);
            if (!m_codecCtx) {
                tryDirect = true;
            } else {
                m_codecCtx->width = m_width;
                m_codecCtx->height = m_height;
                m_codecCtx->time_base = timeBase;
                m_codecCtx->framerate = framerate;
                m_codecCtx->pix_fmt = AV_PIX_FMT_D3D11;
                m_codecCtx->profile = AV_PROFILE_HEVC_MAIN;
                m_codecCtx->bit_rate = bitrate > 0 ? bitrate : 20000000;
                m_codecCtx->gop_size = (int)av_q2d(framerate) * 2;

                m_hwFramesRef = av_hwframe_ctx_alloc(m_d3dContext.GetHwDeviceCtx());
                if (!m_hwFramesRef) {
                    tryDirect = true;
                } else {
                    AVHWFramesContext* frames_ctx = (AVHWFramesContext*)m_hwFramesRef->data;
                    AVD3D11VAFramesContext* frames_hwctx = (AVD3D11VAFramesContext*)frames_ctx->hwctx;
                    frames_ctx->format = AV_PIX_FMT_D3D11;
                    frames_ctx->sw_format = AV_PIX_FMT_NV12;
                    frames_ctx->width = m_width;
                    frames_ctx->height = m_height;
                    frames_ctx->initial_pool_size = 0;
                    frames_hwctx->BindFlags = D3D11_BIND_SHADER_RESOURCE;

                    int ret = av_hwframe_ctx_init(m_hwFramesRef);
                    if (ret < 0) {
                        tryDirect = true;
                    } else {
                        m_codecCtx->hw_frames_ctx = av_buffer_ref(m_hwFramesRef);

                        std::string nvPreset = "p4";
                        if (preset == "speed" || preset == "fast" || preset == "Najszybszy") nvPreset = "p2";
                        else if (preset == "quality" || preset == "best" || preset == "Najlepsza jakość") nvPreset = "p6";
                        av_opt_set(m_codecCtx->priv_data, "preset", nvPreset.c_str(), 0);
                        av_opt_set(m_codecCtx->priv_data, "tune", "hq", 0);
                        av_opt_set(m_codecCtx->priv_data, "profile", "main", 0);

                        ret = avcodec_open2(m_codecCtx, codec, nullptr);
                        if (ret < 0) {
                            tryDirect = true;
                        } else {
                            // Verify frame allocation
                            AVFrame* probeFrame = av_frame_alloc();
                            ret = av_hwframe_get_buffer(m_hwFramesRef, probeFrame, 0);
                            av_frame_free(&probeFrame);
                            if (ret < 0) tryDirect = true;
                        }
                    }
                }
            }
        }

        if (tryDirect) {
            // Clean up failed FFmpeg context
            if (m_codecCtx) { avcodec_free_context(&m_codecCtx); m_codecCtx = nullptr; }
            if (m_hwFramesRef) { av_buffer_unref(&m_hwFramesRef); m_hwFramesRef = nullptr; }

            // Initialize Direct NVENC D3D11 Zero-Copy (API 13.0 for Pascal / driver 582.78)
            if (m_nvencDirect->Initialize(
                m_d3dContext.GetDevice(),
                m_d3dContext.GetContext(),
                m_width, m_height,
                timeBase, framerate,
                bitrate, preset)) {
                m_useDirectNvenc = true;

                // Create lightweight dummy AVCodecContext for AudioMuxer metadata export
                m_codecCtx = avcodec_alloc_context3(nullptr);
                if (m_codecCtx) {
                    m_codecCtx->codec_type = AVMEDIA_TYPE_VIDEO;
                    m_codecCtx->codec_id = AV_CODEC_ID_HEVC;
                    m_codecCtx->width = m_width;
                    m_codecCtx->height = m_height;
                    m_codecCtx->pix_fmt = AV_PIX_FMT_NV12;
                    m_codecCtx->time_base = timeBase;
                    m_codecCtx->framerate = framerate;
                    m_codecCtx->bit_rate = bitrate > 0 ? bitrate : 20000000;
                }
                if(!m_codecCtx){m_lastFailureReason="NVENC_METADATA_ALLOCATION_FAILED";return false;}
                std::cerr << "[HwEncoder] Initialized Direct NVENC D3D11 Zero-Copy with preset '" << preset << "' and profile 'main'" << std::endl;
                return true;
            } else {
                m_lastFailureReason = m_nvencDirect->GetLastFailureReason();
                m_lastFailureDetails = m_nvencDirect->GetLastFailureDetails();
                std::cerr << "{\"type\":\"error\",\"reason\":\"" << m_lastFailureReason << "\",\"message\":\"" << m_lastFailureDetails << "\"}" << std::endl;
                return false;
            }
        }

        std::cerr << "[HwEncoder] Initialized standard hevc_nvenc with preset '" << preset << "' and profile 'main'" << std::endl;
        return true;
    }

    // -------------------------------------------------------------------------
    // 2. INTEL QSV & AMD AMF PATH
    // -------------------------------------------------------------------------
    const AVCodec* codec = avcodec_find_encoder_by_name(m_actualEncoderName.c_str());
    if (!codec) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Hardware encoder " << m_actualEncoderName << " not found in FFmpeg.\"}" << std::endl;
        return false;
    }

    m_codecCtx = avcodec_alloc_context3(codec);
    if (!m_codecCtx) return false;

    m_codecCtx->width = m_width;
    m_codecCtx->height = m_height;
    m_codecCtx->time_base = timeBase;
    m_codecCtx->framerate = framerate;
    m_codecCtx->profile = AV_PROFILE_HEVC_MAIN;
    m_codecCtx->bit_rate = bitrate > 0 ? bitrate : 20000000;
    m_codecCtx->gop_size = (int)av_q2d(framerate) * 2;

    if (m_actualEncoderName.find("qsv") != std::string::npos) {
        AVBufferRef* qsvDevRef = nullptr;
        int qret = av_hwdevice_ctx_create_derived(&qsvDevRef, AV_HWDEVICE_TYPE_QSV, m_d3dContext.GetHwDeviceCtx(), 0);
        if (qret < 0) {
            m_lastFailureReason = "QSV_PIXFMT_INTEROP_FAILED";
            m_lastFailureDetails = "hevc_qsv requires AV_PIX_FMT_QSV; D3D11VA hwdevice derivation failed";
            std::cerr << "{\"type\":\"error\",\"reason\":\"QSV_PIXFMT_INTEROP_FAILED\",\"message\":\"" << m_lastFailureDetails << "\"}" << std::endl;
            return false;
        }

        m_codecCtx->pix_fmt = AV_PIX_FMT_QSV;
        m_hwFramesRef = av_hwframe_ctx_alloc(qsvDevRef);
        if (!m_hwFramesRef) {
            av_buffer_unref(&qsvDevRef);
            m_lastFailureReason = "QSV_PIXFMT_INTEROP_FAILED";
            m_lastFailureDetails = "av_hwframe_ctx_alloc failed for QSV";
            return false;
        }

        AVHWFramesContext* frames_ctx = (AVHWFramesContext*)m_hwFramesRef->data;
        frames_ctx->format = AV_PIX_FMT_QSV;
        frames_ctx->sw_format = AV_PIX_FMT_NV12;
        frames_ctx->width = m_width;
        frames_ctx->height = m_height;
        frames_ctx->initial_pool_size = 16;
        AVQSVFramesContext* qsvFCtx = (AVQSVFramesContext*)frames_ctx->hwctx;
        // Bind video memory decode/encode target without render target flag (rejected on Intel NV12)
        qsvFCtx->frame_type = MFX_MEMTYPE_VIDEO_MEMORY_DECODER_TARGET | MFX_MEMTYPE_FROM_ENCODE;

        int ret = av_hwframe_ctx_init(m_hwFramesRef);
        if (ret < 0) {
            av_buffer_unref(&qsvDevRef);
            m_lastFailureReason = "QSV_PIXFMT_INTEROP_FAILED";
            m_lastFailureDetails = "av_hwframe_ctx_init failed for QSV";
            return false;
        }

        // Set loader to nullptr on QSV device context so FFmpeg clones the valid D3D11-bound session
        AVHWDeviceContext* qsvHwDev = (AVHWDeviceContext*)qsvDevRef->data;
        AVQSVDeviceContext* qsvDevCtx = (AVQSVDeviceContext*)qsvHwDev->hwctx;
        if (qsvDevCtx) {
            qsvDevCtx->loader = nullptr;
        }

        m_codecCtx->hw_device_ctx = av_buffer_ref(qsvDevRef);
        av_buffer_unref(&qsvDevRef);

        std::string qsvPreset = "medium";
        if (preset == "speed" || preset == "fast" || preset == "Najszybszy") qsvPreset = "faster";
        else if (preset == "quality" || preset == "best" || preset == "Najlepsza jakość") qsvPreset = "slow";
        av_opt_set(m_codecCtx->priv_data, "preset", qsvPreset.c_str(), 0);
        av_opt_set(m_codecCtx->priv_data, "profile", "main", 0);
    } else {
        // AMD AMF
        m_codecCtx->pix_fmt = AV_PIX_FMT_D3D11;
        // The AMD compositor normalizes SDR/HLG inputs into its BT.709 limited
        // NV12 output surface. Carry that output contract into AMF's bitstream.
        m_codecCtx->color_range = AVCOL_RANGE_MPEG;
        m_codecCtx->colorspace = AVCOL_SPC_BT709;
        m_codecCtx->color_primaries = AVCOL_PRI_BT709;
        m_codecCtx->color_trc = AVCOL_TRC_BT709;
        m_hwFramesRef = av_hwframe_ctx_alloc(m_d3dContext.GetHwDeviceCtx());
        if (!m_hwFramesRef) {
            m_lastFailureReason = "HWFRAMES_ALLOC_FAILED";
            m_lastFailureDetails = "av_hwframe_ctx_alloc failed for encoder";
            return false;
        }

        AVHWFramesContext* frames_ctx = (AVHWFramesContext*)m_hwFramesRef->data;
        AVD3D11VAFramesContext* frames_hwctx = (AVD3D11VAFramesContext*)frames_ctx->hwctx;
        frames_ctx->format = AV_PIX_FMT_D3D11;
        frames_ctx->sw_format = AV_PIX_FMT_NV12;
        frames_ctx->width = m_width;
        frames_ctx->height = m_height;
        frames_ctx->initial_pool_size = 0;
        frames_hwctx->BindFlags = D3D11_BIND_SHADER_RESOURCE;

        int ret = av_hwframe_ctx_init(m_hwFramesRef);
        if (ret < 0) {
            char err[256]; av_strerror(ret, err, sizeof(err));
            m_lastFailureReason = "HWFRAMES_INIT_FAILED";
            m_lastFailureDetails = err;
            return false;
        }

        av_opt_set(m_codecCtx->priv_data, "usage", "transcoding", 0);
        std::string amfQuality = "balanced";
        if (preset == "speed" || preset == "fast" || preset == "Najszybszy") amfQuality = "speed";
        else if (preset == "quality" || preset == "best" || preset == "Najlepsza jakość") amfQuality = "quality";
        av_opt_set(m_codecCtx->priv_data, "quality", amfQuality.c_str(), 0);
        av_opt_set(m_codecCtx->priv_data, "profile", "main", 0);
    }

    m_codecCtx->hw_frames_ctx = av_buffer_ref(m_hwFramesRef);

    std::cerr << "[HwEncoder] Initialized " << m_actualEncoderName << " with preset '" << preset << "' and profile 'main'" << std::endl;

    int ret = avcodec_open2(m_codecCtx, codec, nullptr);
    if (ret < 0) {
        char err[256];
        av_strerror(ret, err, sizeof(err));
        std::string errStr = err;
        if (m_actualEncoderName.find("amf") != std::string::npos) {
            m_lastFailureReason = "AMF_ENCODER_OPEN_FAILED";
            m_lastFailureDetails = errStr;
        } else if (m_actualEncoderName.find("qsv") != std::string::npos) {
            m_lastFailureReason = "QSV_PIXFMT_INTEROP_FAILED";
            m_lastFailureDetails = errStr;
        } else {
            m_lastFailureReason = "ENCODER_OPEN_FAILED";
            m_lastFailureDetails = errStr;
        }
        std::cerr << "{\"type\":\"error\",\"reason\":\"" << m_lastFailureReason << "\",\"message\":\"avcodec_open2 for " << m_actualEncoderName << " failed: " << err << "\"}" << std::endl;
        return false;
    }

    AVFrame* probeFrame = av_frame_alloc();
    if (!probeFrame) return false;
    ret = av_hwframe_get_buffer(m_hwFramesRef, probeFrame, 0);
    av_frame_free(&probeFrame);
    if (ret < 0) {
        char err[256]; av_strerror(ret, err, sizeof(err));
        std::cerr << "hardware frames allocation: " << err << std::endl;
        return false;
    }
    return true;
}

int HwEncoder::SendFrame(ID3D11Texture2D* composedTex, int64_t pts, bool retry, const std::atomic<bool>* cancelled) {
    if (m_useDirectNvenc && m_nvencDirect) {
        return m_nvencDirect->SendFrame(composedTex, pts, retry, cancelled);
    }

    if (!m_codecCtx || !composedTex) return AVERROR(EINVAL);
    if(cancelled && cancelled->load())return AVERROR_EXIT;
    if (retry) {
        int result = avcodec_send_frame(m_codecCtx, m_hwFrame);
        if (result != AVERROR(EAGAIN)) av_frame_unref(m_hwFrame);
        return result;
    }

    // Get a hardware surface buffer from the pool
    int ret = av_hwframe_get_buffer(m_hwFramesRef, m_hwFrame, 0);
    if (ret < 0) {
        char err[256];
        av_strerror(ret, err, sizeof(err));
        std::cerr << "{\"type\":\"error\",\"message\":\"av_hwframe_get_buffer failed: " << err << "\"}" << std::endl;
        return ret;
    }

    if (m_actualEncoderName.find("amf") != std::string::npos) {
        m_hwFrame->color_range = AVCOL_RANGE_MPEG;
        m_hwFrame->colorspace = AVCOL_SPC_BT709;
        m_hwFrame->color_primaries = AVCOL_PRI_BT709;
        m_hwFrame->color_trc = AVCOL_TRC_BT709;
    }

    ID3D11Texture2D* encTex = nullptr;
    int encSlice = 0;

    if (m_actualEncoderName.find("qsv") != std::string::npos) {
        mfxFrameSurface1* surf = (mfxFrameSurface1*)m_hwFrame->data[3];
        if (!surf || !surf->Data.MemId) {
            std::cerr << "{\"type\":\"error\",\"message\":\"QSV surface MemId is null\"}" << std::endl;
            return AVERROR_EXTERNAL;
        }
        mfxHDLPair* hdl = (mfxHDLPair*)surf->Data.MemId;
        encTex = (ID3D11Texture2D*)hdl->first;
        encSlice = (int)(intptr_t)hdl->second;
    } else {
        encTex = (ID3D11Texture2D*)m_hwFrame->data[0];
        encSlice = (int)(intptr_t)m_hwFrame->data[1];
    }

    // ZERO-COPY DIRECT GPU COPY (VRAM -> VRAM via DMA):
    { PipelineProfile::Scope cpu("GPU_COPY_MS");
      PipelineProfile::GpuScope gpu(m_d3dContext.GetDevice(),m_d3dContext.GetContext(),"GPU_COPY_GPU_MS");
    m_d3dContext.GetContext()->CopySubresourceRegion(
        encTex,
        D3D11CalcSubresource(0, encSlice, 1),
        0, 0, 0,
        composedTex,
        0,
        nullptr
    );
    }

    m_hwFrame->pts = pts;

    m_d3dContext.LogDebug("ENCODE: input texture=0x%p (slice %d), pts=%lld", encTex, encSlice, pts);

    { PipelineProfile::Scope measure("ENCODER_SEND_FRAME_MS"); ret = avcodec_send_frame(m_codecCtx, m_hwFrame); }
    if (ret != AVERROR(EAGAIN)) av_frame_unref(m_hwFrame);

    if (ret < 0 && ret != AVERROR(EAGAIN)) {
        char err[256];
        av_strerror(ret, err, sizeof(err));
        std::cerr << "{\"type\":\"error\",\"message\":\"avcodec_send_frame failed: " << err << "\"}" << std::endl;
        return ret;
    }

    return ret;
}

int HwEncoder::Flush() {
    if (m_useDirectNvenc && m_nvencDirect) {
        return m_nvencDirect->Flush();
    }

    if (!m_codecCtx) return AVERROR(EINVAL);
    int ret = avcodec_send_frame(m_codecCtx, nullptr);
    if (ret < 0 && ret != AVERROR_EOF && ret != AVERROR(EAGAIN)) {
        char err[256]; av_strerror(ret, err, sizeof(err));
        std::cerr << "encoder flush: " << err << std::endl;
        return ret;
    }
    return ret;
}

int HwEncoder::ReceivePacket(AVPacket* pkt) {
    if (m_useDirectNvenc && m_nvencDirect) {
        return m_nvencDirect->ReceivePacket(pkt);
    }

    if (!m_codecCtx) return AVERROR(EINVAL);
    PipelineProfile::Scope measure("ENCODER_RECEIVE_PACKET_MS");
    return avcodec_receive_packet(m_codecCtx, pkt);
}
