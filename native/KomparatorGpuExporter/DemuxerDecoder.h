#pragma once

#include "D3D11Context.h"
#include <string>

extern "C" {
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libavutil/time.h>
}

class DemuxerDecoder {
public:
    DemuxerDecoder(D3D11Context& d3dContext, int streamId);
    ~DemuxerDecoder();

    bool Open(const std::string& filepath);
    void Close();

    // Advance until frame with PTS >= target_time_sec is reached
    // Returns true if a frame is available, false if EOF
    bool GetFrameAt(double target_time_sec, AVFrame** outFrame);

    int GetRotation() const { return m_rotation; }
    void SetRotation(int rotation) { m_rotation = (rotation % 360 + 360) % 360; }
    int GetWidth() const { return m_width; }
    int GetHeight() const { return m_height; }
    double GetDuration() const { return m_duration; }
    const std::string& GetPath() const { return m_path; }
    bool Failed() const { return m_failed; }
    AVRational GetFrameRate() const { return m_frameRate; }
    double GetFps() const { return m_fps; }
    AVRational GetTimeBase() const { return m_timeBase; }
    int GetVideoStreamIndex() const { return m_videoStreamIdx; }
    int GetAudioStreamIndex() const { return m_audioStreamIdx; }
    AVFormatContext* GetFormatContext() const { return m_fmtCtx; }
    AVCodecContext* GetAudioCodecContext() const { return m_audioCodecCtx; }
    AVStream* GetAudioStream() const { return m_audioStreamIdx >= 0 ? m_fmtCtx->streams[m_audioStreamIdx] : nullptr; }

    bool HasValidFrame() const { return m_currentFrame != nullptr && m_hasFrame; }
    double GetCurrentFramePts() const { return m_currentPts; }

private:
    static enum AVPixelFormat GetHwFormat(AVCodecContext* ctx, const enum AVPixelFormat* pix_fmts);
    bool DecodeNextRawFrame();

    D3D11Context& m_d3dContext;
    int m_streamId;

    AVFormatContext* m_fmtCtx = nullptr;
    AVCodecContext* m_videoCodecCtx = nullptr;
    AVCodecContext* m_audioCodecCtx = nullptr;

    int m_videoStreamIdx = -1;
    int m_audioStreamIdx = -1;

    int m_rotation = 0;
    int m_width = 0;
    int m_height = 0;
    double m_duration = 0.0;
    double m_fps = 30.0;
    AVRational m_timeBase = { 1, 30 };

    AVFrame* m_currentFrame = nullptr;
    AVFrame* m_nextFrame = nullptr;
    AVPacket* m_pkt = nullptr;

    double m_currentPts = -1.0;
    double m_nextPts = -1.0;
    bool m_hasFrame = false;
    bool m_eof = false;
    bool m_failed = false;
    bool m_draining = false;
    std::string m_path;
    AVRational m_frameRate = {30, 1};
    uint64_t m_decodedFrameIndex = 0;
};
