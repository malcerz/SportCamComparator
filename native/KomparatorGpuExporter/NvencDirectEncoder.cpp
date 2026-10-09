#include "NvencDirectEncoder.h"
#include "PipelineProfile.h"
#include <algorithm>
#include <cassert>
#include <iostream>

NvencDirectEncoder::NvencDirectEncoder() {}

NvencDirectEncoder::~NvencDirectEncoder() { Shutdown(); }

void NvencDirectEncoder::Shutdown() {
  // EOS drains accepted frames before any texture is released, including error
  // paths.
  if (m_initialized && !m_flushed)
    Flush();
  if (m_flushed && m_async && !m_eosComplete && m_eosEvent)
    m_eosComplete = WaitForSingleObject(m_eosEvent, 30000) == WAIT_OBJECT_0;
  if (m_hEncoder) {
    for (auto &slot : m_slots) {
      if (slot.bitstreamLocked)
        m_nvenc.nvEncUnlockBitstream(m_hEncoder, slot.bs);
      if (slot.mapped)
        m_nvenc.nvEncUnmapInputResource(m_hEncoder, slot.mapped);
      if (slot.eventRegistered) {
        NV_ENC_EVENT_PARAMS e{};
        e.version = NV_ENC_EVENT_PARAMS_VER;
        e.completionEvent = slot.event;
        m_nvenc.nvEncUnregisterAsyncEvent(m_hEncoder, &e);
      }
      if (slot.registered)
        m_nvenc.nvEncUnregisterResource(m_hEncoder, slot.registered);
      if (slot.bs)
        m_nvenc.nvEncDestroyBitstreamBuffer(m_hEncoder, slot.bs);
    }
    if (m_eosRegistered) {
      NV_ENC_EVENT_PARAMS e{};
      e.version = NV_ENC_EVENT_PARAMS_VER;
      e.completionEvent = m_eosEvent;
      m_nvenc.nvEncUnregisterAsyncEvent(m_hEncoder, &e);
      m_eosRegistered = false;
    }
    m_nvenc.nvEncDestroyEncoder(m_hEncoder);
    m_hEncoder = nullptr;
  }
  for (auto &slot : m_slots) {
    if (slot.texture)
      slot.texture->Release();
    if (slot.event)
      CloseHandle(slot.event);
  }
  m_slots.clear();
  if (m_eosEvent) {
    CloseHandle(m_eosEvent);
    m_eosEvent = nullptr;
  }
  while (!m_freeSlots.empty())
    m_freeSlots.pop();
  while (!m_inFlight.empty())
    m_inFlight.pop();
  while (!m_readyPackets.empty())
    m_readyPackets.pop();
  if (m_hNvencDll) {
    FreeLibrary(m_hNvencDll);
    m_hNvencDll = nullptr;
  }
  m_initialized = false;
  m_flushed = false;
  m_eosComplete = false;
  m_error = 0;
  m_peakInFlight = 0;
}

