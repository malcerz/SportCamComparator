#pragma once
#include "DemuxerDecoder.h"
#include <functional>
extern "C" {
#include <libavfilter/avfilter.h>
#include <libavfilter/buffersink.h>
}
class AudioMuxer {
public:
    ~AudioMuxer();
    bool Initialize(const std::string& output, AVCodecContext* video, const std::string& mode,
                    DemuxerDecoder& dec1, DemuxerDecoder& dec2, double duration, double offset);
    bool Close(bool finalize = true);
    bool WriteVideoPacket(AVPacket* pkt, AVRational timeBase);
    bool CopyAudioPackets(const std::function<bool()>& cancelled, double durationLimit = -1);
    uint64_t OutputBytes() const { return m_outputBytes; }
    double DiskWriteMs() const { return m_diskWriteMs; }
private:
    using WriteCallback = int (*)(void*, const uint8_t*, int);
    WriteCallback m_originalWrite = nullptr;
    uint64_t m_outputBytes = 0;
    double m_diskWriteMs = 0;
    static int TimedWrite(void* opaque, const uint8_t* data, int size);
    bool Check(int ret, const char* operation);
    bool DrainAudio();
    AVFormatContext* m_outFmtCtx = nullptr;
    AVStream* m_videoStream = nullptr;
    AVStream* m_audioStream = nullptr;
    AVCodecContext* m_audioEncoder = nullptr;
    AVFilterGraph* m_graph = nullptr;
    AVFilterContext* m_sink = nullptr;
    bool m_headerWritten = false;
};
