#pragma once

#include "D3D11Context.h"
#include "TelemetryRenderer.h"
#include <string>

enum class LayoutMode {
    LeftRight,
    TopBottom
};

class GpuCompositor {
public:
    GpuCompositor(D3D11Context& d3dContext);
    ~GpuCompositor();

    bool Initialize(int outWidth, int outHeight, LayoutMode layout, bool padTo4k = false, int contentWidth = 0, int contentHeight = 0);
    void Shutdown();
    bool SetRotations(int rotation1, int rotation2);

    bool Composite(
        ID3D11Texture2D* tex1, int slice1, int w1, int h1,
        ID3D11Texture2D* tex2, int slice2, int w2, int h2,
        TelemetryRenderer* overlay1,
        TelemetryRenderer* overlay2,
        int colorSpace1 = 0, int colorRange1 = 0,
        int colorSpace2 = 0, int colorRange2 = 0,
        int transfer1 = 0, int transfer2 = 0
    );

    ID3D11Texture2D* GetOutputTexture() const { return m_outputTexture.Get(); }
    ID3D11VideoProcessorEnumerator* GetEnumerator() const { return m_vpEnum.Get(); }
    int GetWidth() const { return m_outWidth; }
    int GetHeight() const { return m_outHeight; }
    bool IsPadTo4k() const { return m_padTo4k; }

private:
    D3D11Context& m_d3dContext;
    int m_outWidth = 3840;
    int m_outHeight = 2160;
    int m_contentWidth = 3840;
    int m_contentHeight = 2160;
    bool m_padTo4k = false;
    int m_rotation1 = 0, m_rotation2 = 0;
    LayoutMode m_layout = LayoutMode::LeftRight;

    ComPtr<ID3D11VideoProcessorEnumerator> m_vpEnum;
    ComPtr<ID3D11VideoProcessor> m_videoProcessor;
    ComPtr<ID3D11Texture2D> m_outputTexture;
    ComPtr<ID3D11VideoProcessorOutputView> m_outputView;
    ComPtr<ID3D11Texture2D> m_overlayBaseTexture;
    ComPtr<ID3D11VideoProcessorOutputView> m_overlayBaseView;
    ComPtr<ID3D11Texture2D> m_overlayTexture;
    ComPtr<ID3D11RenderTargetView> m_overlayRtv;
    ComPtr<ID3D11ShaderResourceView> m_overlayBaseSrv;
    ComPtr<ID3D11ShaderResourceView> m_overlaySrv1;
    ComPtr<ID3D11ShaderResourceView> m_overlaySrv2;
    ComPtr<ID3D11VideoProcessorInputView> m_overlayFinalInputView;
    ID3D11Texture2D* m_lastOverlayFinalTexture = nullptr;
    ComPtr<ID3D11VertexShader> m_overlayVertexShader;
    ComPtr<ID3D11PixelShader> m_overlayPixelShader;
    ComPtr<ID3D11SamplerState> m_overlaySampler;
    ComPtr<ID3D11Buffer> m_overlayConstants;
    ID3D11Texture2D* m_lastOverlayTexture1 = nullptr;
    ID3D11Texture2D* m_lastOverlayTexture2 = nullptr;
    bool m_useAmdOverlayShader = false;
    bool m_loggedFrameDiagnostics = false;
    bool m_loggedColorSpaceDiagnostics = false;

    // Cached input views for single-slice textures
    ComPtr<ID3D11VideoProcessorInputView> m_inputView1;
    ComPtr<ID3D11VideoProcessorInputView> m_inputView2;
    ID3D11Texture2D* m_lastTex1 = nullptr;
    int m_lastSlice1 = -1;
    ID3D11Texture2D* m_lastTex2 = nullptr;
    int m_lastSlice2 = -1;
};