bool NvencDirectEncoder::Initialize(ID3D11Device *device,
                                    ID3D11DeviceContext *context, int width,
                                    int height, AVRational timeBase,
                                    AVRational framerate, int64_t bitrate,
                                    const std::string &preset) {
  Shutdown();

  m_device = device;
  m_context = context;
  m_width = width;
  m_height = height;
  m_timeBase = timeBase;
  m_framerate = framerate;

  if (!m_device || !m_context) {
    m_lastFailureReason = "NVENC_INVALID_DEVICE";
    m_lastFailureDetails = "D3D11 device or context is null";
    return false;
  }

  m_hNvencDll = LoadLibraryW(L"nvEncodeAPI64.dll");
  if (!m_hNvencDll) {
    m_lastFailureReason = "NVENC_DLL_NOT_FOUND";
    m_lastFailureDetails = "nvEncodeAPI64.dll not found in system";
    return false;
  }

  typedef NVENCSTATUS(NVENCAPI * PFN_NvEncodeAPICreateInstance)(
      NV_ENCODE_API_FUNCTION_LIST *);
  PFN_NvEncodeAPICreateInstance pfnCreate =
      (PFN_NvEncodeAPICreateInstance)(void *)GetProcAddress(
          m_hNvencDll, "NvEncodeAPICreateInstance");
  if (!pfnCreate) {
    m_lastFailureReason = "NVENC_ENTRY_POINT_NOT_FOUND";
    m_lastFailureDetails = "NvEncodeAPICreateInstance not found";
    return false;
  }

  m_nvenc.version = NV_ENCODE_API_FUNCTION_LIST_VER;
  NVENCSTATUS status = pfnCreate(&m_nvenc);
  if (status != NV_ENC_SUCCESS) {
    m_lastFailureReason = "NVENC_API_INIT_FAILED";
    m_lastFailureDetails =
        "NvEncodeAPICreateInstance failed with code " + std::to_string(status);
    return false;
  }

  // Negotiate NVENC API 13.0 for Pascal / driver 582.78 compatibility
  NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS openParams{};
  openParams.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
  openParams.deviceType = NV_ENC_DEVICE_TYPE_DIRECTX;
  openParams.device = m_device;
  openParams.apiVersion = NVENCAPI_VERSION;

  status = m_nvenc.nvEncOpenEncodeSessionEx(&openParams, &m_hEncoder);
  if (status != NV_ENC_SUCCESS) {
    m_lastFailureReason = "NVENC_OPEN_SESSION_FAILED";
    m_lastFailureDetails =
        "nvEncOpenEncodeSessionEx failed with code " + std::to_string(status);
    return false;
  }

  // Select preset GUID
  GUID presetGuid = NV_ENC_PRESET_P4_GUID;
  NV_ENC_TUNING_INFO tuningInfo = NV_ENC_TUNING_INFO_HIGH_QUALITY;
  if (preset == "speed" || preset == "fast" || preset == "Najszybszy") {
    presetGuid = NV_ENC_PRESET_P2_GUID;
    tuningInfo = NV_ENC_TUNING_INFO_LOW_LATENCY;
  } else if (preset == "quality" || preset == "best" ||
             preset == "Najlepsza jakość") {
    presetGuid = NV_ENC_PRESET_P6_GUID;
    tuningInfo = NV_ENC_TUNING_INFO_HIGH_QUALITY;
  }

  NV_ENC_PRESET_CONFIG presetCfg{};
  presetCfg.version = NV_ENC_PRESET_CONFIG_VER;
  presetCfg.presetCfg.version = NV_ENC_CONFIG_VER;
  status = m_nvenc.nvEncGetEncodePresetConfigEx(
      m_hEncoder, NV_ENC_CODEC_HEVC_GUID, presetGuid, tuningInfo, &presetCfg);
  if (status != NV_ENC_SUCCESS) {
    m_lastFailureReason = "NVENC_PRESET_CONFIG_FAILED";
    m_lastFailureDetails = "nvEncGetEncodePresetConfigEx failed with code " +
                           std::to_string(status);
    return false;
  }

  uint32_t targetBps = bitrate > 0 ? (uint32_t)bitrate : 20000000;
  NV_ENC_CONFIG encConfig = presetCfg.presetCfg;
  encConfig.profileGUID = NV_ENC_HEVC_PROFILE_MAIN_GUID;
  encConfig.rcParams.rateControlMode = NV_ENC_PARAMS_RC_VBR;
  encConfig.rcParams.averageBitRate = targetBps;
  encConfig.rcParams.maxBitRate = targetBps + targetBps / 4;
  encConfig.gopLength =
      (uint32_t)std::max(1.0, av_q2d(framerate) * 2.0); // 2-second GOP
  encConfig.frameIntervalP = 1; // Strict low-latency 1-to-1 frames (I/P only)
  encConfig.encodeCodecConfig.hevcConfig.repeatSPSPPS =
      1; // In-band VPS/SPS/PPS on each IDR

  if (preset == "quality" || preset == "best" || preset == "Najlepsza jakość") {
    encConfig.rcParams.enableAQ = 1;
    encConfig.rcParams.aqStrength = 8;
  }

  NV_ENC_INITIALIZE_PARAMS initParams{};
  initParams.version = NV_ENC_INITIALIZE_PARAMS_VER;
  initParams.encodeGUID = NV_ENC_CODEC_HEVC_GUID;
  initParams.presetGUID = presetGuid;
  initParams.encodeWidth = m_width;
  initParams.encodeHeight = m_height;
  initParams.darWidth = m_width;
  initParams.darHeight = m_height;
  initParams.frameRateNum = framerate.num > 0 ? framerate.num : 30;
  initParams.frameRateDen = framerate.den > 0 ? framerate.den : 1;
  const char *mode = std::getenv("PIPELINE_MODE");
  m_syncMode = mode && std::string(mode) == "SYNC";
  NV_ENC_CAPS_PARAM caps{};
  caps.version = NV_ENC_CAPS_PARAM_VER;
  caps.capsToQuery = NV_ENC_CAPS_ASYNC_ENCODE_SUPPORT;
  int asyncSupport = 0;
  m_async =
      !m_syncMode && !std::getenv("NVENC_DISABLE_ASYNC_EVENTS") &&
      m_nvenc.nvEncGetEncodeCaps(m_hEncoder, NV_ENC_CODEC_HEVC_GUID, &caps,
                                 &asyncSupport) == NV_ENC_SUCCESS &&
      asyncSupport != 0;
  initParams.enableEncodeAsync = m_async ? 1 : 0;
  caps.capsToQuery = NV_ENC_CAPS_NUM_ENCODER_ENGINES;
  int engineCount = 0;
  if (m_nvenc.nvEncGetEncodeCaps(m_hEncoder, NV_ENC_CODEC_HEVC_GUID, &caps,
                                 &engineCount) == NV_ENC_SUCCESS)
    std::cerr << "NVENC_ENGINE_COUNT=" << engineCount << std::endl;
  initParams.enablePTD = 1;
  initParams.tuningInfo = tuningInfo;
  initParams.encodeConfig = &encConfig;

  status = m_nvenc.nvEncInitializeEncoder(m_hEncoder, &initParams);
  if (m_async && (status == NV_ENC_ERR_UNSUPPORTED_PARAM ||
                  status == NV_ENC_ERR_INVALID_PARAM)) {
    initParams.enableEncodeAsync = 0;
    status = m_nvenc.nvEncInitializeEncoder(m_hEncoder, &initParams);
    if (status == NV_ENC_SUCCESS) {
      m_async = false;
      std::cerr << "NVENC_ASYNC_EVENTS_UNAVAILABLE_USING_BOUNDED_SYNC_API_QUEUE"
                << std::endl;
    }
  }

  if (status != NV_ENC_SUCCESS) {
    m_lastFailureReason = "NVENC_INIT_ENCODER_FAILED";
    m_lastFailureDetails =
        "nvEncInitializeEncoder failed with code " + std::to_string(status);
    return false;
  }

  // Separate registered inputs remain mapped until their bitstreams are
  // consumed.
  size_t depth = 4;
  if (const char *value = std::getenv("NVENC_RING_DEPTH"))
    depth = (std::max)(
        size_t(1),
        (std::min)(size_t(12), size_t((std::max)(1, std::atoi(value)))));
  if (m_syncMode)
    depth = 1;
  if (m_async) {
    m_eosEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    NV_ENC_EVENT_PARAMS e{};
    e.version = NV_ENC_EVENT_PARAMS_VER;
    e.completionEvent = m_eosEvent;
    if (!m_eosEvent ||
        m_nvenc.nvEncRegisterAsyncEvent(m_hEncoder, &e) != NV_ENC_SUCCESS) {
      m_lastFailureReason = "NVENC_EOS_EVENT_FAILED";
      return false;
    }
    m_eosRegistered = true;
  }
  m_slots.resize(depth);
  for (size_t i = 0; i < depth; ++i) {
    auto &slot = m_slots[i];
    D3D11_TEXTURE2D_DESC d{};
    d.Width = m_width;
    d.Height = m_height;
    d.MipLevels = 1;
    d.ArraySize = 1;
    d.Format = DXGI_FORMAT_NV12;
    d.SampleDesc.Count = 1;
    d.Usage = D3D11_USAGE_DEFAULT;
    d.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    if (FAILED(m_device->CreateTexture2D(&d, nullptr, &slot.texture))) {
      m_lastFailureReason = "NVENC_TEXTURE_CREATE_FAILED";
      return false;
    }
    NV_ENC_REGISTER_RESOURCE reg{};
    reg.version = NV_ENC_REGISTER_RESOURCE_VER;
    reg.resourceType = NV_ENC_INPUT_RESOURCE_TYPE_DIRECTX;
    reg.width = m_width;
    reg.height = m_height;
    reg.resourceToRegister = slot.texture;
    reg.bufferFormat = NV_ENC_BUFFER_FORMAT_NV12;
    reg.bufferUsage = NV_ENC_INPUT_IMAGE;
    {
      PipelineProfile::Scope measure("NVENC_REGISTER_MS");
      status = m_nvenc.nvEncRegisterResource(m_hEncoder, &reg);
    }
    if (status != NV_ENC_SUCCESS) {
      m_lastFailureReason = "NVENC_REGISTER_RESOURCE_FAILED";
      return false;
    }
    slot.registered = reg.registeredResource;
    NV_ENC_CREATE_BITSTREAM_BUFFER bs{};
    bs.version = NV_ENC_CREATE_BITSTREAM_BUFFER_VER;
    if (m_nvenc.nvEncCreateBitstreamBuffer(m_hEncoder, &bs) != NV_ENC_SUCCESS) {
      m_lastFailureReason = "NVENC_BITSTREAM_ALLOC_FAILED";
      return false;
    }
    slot.bs = bs.bitstreamBuffer;
    if (m_async) {
      slot.event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
      NV_ENC_EVENT_PARAMS e{};
      e.version = NV_ENC_EVENT_PARAMS_VER;
      e.completionEvent = slot.event;
      if (!slot.event ||
          m_nvenc.nvEncRegisterAsyncEvent(m_hEncoder, &e) != NV_ENC_SUCCESS) {
        m_lastFailureReason = "NVENC_EVENT_REGISTER_FAILED";
        return false;
      }
      slot.eventRegistered = true;
    }
    m_freeSlots.push(i);
  }
  std::cerr << "[NvencDirectEncoder] API13.0 async=" << m_async
            << " ring_depth=" << depth << " I/P only (unchanged)" << std::endl;
  m_initialized = true;
  return true;
}

