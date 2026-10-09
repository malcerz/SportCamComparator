#include "PipelineProfile.h"
#include "ExportPipeline.h"
#include "ExportPreview.h"
#include <iostream>
#include <iomanip>
#include <algorithm>
#include <cstdio>
#include <cmath>
#include <sstream>
#include <ctime>
#include "../third_party/json.hpp"

ExportPipeline::ExportPipeline(const ExportConfig& config)
    : m_config(config) {
    m_d3dContext.debug_gpu_copies = config.debug_gpu_copies;
}

ExportPipeline::~ExportPipeline() {
}

std::string ExportPipeline::LookupTelemetryText(const TelemetryData& data, double timeSec) {
    if (data.samples.empty()) return "Brak danych telemetrii";
    timeSec = (std::max)(0.0, timeSec);
    auto it = std::lower_bound(data.samples.begin(), data.samples.end(), timeSec,
        [](const TelemetrySample& sample, double t) { return sample.timestamp < t; });
    if (it == data.samples.end()) --it;
    else if (it != data.samples.begin() && timeSec - (it-1)->timestamp <= it->timestamp - timeSec) --it;
    std::ostringstream text;
    if (!data.camera.empty()) text << data.camera << "\n";
    if (!data.start_datetime.empty()) {
        std::tm clock{};
        std::istringstream input(data.start_datetime.substr(0,19));
        input >> std::get_time(&clock, "%Y-%m-%dT%H:%M:%S");
        double fraction = 0;
        if (data.start_datetime.size() > 19 && data.start_datetime[19] == '.')
            fraction = std::strtod(data.start_datetime.c_str()+19, nullptr);
        if (!input.fail()) {
            time_t epoch = _mkgmtime(&clock) + static_cast<time_t>(std::floor(it->timestamp + fraction));
            gmtime_s(&clock, &epoch);
            text << std::put_time(&clock, "%Y-%m-%d  %H:%M:%S") << "\n";
        }
    }
    text << std::fixed << std::setprecision(3) << "TIME : " << timeSec << "s\nISO  : ";
    if (it->iso >= 0) text << it->iso; else text << "None";
    text << "\nEXP  : ";
    if (it->exposure > 0) text << "1/" << (std::max)(1LL, std::llround(1.0/it->exposure)); else text << "N/A";
    return text.str();
}

