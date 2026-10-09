#include "PipelineProfile.h"
#include "AudioMuxer.h"
#include <iostream>
#include <sstream>
#include <vector>
#include <cmath>
extern "C" {
#include <libavutil/opt.h>
}

namespace { std::map<void*, AudioMuxer*> outputOwners; }
int AudioMuxer::TimedWrite(void* opaque,const uint8_t* data,int size){
    auto owner=outputOwners.find(opaque);if(owner==outputOwners.end())return AVERROR(EINVAL);
    auto* mux=owner->second;auto start=PipelineProfile::Clock::now();
    int ret=mux->m_originalWrite(opaque,data,size);
    double ms=std::chrono::duration<double,std::milli>(PipelineProfile::Clock::now()-start).count();
    mux->m_diskWriteMs+=ms;if(ret>0)mux->m_outputBytes+=ret;
    PipelineProfile::Get().Add("OUTPUT_DISK_WRITE_MS",ms);return ret;
}
bool AudioMuxer::Check(int ret, const char* operation) {
    if (ret >= 0) return true;
    char error[256]; av_strerror(ret, error, sizeof(error));
    std::cerr << "audio/muxer " << operation << ": " << error << std::endl;
    return false;
}
AudioMuxer::~AudioMuxer() { Close(false); }
bool AudioMuxer::Close(bool finalize) {
    bool ok = true;
    if (m_outFmtCtx) {
        if (m_headerWritten && finalize) ok = Check(av_write_trailer(m_outFmtCtx), "write trailer");
        m_headerWritten = false;
        if(m_outFmtCtx->pb){
            avio_flush(m_outFmtCtx->pb);
            if(m_originalWrite){m_outFmtCtx->pb->write_packet=m_originalWrite;outputOwners.erase(m_outFmtCtx->pb->opaque);m_originalWrite=nullptr;}
            ok=Check(avio_closep(&m_outFmtCtx->pb),"close output") && ok;
        }
        avformat_free_context(m_outFmtCtx); m_outFmtCtx = nullptr;
    }
    avcodec_free_context(&m_audioEncoder);
    avfilter_graph_free(&m_graph);
    return ok;
}

bool AudioMuxer::Initialize(const std::string& output, AVCodecContext* video, const std::string& mode,
                           DemuxerDecoder& dec1, DemuxerDecoder& dec2, double duration, double offset) {
    if (!Check(avformat_alloc_output_context2(&m_outFmtCtx, nullptr, nullptr, output.c_str()), "allocate output") || !m_outFmtCtx) return false;
    m_videoStream = avformat_new_stream(m_outFmtCtx, nullptr);
    if (!m_videoStream || !Check(avcodec_parameters_from_context(m_videoStream->codecpar, video), "video parameters")) return false;
    m_videoStream->time_base = video->time_base;
    m_videoStream->avg_frame_rate = video->framerate;
    std::vector<DemuxerDecoder*> sources;
    std::vector<double> delays;
    if ((mode == "left" || mode == "both") && dec1.GetAudioStream()) { sources.push_back(&dec1); delays.push_back((std::max)(0.0, -offset)); }
    if ((mode == "right" || mode == "both") && dec2.GetAudioStream()) { sources.push_back(&dec2); delays.push_back((std::max)(0.0, offset)); }
    if (!sources.empty()) {
        // Audio-only graph: amovie owns independent demux/decode contexts.
        m_graph = avfilter_graph_alloc();
        if (!m_graph) return false;
        AVFilterInOut* outputs = nullptr;
        std::ostringstream description;
        for (size_t i=0; i<sources.size(); ++i) {
            std::string name = "source" + std::to_string(i);
            AVFilterContext* movie = avfilter_graph_alloc_filter(m_graph, avfilter_get_by_name("amovie"), name.c_str());
            if (!movie || !Check(av_opt_set(movie, "filename", sources[i]->GetPath().c_str(), AV_OPT_SEARCH_CHILDREN), "audio filename") ||
                !Check(av_opt_set(movie, "streams", "a:0", AV_OPT_SEARCH_CHILDREN), "audio stream") ||
                !Check(avfilter_init_str(movie, nullptr), "open audio source")) { avfilter_inout_free(&outputs); return false; }
            AVFilterInOut* entry = avfilter_inout_alloc();
            if (!entry) { avfilter_inout_free(&outputs); return false; }
            entry->name = av_strdup(name.c_str()); entry->filter_ctx = movie; entry->pad_idx = 0; entry->next = outputs; outputs = entry;
            description << "[" << name << "]asetpts=N/SR/TB,aresample=48000,adelay=" << delays[i]*1000
                        << ":all=1,asetpts=N/SR/TB,apad,atrim=duration=" << duration << "[a" << i << "];";
        }
        for (size_t i=0; i<sources.size(); ++i) description << "[a" << i << "]";
        description << "amix=inputs=" << sources.size() << ":duration=longest,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asetnsamples=n=1024:p=1[sink]";
        if (!Check(avfilter_graph_create_filter(&m_sink, avfilter_get_by_name("abuffersink"), "sink", nullptr, nullptr, m_graph), "audio sink")) { avfilter_inout_free(&outputs); return false; }
        AVFilterInOut* inputs = avfilter_inout_alloc();
        inputs->name = av_strdup("sink"); inputs->filter_ctx = m_sink; inputs->pad_idx = 0;
        int ret = avfilter_graph_parse_ptr(m_graph, description.str().c_str(), &inputs, &outputs, nullptr);
        avfilter_inout_free(&inputs); avfilter_inout_free(&outputs);
        if (!Check(ret, "audio graph parse") || !Check(avfilter_graph_config(m_graph, nullptr), "audio graph config")) return false;
        const AVCodec* codec = avcodec_find_encoder(AV_CODEC_ID_AAC);
        m_audioEncoder = avcodec_alloc_context3(codec);
        if (!m_audioEncoder) return false;
        m_audioEncoder->sample_rate = 48000; m_audioEncoder->sample_fmt = AV_SAMPLE_FMT_FLTP;
        av_channel_layout_default(&m_audioEncoder->ch_layout, 2);
        m_audioEncoder->time_base = {1, 48000}; m_audioEncoder->bit_rate = 192000;
        if (m_outFmtCtx->oformat->flags & AVFMT_GLOBALHEADER) m_audioEncoder->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
        if (!Check(avcodec_open2(m_audioEncoder, codec, nullptr), "open AAC")) return false;
        m_audioStream = avformat_new_stream(m_outFmtCtx, nullptr);
        if (!m_audioStream || !Check(avcodec_parameters_from_context(m_audioStream->codecpar, m_audioEncoder), "AAC parameters")) return false;
        m_audioStream->time_base = m_audioEncoder->time_base;
    }
    if (!(m_outFmtCtx->oformat->flags & AVFMT_NOFILE) && !Check(avio_open(&m_outFmtCtx->pb, output.c_str(), AVIO_FLAG_WRITE), "open output")) return false;
    if(PipelineProfile::Get().enabled && m_outFmtCtx->pb && m_outFmtCtx->pb->write_packet){
        m_originalWrite=m_outFmtCtx->pb->write_packet;outputOwners[m_outFmtCtx->pb->opaque]=this;m_outFmtCtx->pb->write_packet=&AudioMuxer::TimedWrite;
    }
    if (!Check(avformat_write_header(m_outFmtCtx, nullptr), "write header")) return false;
    m_headerWritten = true;
    return true;
}

