#include "PipelineProfile.h"
#include "TelemetryRenderer.h"
#include <iostream>
#include <vector>
#include <cmath>
#include <algorithm>

#pragma comment(lib, "d2d1.lib")
#pragma comment(lib, "dwrite.lib")

TelemetryRenderer::TelemetryRenderer(D3D11Context& d3dContext, int streamId)
    : m_d3dContext(d3dContext), m_streamId(streamId) {
}

TelemetryRenderer::~TelemetryRenderer() {
    Shutdown();
}

void TelemetryRenderer::Shutdown() {
    m_inputView.Reset();
    m_textBrush.Reset();
    m_outlineBrush.Reset();
    m_textFormat.Reset();
    m_dcTarget.Reset();
    m_dwriteFactory.Reset();
    m_d2dFactory.Reset();
    if (m_hbmp) { DeleteObject(m_hbmp); m_hbmp = nullptr; }
    if (m_hdcMem) { DeleteDC(m_hdcMem); m_hdcMem = nullptr; }
    m_bits = nullptr;
    m_texture.Reset();
}

bool TelemetryRenderer::Initialize(int width, int height, float fontSize, float opacity) {
    m_width = (width + 1) & ~1;
    m_height = (height + 1) & ~1;
    m_fontSize = fontSize;
    m_opacity = (std::max)(0.0f, (std::min)(1.0f, opacity));

    D3D11_TEXTURE2D_DESC desc = {};
    desc.Width = m_width;
    desc.Height = m_height;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    // The AMD-only shader compositor samples overlays directly. Other vendors
    // retain the original Video Processor-only texture setup.
    desc.BindFlags = m_d3dContext.GetVendorId() == 0x1002 ? D3D11_BIND_SHADER_RESOURCE : 0;

    HRESULT hr = m_d3dContext.GetDevice()->CreateTexture2D(&desc, nullptr, &m_texture);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create TelemetryRenderer B8G8R8A8 texture: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    // Allocate 32-bit DIBSection
    BITMAPINFO bmi = {};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = m_width;
    bmi.bmiHeader.biHeight = -m_height; // Top-down
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    m_hdcMem = CreateCompatibleDC(nullptr);
    m_hbmp = CreateDIBSection(m_hdcMem, &bmi, DIB_RGB_COLORS, &m_bits, nullptr, 0);
    if (!m_hdcMem || !m_hbmp || !m_bits) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create TelemetryRenderer DIBSection\"}" << std::endl;
        return false;
    }
    SelectObject(m_hdcMem, m_hbmp);

    // Initialize Direct2D & DirectWrite
    hr = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory), (void**)&m_d2dFactory);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"D2D1CreateFactory failed: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    hr = DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), (IUnknown**)&m_dwriteFactory);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"DWriteCreateFactory failed: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    D2D1_RENDER_TARGET_PROPERTIES props = D2D1::RenderTargetProperties(
        D2D1_RENDER_TARGET_TYPE_DEFAULT,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED)
    );
    hr = m_d2dFactory->CreateDCRenderTarget(&props, &m_dcTarget);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"CreateDCRenderTarget failed: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    RECT rc = { 0, 0, m_width, m_height };
    hr = m_dcTarget->BindDC(m_hdcMem, &rc);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"BindDC failed: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    hr = m_dwriteFactory->CreateTextFormat(
        L"Consolas", nullptr, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, m_fontSize, L"en-us", &m_textFormat
    );
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"CreateTextFormat failed: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    hr = m_dcTarget->CreateSolidColorBrush(D2D1::ColorF(D2D1::ColorF::White, m_opacity), &m_textBrush);
    if (FAILED(hr)) return false;

    hr = m_dcTarget->CreateSolidColorBrush(D2D1::ColorF(D2D1::ColorF::Black, m_opacity), &m_outlineBrush);
    if (FAILED(hr)) return false;

    // Start with clear transparent texture
    memset(m_bits, 0, m_width * m_height * 4);
    m_d3dContext.GetContext()->UpdateSubresource(m_texture.Get(), 0, nullptr, m_bits, m_width * 4, 0);

    return true;
}

