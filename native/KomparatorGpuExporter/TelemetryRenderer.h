#pragma once

#include "D3D11Context.h"
#include <d2d1.h>
#include <dwrite.h>
#include <string>

class TelemetryRenderer {
public:
    TelemetryRenderer(D3D11Context& d3dContext, int streamId);
    ~TelemetryRenderer();

    bool Initialize(int width, int height, float fontSize, float opacity = 1.0f);
    void Shutdown();

    // True means successful update or cache hit; false means render failure.
    bool UpdateText(const std::string& text, ID3D11VideoProcessorEnumerator* vpEnum);

    ID3D11Texture2D* GetTexture() const { return m_texture.Get(); }
    ID3D11VideoProcessorInputView* GetInputView() const { return m_inputView.Get(); }
    int GetWidth() const { return m_width; }
    int GetHeight() const { return m_height; }
    const std::string& GetCurrentText() const { return m_lastText; }
    bool IsEmpty() const { return m_lastText.empty(); }
    const void* GetPixelData() const { return m_bits; }

private:
    bool RenderTextWithOutline(const std::string& text);

    D3D11Context& m_d3dContext;
    int m_streamId;
    int m_width = 700;
    int m_height = 240;
    float m_fontSize = 24.0f;
    float m_opacity = 1.0f;

    std::string m_lastText;

    ComPtr<ID3D11Texture2D> m_texture;
    ComPtr<ID3D11VideoProcessorInputView> m_inputView;

    // DIBSection for Direct2D DC target rendering
    HDC m_hdcMem = nullptr;
    HBITMAP m_hbmp = nullptr;
    void* m_bits = nullptr;

    // Direct2D / DirectWrite
    ComPtr<ID2D1Factory> m_d2dFactory;
    ComPtr<IDWriteFactory> m_dwriteFactory;
    ComPtr<ID2D1DCRenderTarget> m_dcTarget;
    ComPtr<ID2D1SolidColorBrush> m_textBrush;
    ComPtr<ID2D1SolidColorBrush> m_outlineBrush;
    ComPtr<IDWriteTextFormat> m_textFormat;
};
