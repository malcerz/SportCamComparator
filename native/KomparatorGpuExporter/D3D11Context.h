#pragma once

#include <windows.h>
#include <d3d11.h>
#include <d3d11_4.h>
#include <dxgi.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <string>
#include <atomic>
#include <cstdint>

extern "C" {
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_d3d11va.h>
}

using Microsoft::WRL::ComPtr;

class D3D11Context {
public:
    D3D11Context();
    ~D3D11Context();

    bool Initialize(const std::string& requestedVendor = "auto", bool enableDebug = false);

    ID3D11Device* GetDevice() const { return m_device.Get(); }
    ID3D11DeviceContext* GetContext() const { return m_context.Get(); }
    ID3D11VideoDevice* GetVideoDevice() const { return m_videoDevice.Get(); }
    ID3D11VideoContext* GetVideoContext() const { return m_videoContext.Get(); }
    AVBufferRef* GetHwDeviceCtx() const { return m_hwDeviceCtx; }

    std::wstring GetAdapterDescription() const { return m_adapterDescription; }
    UINT GetVendorId() const { return m_vendorId; }
    UINT GetDeviceId() const { return m_deviceId; }
    LUID GetAdapterLuid() const { return m_adapterLuid; }

    uint64_t VramBytes() const {
        ComPtr<IDXGIDevice> device;ComPtr<IDXGIAdapter> adapter;ComPtr<IDXGIAdapter3> adapter3;
        DXGI_QUERY_VIDEO_MEMORY_INFO info{};
        if(SUCCEEDED(m_device.As(&device)) && SUCCEEDED(device->GetAdapter(&adapter)) && SUCCEEDED(adapter.As(&adapter3)) &&
            SUCCEEDED(adapter3->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_LOCAL,&info)))return info.CurrentUsage;
        return 0;
    }
    // Instrumentation / Gate counters
    std::atomic<uint64_t> full_frame_hwdownload_count{ 0 };
    std::atomic<uint64_t> full_frame_hwupload_count{ 0 };
    std::atomic<uint64_t> software_frame_count{ 0 };
    std::atomic<uint64_t> telemetry_texture_uploads{ 0 };
    std::atomic<uint64_t> telemetry_uploaded_bytes{ 0 };

    bool debug_gpu_copies = false;

    void LogViolation(const char* fmt, ...);
    void LogDebug(const char* fmt, ...);

private:
    ComPtr<ID3D11Device> m_device;
    ComPtr<ID3D11DeviceContext> m_context;
    ComPtr<ID3D11VideoDevice> m_videoDevice;
    ComPtr<ID3D11VideoContext> m_videoContext;
    ComPtr<ID3D11Multithread> m_multithread;

    AVBufferRef* m_hwDeviceCtx = nullptr;

    std::wstring m_adapterDescription;
    UINT m_vendorId = 0;
    UINT m_deviceId = 0;
    LUID m_adapterLuid = {};
};
