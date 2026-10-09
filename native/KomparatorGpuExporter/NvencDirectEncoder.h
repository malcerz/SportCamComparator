#pragma once

#include <atomic>
#include <cstdint>
#include <d3d11.h>
#include <queue>
#include <string>
#include <vector>
#include <windows.h>

#include "../third_party/nvEncodeAPI.h"

extern "C" {
#include <libavcodec/avcodec.h>
}

class NvencDirectEncoder {
public:
  NvencDirectEncoder();
  ~NvencDirectEncoder();

  bool Initialize(ID3D11Device *device, ID3D11DeviceContext *context, int width,
                  int height, AVRational timeBase, AVRational framerate,
                  int64_t bitrate, const std::string &preset = "balanced");

  int SendFrame(ID3D11Texture2D *composedTex, int64_t pts, bool retry = false,
                const std::atomic<bool> *cancelled = nullptr);
  int ReceivePacket(AVPacket *pkt);
  int Flush();
  void Shutdown();

  size_t RingDepth() const { return m_slots.size(); }
  size_t PeakInFlight() const { return m_peakInFlight; }
  bool AsyncEvents() const { return m_async; }
  bool IsInitialized() const { return m_initialized; }
  const std::string &GetLastFailureReason() const {
    return m_lastFailureReason;
  }
  const std::string &GetLastFailureDetails() const {
    return m_lastFailureDetails;
  }

private:
  struct EncodedPacketData {
    std::vector<uint8_t> data;
    int64_t pts = 0;
    int64_t dts = 0;
    bool isKeyFrame = false;
  };

  bool m_initialized = false;
  bool m_flushed = false;
  std::string m_lastFailureReason;
  std::string m_lastFailureDetails;

  int m_width = 0;
  int m_height = 0;
  AVRational m_timeBase{1, 30};
  AVRational m_framerate{30, 1};

  HMODULE m_hNvencDll = nullptr;
  NV_ENCODE_API_FUNCTION_LIST m_nvenc{};
  void *m_hEncoder = nullptr;

  ID3D11Device *m_device = nullptr;
  ID3D11DeviceContext *m_context = nullptr;
  enum class SlotState { Free, Compositing, Submitted, BitstreamReady };
  struct Slot {
    ID3D11Texture2D *texture = nullptr;
    NV_ENC_REGISTERED_PTR registered = nullptr;
    NV_ENC_INPUT_PTR mapped = nullptr;
    NV_ENC_OUTPUT_PTR bs = nullptr;
    HANDLE event = nullptr;
    bool eventRegistered = false;
    bool bitstreamLocked = false;
    SlotState state = SlotState::Free;
    int64_t pts = 0;
    double submittedMs = 0;
  };
  std::vector<Slot> m_slots;
  std::queue<size_t> m_freeSlots;
  std::queue<size_t> m_inFlight;
  HANDLE m_eosEvent = nullptr;
  bool m_eosRegistered = false;
  bool m_eosComplete = false;
  bool m_async = false;
  bool m_syncMode = false;
  int m_error = 0;
  size_t m_peakInFlight = 0;
  std::queue<EncodedPacketData> m_readyPackets;

  bool DrainBitstream(bool wait);
};
