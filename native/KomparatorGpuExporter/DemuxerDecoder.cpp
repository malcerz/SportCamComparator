#include "PipelineProfile.h"
#include "DemuxerDecoder.h"
#include <iostream>
#include <cmath>
extern "C" {
#include <libavutil/display.h>
#include <libavutil/pixdesc.h>
}

enum AVPixelFormat DemuxerDecoder::GetHwFormat(AVCodecContext* ctx, const enum AVPixelFormat* pix_fmts) {
    const enum AVPixelFormat* p;
    for (p = pix_fmts; *p != -1; p++) {
        if (*p == AV_PIX_FMT_D3D11) {
            return *p;
        }
    }
    return AV_PIX_FMT_NONE;
}

DemuxerDecoder::DemuxerDecoder(D3D11Context& d3dContext, int streamId)
    : m_d3dContext(d3dContext), m_streamId(streamId) {
    m_currentFrame = av_frame_alloc();
    m_nextFrame = av_frame_alloc();
    m_pkt = av_packet_alloc();
}

DemuxerDecoder::~DemuxerDecoder() {
    Close();
    if (m_currentFrame) av_frame_free(&m_currentFrame);
    if (m_nextFrame) av_frame_free(&m_nextFrame);
    if (m_pkt) av_packet_free(&m_pkt);
}

void DemuxerDecoder::Close() {
    if (m_videoCodecCtx) {
        avcodec_free_context(&m_videoCodecCtx);
        m_videoCodecCtx = nullptr;
    }
    if (m_audioCodecCtx) {
        avcodec_free_context(&m_audioCodecCtx);
        m_audioCodecCtx = nullptr;
    }
    if (m_fmtCtx) {
        avformat_close_input(&m_fmtCtx);
        m_fmtCtx = nullptr;
    }
}

bool DemuxerDecoder::Open(const std::string& filepath) {
    m_path = filepath;
    int ret = avformat_open_input(&m_fmtCtx, filepath.c_str(), nullptr, nullptr);
    if (ret < 0) {
        char err[256];
        av_strerror(ret, err, sizeof(err));
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to open input " << filepath << ": " << err << "\"}" << std::endl;
        return false;
    }

    ret = avformat_find_stream_info(m_fmtCtx, nullptr);
    if (ret < 0) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to find stream info for " << filepath << "\"}" << std::endl;
        return false;
    }

    m_videoStreamIdx = av_find_best_stream(m_fmtCtx, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (m_videoStreamIdx < 0) {
        std::cerr << "{\"type\":\"error\",\"message\":\"No video stream found in " << filepath << "\"}" << std::endl;
        return false;
    }

    m_audioStreamIdx = av_find_best_stream(m_fmtCtx, AVMEDIA_TYPE_AUDIO, -1, -1, nullptr, 0);

    AVStream* videoStream = m_fmtCtx->streams[m_videoStreamIdx];
    const auto* matrix = av_packet_side_data_get(videoStream->codecpar->coded_side_data,
        videoStream->codecpar->nb_coded_side_data, AV_PKT_DATA_DISPLAYMATRIX);
    if (matrix && matrix->size >= 9*sizeof(int32_t)) {
        double angle = av_display_rotation_get(reinterpret_cast<const int32_t*>(matrix->data));
        if (std::isfinite(angle)) m_rotation = (int(std::lround(-angle / 90)) * 90 % 360 + 360) % 360;
    }
    m_d3dContext.LogDebug("Decoder %d: detected stream rotation = %d deg", m_streamId, m_rotation);
    m_timeBase = videoStream->time_base;
    m_width = videoStream->codecpar->width;
    m_height = videoStream->codecpar->height;

    if (videoStream->duration != AV_NOPTS_VALUE) {
        m_duration = videoStream->duration * av_q2d(m_timeBase);
    } else if (m_fmtCtx->duration != AV_NOPTS_VALUE) {
        m_duration = (double)m_fmtCtx->duration / AV_TIME_BASE;
    }

    m_frameRate = av_guess_frame_rate(m_fmtCtx, videoStream, nullptr);
    if (m_frameRate.num <= 0 || m_frameRate.den <= 0) m_frameRate = {30, 1};
    m_fps = av_q2d(m_frameRate);

    const AVCodec* decoder = avcodec_find_decoder(videoStream->codecpar->codec_id);
    if (!decoder) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Decoder not found for stream in " << filepath << "\"}" << std::endl;
        return false;
    }

    m_videoCodecCtx = avcodec_alloc_context3(decoder);
    if (!m_videoCodecCtx || avcodec_parameters_to_context(m_videoCodecCtx, videoStream->codecpar) < 0) return false;

    m_videoCodecCtx->hw_device_ctx = av_buffer_ref(m_d3dContext.GetHwDeviceCtx());
    if (!m_videoCodecCtx->hw_device_ctx) return false;
    m_videoCodecCtx->get_format = GetHwFormat;

    ret = avcodec_open2(m_videoCodecCtx, decoder, nullptr);
    if (ret < 0) {
        char err[256];
        av_strerror(ret, err, sizeof(err));
        std::cerr << "{\"type\":\"error\",\"message\":\"avcodec_open2 failed: " << err << "\"}" << std::endl;
        return false;
    }

    // Decode first frame into m_nextFrame to establish pipeline
    if (DecodeNextRawFrame()) {
        // Swap into current
        std::swap(m_currentFrame, m_nextFrame);
        m_currentPts = m_nextPts;
        m_hasFrame = true;
    }

    return m_hasFrame && !m_failed;
}

