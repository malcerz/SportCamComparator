#include "D3D11Context.h"
#include <iostream>
#include <cstdarg>
#include <vector>

D3D11Context::D3D11Context() {
}

D3D11Context::~D3D11Context() {
    if (m_hwDeviceCtx) {
        av_buffer_unref(&m_hwDeviceCtx);
    }
}

bool D3D11Context::Initialize(const std::string& requestedVendor, bool enableDebug) {
    UINT flags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT | D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    if (enableDebug) {
        flags |= D3D11_CREATE_DEVICE_DEBUG;
    }

    D3D_FEATURE_LEVEL featureLevels[] = {
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0
    };
    D3D_FEATURE_LEVEL featureLevel;

    ComPtr<IDXGIFactory1> factory;
    HRESULT hr = CreateDXGIFactory1(IID_PPV_ARGS(&factory));
    ComPtr<IDXGIAdapter1> selectedAdapter;
    ComPtr<IDXGIAdapter1> adapter;

    UINT targetVendorId = 0;
    std::string v = requestedVendor;
    for (auto& c : v) c = (char)tolower(c);
    if (v.find("amd") != std::string::npos || v.find("amf") != std::string::npos) targetVendorId = 0x1002;
    else if (v.find("intel") != std::string::npos || v.find("qsv") != std::string::npos) targetVendorId = 0x8086;
    else if (v.find("nvidia") != std::string::npos || v.find("nvenc") != std::string::npos) targetVendorId = 0x10DE;

    if (factory) {
        std::vector<ComPtr<IDXGIAdapter1>> hardwareAdapters;
        for (UINT i = 0; factory->EnumAdapters1(i, &adapter) != DXGI_ERROR_NOT_FOUND; ++i) {
            DXGI_ADAPTER_DESC1 desc;
            adapter->GetDesc1(&desc);
            if (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) continue;
            hardwareAdapters.push_back(adapter);

            if (targetVendorId != 0 && desc.VendorId == targetVendorId) {
                selectedAdapter = adapter;
                m_adapterDescription = desc.Description;
                m_vendorId = desc.VendorId;
                m_deviceId = desc.DeviceId;
                m_adapterLuid = desc.AdapterLuid;
                break;
            }
        }

        if (!selectedAdapter && !hardwareAdapters.empty()) {
            if (targetVendorId == 0) {
                // If auto, pick first discrete GPU (AMD or NVIDIA), or first hardware GPU
                for (const auto& a : hardwareAdapters) {
                    DXGI_ADAPTER_DESC1 desc;
                    a->GetDesc1(&desc);
                    if (desc.VendorId == 0x1002 || desc.VendorId == 0x10DE) {
                        selectedAdapter = a;
                        m_adapterDescription = desc.Description;
                        m_vendorId = desc.VendorId;
                        m_deviceId = desc.DeviceId;
                        m_adapterLuid = desc.AdapterLuid;
                        break;
                    }
                }
            }
            if (!selectedAdapter) {
                selectedAdapter = hardwareAdapters[0];
                DXGI_ADAPTER_DESC1 desc;
                selectedAdapter->GetDesc1(&desc);
                m_adapterDescription = desc.Description;
                m_vendorId = desc.VendorId;
                m_deviceId = desc.DeviceId;
                m_adapterLuid = desc.AdapterLuid;
            }
        }
    }

    char luidStr[64] = "0:0";
    snprintf(luidStr, sizeof(luidStr), "%08x:%08x", (unsigned)m_adapterLuid.HighPart, (unsigned)m_adapterLuid.LowPart);

    if (m_vendorId == 0x8086) {
        std::wcout << L"[D3D11] INTEL_DXGI_ADAPTER: " << m_adapterDescription << std::endl;
        std::cout << "[D3D11] INTEL_VENDOR_ID: 0x8086" << std::endl;
        std::cout << "[D3D11] INTEL_DEVICE_ID: 0x" << std::hex << m_deviceId << std::dec << std::endl;
        std::cout << "[D3D11] INTEL_LUID: " << luidStr << std::endl;
    } else if (m_vendorId == 0x10DE) {
        std::wcout << L"[D3D11] NVIDIA_DXGI_ADAPTER: " << m_adapterDescription << std::endl;
        std::cout << "[D3D11] NVIDIA_VENDOR_ID: 0x10de" << std::endl;
        std::cout << "[D3D11] NVIDIA_DEVICE_ID: 0x" << std::hex << m_deviceId << std::dec << std::endl;
        std::cout << "[D3D11] NVIDIA_LUID: " << luidStr << std::endl;
    } else if (m_vendorId == 0x1002) {
        std::wcout << L"[D3D11] AMD_DXGI_ADAPTER: " << m_adapterDescription << std::endl;
        std::cout << "[D3D11] AMD_VENDOR_ID: 0x1002" << std::endl;
        std::cout << "[D3D11] AMD_DEVICE_ID: 0x" << std::hex << m_deviceId << std::dec << std::endl;
        std::cout << "[D3D11] AMD_LUID: " << luidStr << std::endl;
    }

    D3D_DRIVER_TYPE driverType = selectedAdapter ? D3D_DRIVER_TYPE_UNKNOWN : D3D_DRIVER_TYPE_HARDWARE;

    hr = D3D11CreateDevice(
        selectedAdapter.Get(),
        driverType,
        nullptr,
        flags,
        featureLevels,
        2,
        D3D11_SDK_VERSION,
        &m_device,
        &featureLevel,
        &m_context
    );

    if (FAILED(hr)) {
        if (flags & D3D11_CREATE_DEVICE_DEBUG) {
            flags &= ~D3D11_CREATE_DEVICE_DEBUG;
            hr = D3D11CreateDevice(
                selectedAdapter.Get(),
                driverType,
                nullptr,
                flags,
                featureLevels,
                2,
                D3D11_SDK_VERSION,
                &m_device,
                &featureLevel,
                &m_context
            );
        }
    }

    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"D3D11CreateDevice failed with HR: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    // Enable multithread protection on D3D11 context
    hr = m_device->QueryInterface(__uuidof(ID3D11Multithread), (void**)&m_multithread);
    if (SUCCEEDED(hr) && m_multithread) {
        m_multithread->SetMultithreadProtected(TRUE);
    }

    // Query VideoDevice and VideoContext
    hr = m_device->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&m_videoDevice);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"ID3D11VideoDevice interface not supported on this adapter.\"}" << std::endl;
        return false;
    }

    hr = m_context->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&m_videoContext);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"ID3D11VideoContext interface not supported on this adapter.\"}" << std::endl;
        return false;
    }

    // Allocate and initialize FFmpeg D3D11VA hwdevice context
    m_hwDeviceCtx = av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_D3D11VA);
    if (!m_hwDeviceCtx) {
        std::cerr << "{\"type\":\"error\",\"message\":\"av_hwdevice_ctx_alloc(D3D11VA) failed.\"}" << std::endl;
        return false;
    }

    AVHWDeviceContext* dev_ctx = (AVHWDeviceContext*)m_hwDeviceCtx->data;
    AVD3D11VADeviceContext* d3d11_ctx = (AVD3D11VADeviceContext*)dev_ctx->hwctx;
    d3d11_ctx->device = m_device.Get();
    d3d11_ctx->device->AddRef();
    d3d11_ctx->device_context = m_context.Get();
    d3d11_ctx->device_context->AddRef();
    d3d11_ctx->video_device = m_videoDevice.Get();
    d3d11_ctx->video_device->AddRef();
    d3d11_ctx->video_context = m_videoContext.Get();
    d3d11_ctx->video_context->AddRef();

    int ret = av_hwdevice_ctx_init(m_hwDeviceCtx);
    if (ret < 0) {
        std::cerr << "{\"type\":\"error\",\"message\":\"av_hwdevice_ctx_init failed: " << ret << "\"}" << std::endl;
        return false;
    }

    return true;
}

void D3D11Context::LogViolation(const char* fmt, ...) {
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    std::cerr << "{\"type\":\"violation\",\"tag\":\"ZERO_COPY_VIOLATION\",\"message\":\"" << buf << "\"}" << std::endl;
}

void D3D11Context::LogDebug(const char* fmt, ...) {
    if (!debug_gpu_copies) return;
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    std::cerr << "{\"type\":\"debug\",\"message\":\"" << buf << "\"}" << std::endl;
}
