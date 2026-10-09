#pragma once
#include "../third_party/json.hpp"
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <d3d11.h>
#include <fstream>
#include <map>
#include <memory>
#include <numeric>
#include <vector>
#include <wrl/client.h>
// Developer-only; no per-frame stdout and bounded samples/queries.
class PipelineProfile {
public:
  using Clock = std::chrono::steady_clock;
  static PipelineProfile &Get() {
    static PipelineProfile p;
    return p;
  }
  bool enabled = std::getenv("EXPORT_PROFILE") != nullptr;
  int64_t frame = -1;
  Clock::time_point origin = Clock::now();
  std::map<std::string, std::vector<double>> samples, frameSamples;
  std::map<std::string, double> frameTotals;
  const std::vector<std::string> stages = {"DECODE_VIDEO1_SUBMIT_MS",
                                           "DECODE_VIDEO1_WAIT_MS",
                                           "DECODE_VIDEO2_SUBMIT_MS",
                                           "DECODE_VIDEO2_WAIT_MS",
                                           "COMPOSITOR_MS",
                                           "TELEMETRY_RENDER_MS",
                                           "TELEMETRY_UPLOAD_MS",
                                           "GPU_COPY_MS",
                                           "NVENC_REGISTER_MS",
                                           "NVENC_MAP_MS",
                                           "NVENC_ENCODE_SUBMIT_MS",
                                           "NVENC_WAIT_MS",
                                           "NVENC_LOCK_BITSTREAM_MS",
                                           "NVENC_UNLOCK_MS",
                                           "NVENC_UNMAP_MS",
                                           "MUX_VIDEO_MS",
                                           "MUX_AUDIO_MS",
                                           "PREVIEW_READBACK_MS",
                                           "D3D11_FLUSH_MS",
                                           "D3D11_QUERY_WAIT_MS",
                                           "D3D11_QUERY_POLL_MS",
                                           "OTHER_CPU_MS",
                                           "FRAME_TOTAL_MS"};
  void BeginFrame(int64_t index) {
    frame = index;
    if (enabled)
      frameTotals.clear();
  }
  void EndFrame(double total) {
    if (!enabled)
      return;
    double accounted = 0;
    for (const auto &name : stages)
      if (name != "OTHER_CPU_MS" && name != "FRAME_TOTAL_MS")
        accounted += frameTotals[name];
    frameTotals["OTHER_CPU_MS"] = (std::max)(0.0, total - accounted);
    frameTotals["FRAME_TOTAL_MS"] = total;
    for (const auto &name : stages)
      if (frameSamples[name].size() < 30000)
        frameSamples[name].push_back(frameTotals[name]);
    frame = -1;
  }
  nlohmann::json trace = nlohmann::json::array();
  void Add(const std::string &name, double ms) {
    if (enabled) {
      if (samples[name].size() < 30000)
        samples[name].push_back(ms);
      if (frame >= 0)
        frameTotals[name] += ms;
    }
  }
  double Now() const {
    return std::chrono::duration<double, std::milli>(Clock::now() - origin)
        .count();
  }
  void Event(const std::string &name, double start, double end, int64_t index) {
    if (enabled && index >= 0 && index < 300)
      trace.push_back({{"frame_index", index},
                       {"stage", name},
                       {"start_ms", start},
                       {"end_ms", end}});
  }
  struct Scope {
    std::string name;
    Clock::time_point start;
    double traceStart;
    int64_t index;
    bool active = true;
    Scope(const std::string &n)
        : name(n), start(Clock::now()), traceStart(Get().Now()),
          index(Get().frame) {}
    void Stop() {
      if (!active)
        return;
      active = false;
      auto &p = Get();
      if (p.enabled) {
        double ms =
            std::chrono::duration<double, std::milli>(Clock::now() - start)
                .count();
        p.Add(name, ms);
        p.Event(name, traceStart, p.Now(), index);
      }
    }
    ~Scope() { Stop(); }
  };
  struct FrameScope {
    Clock::time_point start = Clock::now();
    explicit FrameScope(int64_t index) { Get().BeginFrame(index); }
    ~FrameScope() {
      Get().EndFrame(
          std::chrono::duration<double, std::milli>(Clock::now() - start)
              .count());
    }
  };
  struct GpuRecord {
    std::string name;
    Microsoft::WRL::ComPtr<ID3D11Query> disjoint, begin, end;
    bool ended = false;
  };
  std::vector<std::shared_ptr<GpuRecord>> pending;
  struct GpuScope {
    ID3D11DeviceContext *context;
    std::shared_ptr<GpuRecord> r;
    GpuScope(ID3D11Device *device, ID3D11DeviceContext *c,
             const std::string &name)
        : context(c) {
      auto &p = Get();
      if (!p.enabled || p.pending.size() >= 256)
        return;
      r = std::make_shared<GpuRecord>();
      r->name = name;
      D3D11_QUERY_DESC d{D3D11_QUERY_TIMESTAMP_DISJOINT, 0};
      if (FAILED(device->CreateQuery(&d, &r->disjoint))) {
        r.reset();
        return;
      }
      d.Query = D3D11_QUERY_TIMESTAMP;
      if (FAILED(device->CreateQuery(&d, &r->begin)) ||
          FAILED(device->CreateQuery(&d, &r->end))) {
        r.reset();
        return;
      }
      c->Begin(r->disjoint.Get());
      c->End(r->begin.Get());
      p.pending.push_back(r);
    }
    ~GpuScope() {
      if (r) {
        context->End(r->end.Get());
        context->End(r->disjoint.Get());
        r->ended = true;
      }
    }
  };
  void Poll(ID3D11DeviceContext *c) {
    if (!enabled)
      return;
    Scope poll("D3D11_QUERY_POLL_MS");
    for (auto it = pending.begin(); it != pending.end();) {
      auto &r = **it;
      D3D11_QUERY_DATA_TIMESTAMP_DISJOINT d{};
      UINT64 a = 0, b = 0;
      if (!r.ended ||
          c->GetData(r.disjoint.Get(), &d, sizeof(d),
                     D3D11_ASYNC_GETDATA_DONOTFLUSH) != S_OK ||
          c->GetData(r.begin.Get(), &a, sizeof(a),
                     D3D11_ASYNC_GETDATA_DONOTFLUSH) != S_OK ||
          c->GetData(r.end.Get(), &b, sizeof(b),
                     D3D11_ASYNC_GETDATA_DONOTFLUSH) != S_OK) {
        ++it;
        continue;
      }
      if (!d.Disjoint && d.Frequency && b >= a)
        Add(r.name, 1000.0 * (b - a) / d.Frequency);
      it = pending.erase(it);
    }
  }
  ~PipelineProfile() {
    if (!enabled)
      return;
    nlohmann::json report;
    for (auto &[name, v] : samples) {
      if (v.empty())
        continue;
      std::sort(v.begin(), v.end());
      auto q = [&](double f) { return v[size_t(f * (v.size() - 1))]; };
      report[name] = {
          {"count", v.size()},
          {"avg", std::accumulate(v.begin(), v.end(), 0.0) / v.size()},
          {"median", q(.5)},
          {"p90", q(.9)},
          {"p99", q(.99)},
          {"max", v.back()}};
    }
    for (auto &[name, v] : frameSamples) {
      if (v.empty())
        continue;
      std::sort(v.begin(), v.end());
      auto q = [&](double f) { return v[size_t(f * (v.size() - 1))]; };
      report[name]["per_frame"] = {
          {"count", v.size()},
          {"avg", std::accumulate(v.begin(), v.end(), 0.0) / v.size()},
          {"median", q(.5)},
          {"p90", q(.9)},
          {"p99", q(.99)},
          {"max", v.back()}};
    }
    report["unresolved_gpu_queries"] = pending.size();
    const char *path = std::getenv("EXPORT_PROFILE");
    std::string base =
        (path && *path && std::string(path) != "1") ? path : "export_pipeline";
    std::ofstream(base + "_profile.json") << report.dump(2);
    std::ofstream(base + "_trace.json") << trace.dump(2);
    std::ofstream csv(base + "_trace.csv");
    csv << "frame_index,stage,start_ms,end_ms\n";
    for (const auto &row : trace)
      csv << row["frame_index"] << "," << row["stage"].get<std::string>() << ","
          << row["start_ms"] << "," << row["end_ms"] << "\n";
  }
};