bool TelemetryRenderer::UpdateText(const std::string& text, ID3D11VideoProcessorEnumerator* vpEnum) {
    if (m_d3dContext.GetVendorId() != 0x1002 && !m_inputView && vpEnum && m_texture) {
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC viewDesc = {};
        viewDesc.FourCC = 0;
        viewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        viewDesc.Texture2D.MipSlice = 0;
        viewDesc.Texture2D.ArraySlice = 0;
        HRESULT hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorInputView(m_texture.Get(), vpEnum, &viewDesc, &m_inputView);
        if (FAILED(hr)) {
            std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create TelemetryRenderer InputView: " << std::hex << hr << "\"}" << std::endl;
            return false;
        }
    }

    if (text == m_lastText) {
        return true;
    }

    m_lastText = text;
    return RenderTextWithOutline(text);
}

bool TelemetryRenderer::RenderTextWithOutline(const std::string& text) {
    PipelineProfile::Scope measure("TELEMETRY_RENDER_MS");
    if (!m_dcTarget || !m_bits) return false;

    if (text.empty()) {
        memset(m_bits, 0, m_width * m_height * 4);
        m_d3dContext.GetContext()->UpdateSubresource(m_texture.Get(), 0, nullptr, m_bits, m_width * 4, 0);
        return true;
    }

    int count = MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0);
    std::wstring wide(count, L' ');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), wide.data(), count);

    m_dcTarget->BeginDraw();
    // 100% transparent background (RGBA = 0, 0, 0, 0): NO BACKGROUND BOX!
    m_dcTarget->Clear(D2D1::ColorF(0, 0, 0, 0));

    // Dynamic outline radius proportional to font size:
    // outline_px = max(1, min(4, round(fontSize * 0.10)))
    int r = (std::max)(1, (std::min)(4, (int)std::round(m_fontSize * 0.10f)));

    float leftMargin = (float)(r + 2);
    float topMargin = (float)(r + 2);

    // Multi-pass outline: stroke black brush in a circle of radius r
    for (int dy = -r; dy <= r; ++dy) {
        for (int dx = -r; dx <= r; ++dx) {
            if (dx == 0 && dy == 0) continue;
            if (dx * dx + dy * dy > r * r + 1) continue;
            D2D1_RECT_F outlineRect = D2D1::RectF(leftMargin + dx, topMargin + dy, m_width - (float)r + dx, m_height - (float)r + dy);
            m_dcTarget->DrawText(wide.c_str(), (UINT32)wide.length(), m_textFormat.Get(), &outlineRect, m_outlineBrush.Get());
        }
    }

    // White text fill in the center
    D2D1_RECT_F textRect = D2D1::RectF(leftMargin, topMargin, m_width - (float)r, m_height - (float)r);
    m_dcTarget->DrawText(wide.c_str(), (UINT32)wide.length(), m_textFormat.Get(), &textRect, m_textBrush.Get());

    HRESULT hr = m_dcTarget->EndDraw();
    if (FAILED(hr)) return false;

    measure.Stop();
    // Upload BGRA texture directly to GPU
    PipelineProfile::Scope upload("TELEMETRY_UPLOAD_MS");
    PipelineProfile::GpuScope uploadGpu(m_d3dContext.GetDevice(),m_d3dContext.GetContext(),"TELEMETRY_UPLOAD_GPU_MS");
    m_d3dContext.GetContext()->UpdateSubresource(m_texture.Get(), 0, nullptr, m_bits, m_width * 4, 0);
    m_d3dContext.telemetry_texture_uploads++;
    m_d3dContext.telemetry_uploaded_bytes += m_width * m_height * 4;

    return true;
}