bool DemuxerDecoder::DecodeNextRawFrame() {
    auto fail = [&](const char* operation, int ret) {
        char err[256]; av_strerror(ret, err, sizeof(err));
        std::cerr << "decoder " << m_streamId << " " << operation << ": " << err << std::endl;
        m_failed = true;
        return false;
    };
    while (!m_eof && !m_failed) {
        av_frame_unref(m_nextFrame);
        int ret;
        { PipelineProfile::Scope measure("DECODE_VIDEO"+std::to_string(m_streamId)+"_WAIT_MS"); ret = avcodec_receive_frame(m_videoCodecCtx, m_nextFrame); }
        if (ret == 0) {
            if (m_nextFrame->format != AV_PIX_FMT_D3D11) {
                m_d3dContext.software_frame_count++;
                return fail("non D3D11 frame", AVERROR(EINVAL));
            }
            if (m_decodedFrameIndex == 0) {
                auto* hwctx = m_nextFrame->hw_frames_ctx
                    ? reinterpret_cast<AVHWFramesContext*>(m_nextFrame->hw_frames_ctx->data) : nullptr;
                auto* texture = reinterpret_cast<ID3D11Texture2D*>(m_nextFrame->data[0]);
                D3D11_TEXTURE2D_DESC td{};
                if (texture) texture->GetDesc(&td);
                const char* pixfmt = hwctx ? av_get_pix_fmt_name(hwctx->sw_format) : "unknown";
                std::cerr << "[D3D11VA] stream=" << m_streamId << " hw_format=" << av_get_pix_fmt_name((AVPixelFormat)m_nextFrame->format)
                          << " sw_format=" << (pixfmt ? pixfmt : "unknown") << " dxgi_format=" << (unsigned)td.Format
                          << " texture=" << td.Width << "x" << td.Height << " array=" << td.ArraySize
                          << " bind=0x" << std::hex << td.BindFlags << std::dec
                          << " colorspace=" << m_nextFrame->colorspace << " range=" << m_nextFrame->color_range
                          << " transfer=" << m_nextFrame->color_trc << std::endl;
            }
            int64_t pts = m_nextFrame->best_effort_timestamp;
            int64_t origin = m_fmtCtx->streams[m_videoStreamIdx]->start_time;
            if (origin == AV_NOPTS_VALUE) origin = 0;
            m_nextPts = pts == AV_NOPTS_VALUE ? m_decodedFrameIndex / m_fps : (pts - origin) * av_q2d(m_timeBase);
            ++m_decodedFrameIndex;
            return true;
        }
        if (ret == AVERROR_EOF) { m_eof = true; return false; }
        if (ret != AVERROR(EAGAIN)) return fail("receive frame", ret);
        if (m_draining) return fail("decoder stalled while draining", AVERROR(EINVAL));
        do {
            ret = av_read_frame(m_fmtCtx, m_pkt);
            if (ret == AVERROR_EOF) {
                ret = avcodec_send_packet(m_videoCodecCtx, nullptr);
                if (ret < 0 && ret != AVERROR_EOF) return fail("send drain", ret);
                m_draining = true;
                break;
            }
            if (ret < 0) return fail("read packet", ret);
            bool video = m_pkt->stream_index == m_videoStreamIdx;
            if (video) {
                { PipelineProfile::Scope measure("DECODE_VIDEO"+std::to_string(m_streamId)+"_SUBMIT_MS"); ret = avcodec_send_packet(m_videoCodecCtx, m_pkt); }
                av_packet_unref(m_pkt);
                // receive_frame returned EAGAIN, so send must accept this packet.
                if (ret < 0) return fail("send packet", ret);
                break;
            }
            av_packet_unref(m_pkt);
        } while (true);
    }
    return false;
}

bool DemuxerDecoder::GetFrameAt(double target, AVFrame** outFrame) {
    if (!m_hasFrame || m_failed) { *outFrame = nullptr; return false; }
    // Keep the last successfully decoded hardware frame at EOF.
    while (m_currentPts < target && !m_eof) {
        if (!DecodeNextRawFrame()) break;
        std::swap(m_currentFrame, m_nextFrame);
        m_currentPts = m_nextPts;
    }
    *outFrame = m_currentFrame;
    return !m_failed;
}