bool NvencDirectEncoder::DrainBitstream(bool wait) {
  if (m_inFlight.empty() || m_error)
    return false;
  size_t index = m_inFlight.front();
  auto &slot = m_slots[index];
  assert(slot.state == SlotState::Submitted);
  if (m_async) {
    PipelineProfile::Scope measure("NVENC_WAIT_MS");
    DWORD result = WaitForSingleObject(slot.event, wait ? 30000 : 0);
    if (result == WAIT_TIMEOUT) {
      if (wait) {
        std::cerr << "NVENC event timeout pts=" << slot.pts << std::endl;
        m_error = AVERROR_EXTERNAL;
      }
      return false;
    }
    if (result != WAIT_OBJECT_0) {
      m_error = AVERROR_EXTERNAL;
      return false;
    }
  }
  slot.state = SlotState::BitstreamReady;
  NV_ENC_LOCK_BITSTREAM lock{};
  lock.version = NV_ENC_LOCK_BITSTREAM_VER;
  lock.outputBitstream = slot.bs;
  // In sync mode the driver owns completion; doNotWait=0 is the SDK contract.
  lock.doNotWait = m_async ? 1 : (wait ? 0 : 1);
  NVENCSTATUS status;
  {
    PipelineProfile::Scope measure("NVENC_LOCK_BITSTREAM_MS");
    status = m_nvenc.nvEncLockBitstream(m_hEncoder, &lock);
  }
  if (status == NV_ENC_ERR_LOCK_BUSY || status == NV_ENC_ERR_ENCODER_BUSY) {
    slot.state = SlotState::Submitted;
    if (m_async)
      SetEvent(slot.event);
    return false;
  }
  if (status != NV_ENC_SUCCESS) {
    std::cerr << "NVENC drain status=" << status << " pts=" << slot.pts
              << std::endl;
    m_error = AVERROR_EXTERNAL;
    return false;
  }
  slot.bitstreamLocked = true;
  EncodedPacketData packet;
  packet.data.assign(static_cast<uint8_t *>(lock.bitstreamBufferPtr),
                     static_cast<uint8_t *>(lock.bitstreamBufferPtr) +
                         lock.bitstreamSizeInBytes);
  packet.pts = static_cast<int64_t>(lock.outputTimeStamp);
  packet.dts = packet.pts;
  packet.isKeyFrame = lock.pictureType == NV_ENC_PIC_TYPE_IDR ||
                      lock.pictureType == NV_ENC_PIC_TYPE_I;
  PipelineProfile::Get().Event("ENCODE_IN_FLIGHT", slot.submittedMs,
                               PipelineProfile::Get().Now(), slot.pts);
  {
    PipelineProfile::Scope measure("NVENC_UNLOCK_MS");
    status = m_nvenc.nvEncUnlockBitstream(m_hEncoder, slot.bs);
  }
  if (status != NV_ENC_SUCCESS) {
    std::cerr << "NVENC drain status=" << status << " pts=" << slot.pts
              << std::endl;
    m_error = AVERROR_EXTERNAL;
    return false;
  }
  slot.bitstreamLocked = false;
  {
    PipelineProfile::Scope measure("NVENC_UNMAP_MS");
    status = m_nvenc.nvEncUnmapInputResource(m_hEncoder, slot.mapped);
  }
  if (status != NV_ENC_SUCCESS) {
    std::cerr << "NVENC drain status=" << status << " pts=" << slot.pts
              << std::endl;
    m_error = AVERROR_EXTERNAL;
    return false;
  }
  slot.mapped = nullptr;
  // The owned CPU packet survives muxing; only GPU resources are now free.
  slot.state = SlotState::Free;
  m_inFlight.pop();
  m_freeSlots.push(index);
  m_readyPackets.push(std::move(packet));
  return true;
}