int ExportPipeline::Run() {
    using json = nlohmann::json;
    AudioMuxer muxer;
    bool outputStarted = false;
    bool failed = false;
    std::string failureReason;
    auto failure = [&](const std::string& reason) {
        failed = true; failureReason = reason;
        muxer.Close(false);
        if (outputStarted) std::remove(m_config.output.c_str());
        std::cerr << json({{"type", "error"}, {"message", failureReason}}).dump() << std::endl;
        return 1;
    };
    std::cout << json({{"type","init"},{"status","starting"}}).dump() << std::endl;
    if (!m_d3dContext.Initialize(m_config.encoder, m_config.debug_gpu_copies)) return failure("D3D11 initialization failed");
    DemuxerDecoder dec1(m_d3dContext, 1), dec2(m_d3dContext, 2);
    if (!dec1.Open(m_config.video1)) return failure("Decoder 1 open/decode failed");
    if (!dec2.Open(m_config.video2)) return failure("Decoder 2 open/decode failed");
    if (m_config.input_rotation1 >= 0) dec1.SetRotation(m_config.input_rotation1);
    if (m_config.input_rotation2 >= 0) dec2.SetRotation(m_config.input_rotation2);
    std::cerr << "INPUT_ORIENTATION_D3D_ROTATION1=" << dec1.GetRotation()
              << " INPUT_ORIENTATION_D3D_ROTATION2=" << dec2.GetRotation() << std::endl;
    AVRational framerate = m_config.fps > 0 ? av_d2q(m_config.fps, 1001000) : dec1.GetFrameRate();
    AVRational timeBase = av_inv_q(framerate);
    double fps = av_q2d(framerate);
    double delay1 = (std::max)(0.0, -m_config.offset_seconds), delay2 = (std::max)(0.0, m_config.offset_seconds);
    double duration = (std::max)(delay1 + dec1.GetDuration(), delay2 + dec2.GetDuration());
    if (m_config.duration_limit_seconds > 0) duration = (std::min)(duration, m_config.duration_limit_seconds);
    if (duration <= 0) return failure("Invalid source duration");
    GpuCompositor compositor(m_d3dContext);
    LayoutMode layout = (m_config.layout == "top_bottom" || m_config.layout == "vertical") ? LayoutMode::TopBottom : LayoutMode::LeftRight;
    if (!compositor.Initialize(m_config.width, m_config.height, layout, m_config.pad_to_4k, m_config.width, m_config.height)) return failure("Compositor initialization failed");
    if (!compositor.SetRotations(dec1.GetRotation(), dec2.GetRotation())) return failure("GPU source rotation unsupported");
    TelemetryRenderer overlay1(m_d3dContext, 1), overlay2(m_d3dContext, 2);
    int compW = compositor.GetWidth();
    int compH = compositor.GetHeight();
    int ovW = (std::max)(240, int(compW * .24));
    float fontSize = (std::max)(12.f, float(compH * .018) * m_config.overlay_font_scale);
    int ovH = (std::max)(140, int(fontSize * 7 + 28));
    if (m_config.show_overlay && (!overlay1.Initialize(ovW, ovH, fontSize, m_config.overlay_opacity) || !overlay2.Initialize(ovW, ovH, fontSize, m_config.overlay_opacity))) return failure("Overlay initialization failed");
    HwEncoder encoder(m_d3dContext);
    if (!encoder.Initialize(m_config.encoder, m_config.codec, compW, compH, timeBase, framerate, m_config.bitrate, m_config.encoder_preset)) return failure("Hardware encoder initialization failed");
    outputStarted = true;
    if (!muxer.Initialize(m_config.output, encoder.GetCodecContext(), m_config.audio, dec1, dec2, duration, m_config.offset_seconds)) return failure("Muxer/audio initialization failed");
    std::cout << json({{"type","init"},{"status","ok"},{"backend",encoder.GetActualEncoderName()}}).dump() << std::endl;
    ExportPreview preview(m_d3dContext);
    if (m_config.export_preview) preview.Initialize(compositor.GetOutputTexture(), m_config.preview_pipe,
        m_config.diagnostic_preview_failure, m_config.preview_width, m_config.preview_height, m_config.preview_fps);
    AVPacket* packet = av_packet_alloc();
    if (!packet) return failure("Packet allocation failed");
    auto drain = [&](bool flushing) {
        int ret;
        while ((ret = encoder.ReceivePacket(packet)) == 0) {
            const int64_t muxFrame=packet->pts;const double muxStart=PipelineProfile::Get().Now();
            PipelineProfile::Scope measure("MUX_VIDEO_MS");
            bool ok = muxer.WriteVideoPacket(packet, timeBase);
            PipelineProfile::Get().Event("MUX_PACKET",muxStart,PipelineProfile::Get().Now(),muxFrame);
            av_packet_unref(packet);
            if (!ok) { failed = true; failureReason = "Video packet write failed"; return; }
        }
        if (ret != AVERROR(EAGAIN) && ret != AVERROR_EOF) {
            char err[256]; av_strerror(ret, err, sizeof(err));
            failed = true; failureReason = std::string("Receive encoder packet: ") + err;
        } else if (flushing && ret != AVERROR_EOF) {
            failed = true; failureReason = "Encoder flush did not reach EOF";
        }
    };
    int64_t count = static_cast<int64_t>(std::ceil(duration * fps));
    int64_t frame = 0;
    uint64_t peakVram=m_d3dContext.VramBytes();
    auto start = std::chrono::steady_clock::now(), lastReport = start;
    for (; frame < count && !failed && !m_cancelRequested; ++frame) {
        PipelineProfile::FrameScope frameProfile(frame);
        PipelineProfile::Get().Poll(m_d3dContext.GetContext());
        if(PipelineProfile::Get().enabled && frame%30==0)peakVram=(std::max)(peakVram,m_d3dContext.VramBytes());
        double t = frame * av_q2d(timeBase);
        double t1 = (std::max)(0.0, (std::min)(dec1.GetDuration(), t-delay1));
        double t2 = (std::max)(0.0, (std::min)(dec2.GetDuration(), t-delay2));
        if(frame==0 || !std::getenv("EXPORT_ISOLATE_ENCODER")) {
        AVFrame *f1=nullptr, *f2=nullptr;
        if (!dec1.GetFrameAt(t1, &f1) || !dec2.GetFrameAt(t2, &f2) || !f1 || !f2) {
            failed = true; failureReason = "Video decoder failure at frame " + std::to_string(frame); break;
        }
        const int overlayCount = m_config.diagnostic_overlay_count >= 0
            ? m_config.diagnostic_overlay_count : (m_config.show_overlay ? 2 : 0);
        if (overlayCount > 0 && (!overlay1.UpdateText(LookupTelemetryText(m_config.telemetry1,t1), compositor.GetEnumerator()) ||
                                 (overlayCount > 1 && !overlay2.UpdateText(LookupTelemetryText(m_config.telemetry2,t2), compositor.GetEnumerator())))) {
            failed = true; failureReason = "Telemetry renderer failed"; break;
        }
        if (frame == m_config.diagnostic_fail_frame || !compositor.Composite(
            reinterpret_cast<ID3D11Texture2D*>(f1->data[0]), int(intptr_t(f1->data[1])), dec1.GetWidth(),dec1.GetHeight(),
            reinterpret_cast<ID3D11Texture2D*>(f2->data[0]), int(intptr_t(f2->data[1])), dec2.GetWidth(),dec2.GetHeight(),
            overlayCount > 0 ? &overlay1 : nullptr, overlayCount > 1 ? &overlay2 : nullptr,
            f1->colorspace, f1->color_range, f2->colorspace, f2->color_range,
            f1->color_trc, f2->color_trc)) {
            failed = true; failureReason = "Compositor failed at frame " + std::to_string(frame); break;
        }
        } // Developer isolation benchmark: repeat GPU input, never a normal export.
        { PipelineProfile::Scope measure("PREVIEW_READBACK_MS"); preview.Tick(t, frame); }
        if(m_cancelRequested)break;
        int sent = encoder.SendFrame(compositor.GetOutputTexture(), frame, false, &m_cancelRequested);
        if (sent == AVERROR(EAGAIN)) {
            drain(false);
            if (!failed) sent = encoder.SendFrame(compositor.GetOutputTexture(), frame, true, &m_cancelRequested);
        }
        if(sent==AVERROR_EXIT && m_cancelRequested)break;
        if (sent < 0 || failed) {
            char err[256]; av_strerror(sent, err, sizeof(err));
            failed = true; failureReason = std::string("Encoder send failed: ") + err; break;
        }
        drain(false);
        auto now = std::chrono::steady_clock::now();
        double elapsed = std::chrono::duration<double>(now-start).count();
        if (std::chrono::duration<double>(now-lastReport).count() >= .2 || frame+1 == count) {
            lastReport = now;
            double speed = (frame+1)/(std::max)(.001,elapsed);
            std::cout << json({{"type","progress"},{"frame",frame+1},{"fps",speed},{"percent",100.0*(frame+1)/count},{"eta",(count-frame-1)/speed}}).dump() << std::endl;
        }
    }
    preview.Stop();
    if (m_cancelRequested && !failed) {
        // Graceful cancel: flush encoder, write trailer, preserve file up to this point.
        // NV12 black != all-zero buffer – padding pixels are already correct from compositor.
        int flushRet = encoder.Flush();
        if(flushRet==AVERROR(EAGAIN)){drain(false);if(!failed)flushRet=encoder.Flush();}
        if(flushRet<0 && flushRet!=AVERROR_EOF){av_packet_free(&packet);return failure("Cancelled encoder drain failed");}
        drain(true);
        av_packet_free(&packet);
        if(failed)return failure(failureReason);
        // Complete audio for exactly the frames already submitted; do not restart video.
        if(!muxer.CopyAudioPackets([](){return false;},frame*av_q2d(timeBase)))return failure("Cancelled audio finalization failed");
        if(!muxer.Close(true))return failure("Cancelled MP4 trailer failed");
        std::cout << json({{"type","cancelled"},{"file_saved",true},{"total_frames",frame},
            {"full_frame_hwdownload_count",m_d3dContext.full_frame_hwdownload_count.load()},
            {"full_frame_hwupload_count",m_d3dContext.full_frame_hwupload_count.load()},
            {"software_frame_count",m_d3dContext.software_frame_count.load()}}).dump() << std::endl;
        return 2;
    }
    if (!failed) {
        int ret = encoder.Flush();
        if (ret == AVERROR(EAGAIN)) { drain(false); if (!failed) ret = encoder.Flush(); }
        if (ret < 0 && ret != AVERROR_EOF) {
            char err[256]; av_strerror(ret, err, sizeof(err));
            failed = true; failureReason = std::string("Encoder flush: ") + err;
        }
    }
    if (!failed) drain(true);
    PipelineProfile::Get().Poll(m_d3dContext.GetContext());
    av_packet_free(&packet);
    if (!failed) {
        PipelineProfile::Scope audioMeasure("MUX_AUDIO_MS");
        bool audioOk = muxer.CopyAudioPackets([&]() { return m_cancelRequested.load(); });
        if (m_cancelRequested) {
            // Audio interrupted by cancel: write trailer and preserve the file.
            muxer.Close(true);
            std::cout << json({{"type","cancelled"},{"file_saved",true}}).dump() << std::endl; return 2;
        }
        if (!audioOk) { failed = true; failureReason = "Audio render/write failed"; }
    }
    if (!failed && !muxer.Close()) { failed = true; failureReason = "Muxer trailer/close failed"; }
    if (failed) return failure(failureReason);
    double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    json result = json({{"type","complete"},{"status","success"},
        {"full_frame_hwdownload_count",m_d3dContext.full_frame_hwdownload_count.load()},
        {"full_frame_hwupload_count",m_d3dContext.full_frame_hwupload_count.load()},
        {"software_frame_count",m_d3dContext.software_frame_count.load()},
        {"telemetry_texture_uploads",m_d3dContext.telemetry_texture_uploads.load()},
        {"telemetry_uploaded_bytes",m_d3dContext.telemetry_uploaded_bytes.load()},
        {"total_frames",frame},{"avg_fps",frame/(std::max)(.001,elapsed)},{"duration",elapsed}});
    if(std::getenv("EXPORT_ISOLATE_ENCODER"))result["diagnostic_static_gpu_input"]=true;
    result["NVENC_RING_DEPTH"]=encoder.RingDepth();result["NVENC_PEAK_IN_FLIGHT"]=encoder.PeakInFlight();result["NVENC_ASYNC_EVENTS"]=encoder.AsyncEvents();
    result.update(preview.Metrics());
    if(PipelineProfile::Get().enabled){result["VRAM_PEAK_MB"]=peakVram/1048576.0;result["OUTPUT_WRITE_MBPS"]=muxer.OutputBytes()*8.0/1000000.0/(std::max)(.001,elapsed);result["OUTPUT_DISK_WAIT_MS"]=muxer.DiskWriteMs();}
    std::cerr << "FULL_FRAME_HWDOWNLOAD_COUNT=" << m_d3dContext.full_frame_hwdownload_count.load()
              << " FULL_FRAME_HWUPLOAD_COUNT=" << m_d3dContext.full_frame_hwupload_count.load()
              << " SOFTWARE_VIDEO_FRAME_COUNT=" << m_d3dContext.software_frame_count.load() << std::endl;
    std::cout << result.dump() << std::endl;
    return 0;
}