bool AudioMuxer::WriteVideoPacket(AVPacket* packet, AVRational timeBase) {
    if (packet->duration <= 0) packet->duration = 1;
    av_packet_rescale_ts(packet, timeBase, m_videoStream->time_base);
    packet->stream_index = m_videoStream->index;
    return Check(av_interleaved_write_frame(m_outFmtCtx, packet), "write video packet");
}

bool AudioMuxer::DrainAudio() {
    AVPacket* packet = av_packet_alloc();
    if (!packet) return false;
    int ret;
    bool ok = true;
    while ((ret = avcodec_receive_packet(m_audioEncoder, packet)) == 0) {
        av_packet_rescale_ts(packet, m_audioEncoder->time_base, m_audioStream->time_base);
        packet->stream_index = m_audioStream->index;
        ok = Check(av_interleaved_write_frame(m_outFmtCtx, packet), "write audio packet");
        av_packet_unref(packet);
        if (!ok) break;
    }
    if (ok && ret != AVERROR(EAGAIN) && ret != AVERROR_EOF) ok = Check(ret, "receive audio packet");
    av_packet_free(&packet);
    return ok;
}

bool AudioMuxer::CopyAudioPackets(const std::function<bool()>& cancelled, double durationLimit) {
    if (!m_audioEncoder) return true;
    AVFrame* frame = av_frame_alloc();
    if (!frame) return false;
    int ret; bool ok = true;
    int64_t audioPts = 0;
    while ((ret = av_buffersink_get_frame(m_sink, frame)) >= 0) {
        if (cancelled()) { av_frame_unref(frame); ret=AVERROR_EOF; break; }
        if(durationLimit>=0){
            int64_t remaining=static_cast<int64_t>(std::llround(durationLimit*m_audioEncoder->sample_rate))-audioPts;
            if(remaining<=0){av_frame_unref(frame);ret=AVERROR_EOF;break;}
            if(remaining<frame->nb_samples)frame->nb_samples=static_cast<int>(remaining);
        }
        frame->pts = audioPts;
        audioPts += frame->nb_samples;
        int sent = avcodec_send_frame(m_audioEncoder, frame);
        if (sent == AVERROR(EAGAIN)) {
            ok = DrainAudio();
            if (ok) sent = avcodec_send_frame(m_audioEncoder, frame);
        }
        ok = ok && Check(sent, "send audio frame") && DrainAudio();
        av_frame_unref(frame);
        if (!ok) break;
    }
    if (ok && ret != AVERROR_EOF) ok = Check(ret, "read audio graph");
    if (ok) {
        int sent = avcodec_send_frame(m_audioEncoder, nullptr);
        if (sent == AVERROR(EAGAIN)) { ok = DrainAudio(); if (ok) sent = avcodec_send_frame(m_audioEncoder, nullptr); }
        ok = ok && (sent == AVERROR_EOF || Check(sent, "flush AAC")) && DrainAudio();
    }
    av_frame_free(&frame);
    return ok;
}