int NvencDirectEncoder::SendFrame(ID3D11Texture2D *composedTex, int64_t pts,
                                  bool, const std::atomic<bool> *cancelled) {
  if (!m_initialized || m_flushed || !composedTex)
    return AVERROR(EINVAL);
  if (m_error)
    return m_error;
  // Backpressure only when all bounded slots are occupied.
  if (m_freeSlots.empty() && !DrainBitstream(true))
    return m_error ? m_error : AVERROR(EAGAIN);
  if (cancelled && cancelled->load())
    return AVERROR_EXIT;
  size_t index = m_freeSlots.front();
  auto &slot = m_slots[index];
  assert(slot.state == SlotState::Free && !slot.mapped);
  slot.state = SlotState::Compositing;
  {
    PipelineProfile::Scope cpu("GPU_COPY_MS");
    PipelineProfile::GpuScope gpu(m_device, m_context, "GPU_COPY_GPU_MS");
    m_context->CopySubresourceRegion(slot.texture, 0, 0, 0, 0, composedTex, 0,
                                     nullptr);
  }
  NV_ENC_MAP_INPUT_RESOURCE map{};
  map.version = NV_ENC_MAP_INPUT_RESOURCE_VER;
  map.registeredResource = slot.registered;
  NVENCSTATUS status;
  {
    PipelineProfile::Scope measure("NVENC_MAP_MS");
    status = m_nvenc.nvEncMapInputResource(m_hEncoder, &map);
  }
  if (status != NV_ENC_SUCCESS) {
    slot.state = SlotState::Free;
    return AVERROR_EXTERNAL;
  }
  slot.mapped = map.mappedResource;
  slot.pts = pts;
  NV_ENC_PIC_PARAMS pic{};
  pic.version = NV_ENC_PIC_PARAMS_VER;
  pic.inputWidth = m_width;
  pic.inputHeight = m_height;
  pic.inputPitch = m_width;
  pic.inputBuffer = slot.mapped;
  pic.outputBitstream = slot.bs;
  pic.bufferFmt = map.mappedBufferFmt;
  pic.pictureStruct = NV_ENC_PIC_STRUCT_FRAME;
  pic.frameIdx = static_cast<uint32_t>(pts);
  pic.inputTimeStamp = pts;
  pic.completionEvent = slot.event;
  if (cancelled && cancelled->load()) {
    m_nvenc.nvEncUnmapInputResource(m_hEncoder, slot.mapped);
    slot.mapped = nullptr;
    slot.state = SlotState::Free;
    return AVERROR_EXIT;
  }
  slot.submittedMs = PipelineProfile::Get().Now();
  {
    PipelineProfile::Scope measure("NVENC_ENCODE_SUBMIT_MS");
    status = m_nvenc.nvEncEncodePicture(m_hEncoder, &pic);
  }
  if (status != NV_ENC_SUCCESS && status != NV_ENC_ERR_NEED_MORE_INPUT) {
    m_nvenc.nvEncUnmapInputResource(m_hEncoder, slot.mapped);
    slot.mapped = nullptr;
    slot.state = SlotState::Free;
    return AVERROR_EXTERNAL;
  }
  m_freeSlots.pop();
  slot.state = SlotState::Submitted;
  m_inFlight.push(index);
  m_peakInFlight = (std::max)(m_peakInFlight, m_inFlight.size());
  if (m_syncMode && !DrainBitstream(true))
    return m_error ? m_error : AVERROR_EXTERNAL;
  return 0;
}

int NvencDirectEncoder::ReceivePacket(AVPacket *pkt) {
  if (!m_initialized)
    return AVERROR(EINVAL);
  if (m_error)
    return m_error;
  // Do not collect immediately after every submit; first fill the ring.
  if (m_readyPackets.empty() &&
      (m_flushed || (m_async && m_inFlight.size() >= m_slots.size())))
    DrainBitstream(false);
  if (m_error)
    return m_error;
  if (m_readyPackets.empty())
    return m_flushed && m_inFlight.empty() ? AVERROR_EOF : AVERROR(EAGAIN);
  auto item = std::move(m_readyPackets.front());
  m_readyPackets.pop();
  int ret = av_new_packet(pkt, static_cast<int>(item.data.size()));
  if (ret < 0)
    return ret;
  memcpy(pkt->data, item.data.data(), item.data.size());
  pkt->pts = item.pts;
  pkt->dts = item.dts;
  if (item.isKeyFrame)
    pkt->flags |= AV_PKT_FLAG_KEY;
  return 0;
}

int NvencDirectEncoder::Flush() {
  if (!m_initialized)
    return AVERROR(EINVAL);
  if (!m_flushed) {
    NV_ENC_PIC_PARAMS eos{};
    eos.version = NV_ENC_PIC_PARAMS_VER;
    eos.encodePicFlags = NV_ENC_PIC_FLAG_EOS;
    eos.completionEvent = m_eosEvent;
    NVENCSTATUS status = m_nvenc.nvEncEncodePicture(m_hEncoder, &eos);
    if (status != NV_ENC_SUCCESS) {
      std::cerr << "NVENC EOS status=" << status << std::endl;
      return AVERROR_EXTERNAL;
    }
    m_flushed = true;
  }
  while (!m_inFlight.empty()) {
    if (!DrainBitstream(true))
      return m_error ? m_error : AVERROR_EXTERNAL;
  }
  if (m_async && !m_eosComplete) {
    PipelineProfile::Scope measure("NVENC_WAIT_MS");
    m_eosComplete = WaitForSingleObject(m_eosEvent, 30000) == WAIT_OBJECT_0;
    if (!m_eosComplete)
      return AVERROR_EXTERNAL;
  }
  std::cerr << "NVENC_PEAK_IN_FLIGHT=" << m_peakInFlight << std::endl;
  return 0;
}
