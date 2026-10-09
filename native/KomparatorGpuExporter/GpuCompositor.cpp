#include "PipelineProfile.h"
#include "GpuCompositor.h"
#include <iostream>
#include <vector>
#include <algorithm>
#include <cstring>
#include <d3dcompiler.h>

GpuCompositor::GpuCompositor(D3D11Context& d3dContext)
    : m_d3dContext(d3dContext) {
}

GpuCompositor::~GpuCompositor() {
    Shutdown();
}

void GpuCompositor::Shutdown() {
    m_inputView1.Reset();
    m_inputView2.Reset();
    m_outputView.Reset();
    m_outputTexture.Reset();
    m_overlayFinalInputView.Reset(); m_overlayBaseView.Reset(); m_overlayRtv.Reset();
    m_overlayBaseSrv.Reset(); m_overlaySrv1.Reset(); m_overlaySrv2.Reset();
    m_overlayTexture.Reset(); m_overlayBaseTexture.Reset();
    m_overlayVertexShader.Reset(); m_overlayPixelShader.Reset(); m_overlaySampler.Reset(); m_overlayConstants.Reset();
    m_videoProcessor.Reset();
    m_vpEnum.Reset();
}

bool GpuCompositor::Initialize(int outWidth, int outHeight, LayoutMode layout, bool padTo4k, int contentWidth, int contentHeight) {
    m_layout = layout;
    m_padTo4k = padTo4k;
    m_contentWidth = (contentWidth > 0) ? contentWidth : outWidth;
    m_contentHeight = (contentHeight > 0) ? contentHeight : outHeight;

    if (m_padTo4k) {
        if (m_contentWidth > 3840 || m_contentHeight > 2160) {
            std::cout << "[export] PAD_TO_4K_SKIPPED_CONTENT_TOO_LARGE: " << m_contentWidth << "x" << m_contentHeight << " > 3840x2160" << std::endl;
            m_padTo4k = false;
            m_outWidth = m_contentWidth;
            m_outHeight = m_contentHeight;
        } else {
            m_outWidth = 3840;
            m_outHeight = 2160;
            std::cout << "[export] PAD_TO_4K_APPLIED: padding " << m_contentWidth << "x" << m_contentHeight << " to 3840x2160" << std::endl;
        }
    } else {
        m_outWidth = outWidth;
        m_outHeight = outHeight;
    }

    D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
    contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    contentDesc.InputWidth = m_outWidth;
    contentDesc.InputHeight = m_outHeight;
    contentDesc.OutputWidth = m_outWidth;
    contentDesc.OutputHeight = m_outHeight;
    contentDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    HRESULT hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorEnumerator(&contentDesc, &m_vpEnum);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create VideoProcessorEnumerator: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    m_useAmdOverlayShader = m_d3dContext.GetVendorId() == 0x1002;
    if (m_useAmdOverlayShader) {
        D3D11_TEXTURE2D_DESC bgra{};
        bgra.Width = m_outWidth; bgra.Height = m_outHeight;
        bgra.MipLevels = 1; bgra.ArraySize = 1; bgra.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        bgra.SampleDesc.Count = 1; bgra.Usage = D3D11_USAGE_DEFAULT;
        bgra.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
        hr = m_d3dContext.GetDevice()->CreateTexture2D(&bgra, nullptr, &m_overlayBaseTexture);
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreateTexture2D(&bgra, nullptr, &m_overlayTexture);
        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC bgraView{};
        bgraView.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorOutputView(
            m_overlayBaseTexture.Get(), m_vpEnum.Get(), &bgraView, &m_overlayBaseView);
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreateRenderTargetView(m_overlayTexture.Get(), nullptr, &m_overlayRtv);
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreateShaderResourceView(m_overlayBaseTexture.Get(), nullptr, &m_overlayBaseSrv);
        if (FAILED(hr)) {
            std::cerr << "[D3D11 AMD] BGRA overlay target creation failed hr=0x" << std::hex << (unsigned)hr << std::dec << std::endl;
            return false;
        }

        static const char* shader = R"(
            Texture2D baseImage : register(t0);
            Texture2D overlayImage1 : register(t1);
            Texture2D overlayImage2 : register(t2);
            SamplerState linearSampler : register(s0);
            cbuffer OverlayConstants : register(b0) { float4 rect1; float4 rect2; };
            struct VOut { float4 position : SV_POSITION; float2 uv : TEXCOORD0; };
            VOut VSMain(uint id : SV_VertexID) {
                VOut o; float2 p = float2((id << 1) & 2, id & 2);
                o.uv = p; o.position = float4(p * float2(2, -2) + float2(-1, 1), 0, 1); return o;
            }
            float4 PSMain(VOut i) : SV_TARGET {
                float4 c = baseImage.Sample(linearSampler, i.uv);
                if (all(i.uv >= rect1.xy) && all(i.uv < rect1.zw)) {
                    float2 uv = (i.uv - rect1.xy) / max(rect1.zw - rect1.xy, float2(1e-6, 1e-6));
                    float4 o = overlayImage1.Sample(linearSampler, uv);
                    // Direct2D renders the DIB into a premultiplied-alpha
                    // BGRA surface, so composite with the premultiplied form.
                    c.rgb = o.rgb + c.rgb * (1.0 - o.a);
                }
                if (all(i.uv >= rect2.xy) && all(i.uv < rect2.zw)) {
                    float2 uv = (i.uv - rect2.xy) / max(rect2.zw - rect2.xy, float2(1e-6, 1e-6));
                    float4 o = overlayImage2.Sample(linearSampler, uv);
                    c.rgb = o.rgb + c.rgb * (1.0 - o.a);
                }
                return float4(c.rgb, 1);
            }
        )";
        ComPtr<ID3DBlob> vsBlob, psBlob, errors;
        hr = D3DCompile(shader, strlen(shader), nullptr, nullptr, nullptr, "VSMain", "vs_4_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &vsBlob, &errors);
        if (SUCCEEDED(hr)) hr = D3DCompile(shader, strlen(shader), nullptr, nullptr, nullptr, "PSMain", "ps_4_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &psBlob, &errors);
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreateVertexShader(vsBlob->GetBufferPointer(), vsBlob->GetBufferSize(), nullptr, &m_overlayVertexShader);
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreatePixelShader(psBlob->GetBufferPointer(), psBlob->GetBufferSize(), nullptr, &m_overlayPixelShader);
        D3D11_SAMPLER_DESC sampler{};
        sampler.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreateSamplerState(&sampler, &m_overlaySampler);
        D3D11_BUFFER_DESC cb{}; cb.ByteWidth = sizeof(float) * 8; cb.Usage = D3D11_USAGE_DYNAMIC;
        cb.BindFlags = D3D11_BIND_CONSTANT_BUFFER; cb.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        if (SUCCEEDED(hr)) hr = m_d3dContext.GetDevice()->CreateBuffer(&cb, nullptr, &m_overlayConstants);
        if (FAILED(hr)) {
            if (errors) std::cerr << "[D3D11 AMD] Overlay shader compile: " << (const char*)errors->GetBufferPointer() << std::endl;
            std::cerr << "[D3D11 AMD] Overlay shader initialization failed hr=0x" << std::hex << (unsigned)hr << std::dec << std::endl;
            return false;
        }
    }

    hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessor(m_vpEnum.Get(), 0, &m_videoProcessor);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create ID3D11VideoProcessor: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    D3D11_VIDEO_PROCESSOR_CAPS vpCaps{};
    hr = m_vpEnum->GetVideoProcessorCaps(&vpCaps);
    if (SUCCEEDED(hr)) {
        UINT inSupport = 0, outSupport = 0;
        const DXGI_FORMAT formats[] = { DXGI_FORMAT_NV12, DXGI_FORMAT_P010, DXGI_FORMAT_B8G8R8A8_UNORM };
        for (DXGI_FORMAT format : formats) {
            UINT support = 0;
            HRESULT fmtHr = m_vpEnum->CheckVideoProcessorFormat(format, &support);
            std::cerr << "[D3D11 VP] format=" << (unsigned)format << " hr=0x" << std::hex << (unsigned)fmtHr
                      << " input=" << ((support & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) != 0)
                      << " output=" << ((support & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT) != 0)
                      << std::dec << std::endl;
        }
        (void)inSupport; (void)outSupport;
        std::cerr << "[D3D11 VP] MaxInputStreams=" << vpCaps.MaxInputStreams
                  << " FeatureCaps=0x" << std::hex << vpCaps.FeatureCaps
                  << " rotation=" << ((vpCaps.FeatureCaps & D3D11_VIDEO_PROCESSOR_FEATURE_CAPS_ROTATION) != 0)
                  << std::dec << std::endl;
    } else {
        std::cerr << "[D3D11 VP] GetVideoProcessorCaps failed hr=0x" << std::hex << (unsigned)hr << std::dec << std::endl;
    }

    // Allocate output texture (NV12 with D3D11_BIND_RENDER_TARGET)
    D3D11_TEXTURE2D_DESC texDesc = {};
    texDesc.Width = m_outWidth;
    texDesc.Height = m_outHeight;
    texDesc.MipLevels = 1;
    texDesc.ArraySize = 1;
    texDesc.Format = DXGI_FORMAT_NV12;
    texDesc.SampleDesc.Count = 1;
    texDesc.Usage = D3D11_USAGE_DEFAULT;
    texDesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

    hr = m_d3dContext.GetDevice()->CreateTexture2D(&texDesc, nullptr, &m_outputTexture);
    if (FAILED(hr)) {
        // Retry with just RENDER_TARGET if combined failed
        texDesc.BindFlags = D3D11_BIND_RENDER_TARGET;
        hr = m_d3dContext.GetDevice()->CreateTexture2D(&texDesc, nullptr, &m_outputTexture);
    }

    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create compositor output texture: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    // Create VideoProcessor output view
    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outViewDesc = {};
    outViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    outViewDesc.Texture2D.MipSlice = 0;

    hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorOutputView(m_outputTexture.Get(), m_vpEnum.Get(), &outViewDesc, &m_outputView);
    if (FAILED(hr)) {
        std::cerr << "{\"type\":\"error\",\"message\":\"Failed to create VideoProcessorOutputView: " << std::hex << hr << "\"}" << std::endl;
        return false;
    }

    return true;
}

bool GpuCompositor::SetRotations(int rotation1, int rotation2) {
    m_rotation1 = (rotation1 % 360 + 360) % 360;
    m_rotation2 = (rotation2 % 360 + 360) % 360;
    ComPtr<ID3D11VideoContext1> context;
    if (FAILED(m_d3dContext.GetVideoContext()->QueryInterface(IID_PPV_ARGS(&context))))
        return m_rotation1 == 0 && m_rotation2 == 0;

    auto applyRot = [&](UINT streamIdx, int rot) {
        D3D11_VIDEO_PROCESSOR_ROTATION rEnum = D3D11_VIDEO_PROCESSOR_ROTATION_IDENTITY;
        BOOL enable = FALSE;
        if (rot == 90) {
            enable = TRUE;
            rEnum = D3D11_VIDEO_PROCESSOR_ROTATION_90;
        } else if (rot == 180) {
            enable = TRUE;
            rEnum = D3D11_VIDEO_PROCESSOR_ROTATION_180;
        } else if (rot == 270) {
            enable = TRUE;
            rEnum = D3D11_VIDEO_PROCESSOR_ROTATION_270;
        }
        context->VideoProcessorSetStreamRotation(m_videoProcessor.Get(), streamIdx, enable, rEnum);
    };

    applyRot(0, m_rotation1);
    applyRot(1, m_rotation2);
    applyRot(2, 0);
    applyRot(3, 0);
    m_d3dContext.LogDebug("GPU COMPOSITOR: SetRotations applied: stream0=%d deg, stream1=%d deg", m_rotation1, m_rotation2);
    return true;
}

bool GpuCompositor::Composite(
    ID3D11Texture2D* tex1, int slice1, int w1, int h1,
    ID3D11Texture2D* tex2, int slice2, int w2, int h2,
    TelemetryRenderer* overlay1,
    TelemetryRenderer* overlay2,
    int colorSpace1, int colorRange1,
    int colorSpace2, int colorRange2,
    int transfer1, int transfer2
) {
    if (!tex1 || !tex2 || !m_videoProcessor || !m_outputView) {
        return false;
    }

    // Update / create input view for video 1 if texture/slice changed
    if (tex1 != m_lastTex1 || slice1 != m_lastSlice1 || !m_inputView1) {
        m_inputView1.Reset();
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
        inViewDesc.FourCC = 0;
        inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        inViewDesc.Texture2D.MipSlice = 0;
        inViewDesc.Texture2D.ArraySlice = (UINT)slice1;
        HRESULT hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorInputView(tex1, m_vpEnum.Get(), &inViewDesc, &m_inputView1);
        if (FAILED(hr)) {
            m_d3dContext.LogViolation("Failed to create VideoProcessorInputView for video 1 (HR: 0x%x)", hr);
            return false;
        }
        m_lastTex1 = tex1;
        m_lastSlice1 = slice1;
    }

    // Update / create input view for video 2 if texture/slice changed
    if (tex2 != m_lastTex2 || slice2 != m_lastSlice2 || !m_inputView2) {
        m_inputView2.Reset();
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
        inViewDesc.FourCC = 0;
        inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        inViewDesc.Texture2D.MipSlice = 0;
        inViewDesc.Texture2D.ArraySlice = (UINT)slice2;
        HRESULT hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorInputView(tex2, m_vpEnum.Get(), &inViewDesc, &m_inputView2);
        if (FAILED(hr)) {
            m_d3dContext.LogViolation("Failed to create VideoProcessorInputView for video 2 (HR: 0x%x)", hr);
            return false;
        }
        m_lastTex2 = tex2;
        m_lastSlice2 = slice2;
    }

    RECT targetRect = { 0, 0, m_outWidth, m_outHeight };
    m_d3dContext.GetVideoContext()->VideoProcessorSetOutputTargetRect(m_videoProcessor.Get(), TRUE, &targetRect);

    // Calculate source and dest rectangles
    RECT srcRect1 = { 0, 0, w1, h1 };
    RECT srcRect2 = { 0, 0, w2, h2 };
    RECT dstRect1 = {};
    RECT dstRect2 = {};

    RECT ovDst1 = {};
    RECT ovDst2 = {};

    if (m_d3dContext.debug_gpu_copies && !m_loggedFrameDiagnostics) {
        auto logTexture = [](const char* label, ID3D11Texture2D* tex) {
            D3D11_TEXTURE2D_DESC desc{};
            tex->GetDesc(&desc);
            std::cerr << "[D3D11 VP] " << label << " format=" << (unsigned)desc.Format
                      << " size=" << desc.Width << "x" << desc.Height << " array=" << desc.ArraySize
                      << " bind=0x" << std::hex << desc.BindFlags << std::dec << std::endl;
        };
        logTexture("input1", tex1); logTexture("input2", tex2);
        std::cerr << "[D3D11 VP] video_processor_streams=" << (2 + (!m_useAmdOverlayShader && overlay1 && !overlay1->IsEmpty()) + (!m_useAmdOverlayShader && overlay2 && !overlay2->IsEmpty()))
                  << " shader_overlays=" << (m_useAmdOverlayShader ? ((overlay1 && !overlay1->IsEmpty()) + (overlay2 && !overlay2->IsEmpty())) : 0)
                  << " output=" << m_outWidth << "x" << m_outHeight
                  << " input_color={" << colorSpace1 << "," << colorRange1 << "},{" << colorSpace2 << "," << colorRange2 << "}" << std::endl;
    }

    int pad = (std::max)(10, m_outWidth / 150);

    int boxX = 0, boxY = 0;
    int boxW = m_outWidth, boxH = m_outHeight;
    if (m_padTo4k) {
        boxW = m_contentWidth;
        boxH = m_contentHeight;
        boxX = (m_outWidth - boxW) / 2;
        boxY = (m_outHeight - boxH) / 2;
    }

    if (m_layout == LayoutMode::LeftRight) {
        int halfW = boxW / 2;
        dstRect1 = { boxX, boxY, boxX + halfW, boxY + boxH };
        dstRect2 = { boxX + halfW, boxY, boxX + boxW, boxY + boxH };

        if (overlay1) {
            ovDst1 = { boxX + pad, boxY + pad, boxX + pad + overlay1->GetWidth(), boxY + pad + overlay1->GetHeight() };
        }
        if (overlay2) {
            ovDst2 = { boxX + halfW + pad, boxY + pad, boxX + halfW + pad + overlay2->GetWidth(), boxY + pad + overlay2->GetHeight() };
        }
    } else { // TopBottom
        int halfH = boxH / 2;
        dstRect1 = { boxX, boxY, boxX + boxW, boxY + halfH };
        dstRect2 = { boxX, boxY + halfH, boxX + boxW, boxY + boxH };

        if (overlay1) {
            ovDst1 = { boxX + pad, boxY + pad, boxX + pad + overlay1->GetWidth(), boxY + pad + overlay1->GetHeight() };
        }
        if (overlay2) {
            ovDst2 = { boxX + pad, boxY + halfH + pad, boxX + pad + overlay2->GetWidth(), boxY + halfH + pad + overlay2->GetHeight() };
        }
    }

    auto fit = [](RECT box, int width, int height) {
        double scale = (std::min)(double(box.right-box.left)/width, double(box.bottom-box.top)/height);
        int w = int(width*scale) & ~1, h = int(height*scale) & ~1;
        int x = box.left + (box.right-box.left-w)/2, y = box.top + (box.bottom-box.top-h)/2;
        return RECT{x,y,x+w,y+h};
    };
    dstRect1 = fit(dstRect1, m_rotation1 % 180 ? h1 : w1, m_rotation1 % 180 ? w1 : h1);
    dstRect2 = fit(dstRect2, m_rotation2 % 180 ? h2 : w2, m_rotation2 % 180 ? w2 : h2);
    if (overlay1) ovDst1 = {dstRect1.left+pad,dstRect1.top+pad,dstRect1.left+pad+overlay1->GetWidth(),dstRect1.top+pad+overlay1->GetHeight()};
    if (overlay2) ovDst2 = {dstRect2.left+pad,dstRect2.top+pad,dstRect2.left+pad+overlay2->GetWidth(),dstRect2.top+pad+overlay2->GetHeight()};
    if (m_d3dContext.debug_gpu_copies && !m_loggedFrameDiagnostics) {
        auto printRect = [](const char* label, RECT r) {
            std::cerr << "[D3D11 VP] " << label << "=" << r.left << "," << r.top << "-" << r.right << "," << r.bottom << std::endl;
        };
        printRect("src1", srcRect1); printRect("dst1", dstRect1);
        printRect("src2", srcRect2); printRect("dst2", dstRect2);
        printRect("overlay1", ovDst1); printRect("overlay2", ovDst2);
        m_loggedFrameDiagnostics = true;
    }
    // Route every AMD composition through BGRA so the VP performs source
    // color conversion into RGB before the final NV12 encode surface. The
    // shader becomes a transparent pass-through when no telemetry is present.
    const bool amdTwoStage = m_useAmdOverlayShader;
    const bool shaderOverlay = amdTwoStage &&
        ((overlay1 && !overlay1->IsEmpty()) || (overlay2 && !overlay2->IsEmpty()));
    // NV12 black != all-zero buffer.
    // D3D11_VIDEO_COLOR is a union of RGBA and YCbCrA. For NV12 output surfaces the
    // video processor interprets the background color as YCbCr, NOT as RGBA.
    // All-zero YCbCr: Y=0, Cb=0, Cr=0 → after BT.709 conversion: saturated GREEN (R≈0,G≈151,B≈0).
    // Correct NV12 black (Studio 16-235): Y=16/255, Cb=128/255, Cr=128/255.
    D3D11_VIDEO_COLOR background{};
    background.YCbCr.Y  = 16.0f  / 255.0f;   // Studio black luma  (16)
    background.YCbCr.Cb = 128.0f / 255.0f;   // Neutral chroma Cb  (128)
    background.YCbCr.Cr = 128.0f / 255.0f;   // Neutral chroma Cr  (128)
    background.YCbCr.A  = 1.0f;
    // Configure output color space: BT.709, Studio 16-235, so the driver uses the
    // same interpretation as the background color values above.
    D3D11_VIDEO_PROCESSOR_COLOR_SPACE csOut = {};
    csOut.Usage        = 0; // Playback
    csOut.RGB_Range    = 1; // Studio 16-235
    csOut.YCbCr_Matrix = 1; // BT.709
    csOut.Nominal_Range = D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_16_235;
    m_d3dContext.GetVideoContext()->VideoProcessorSetOutputColorSpace(m_videoProcessor.Get(), &csOut);
    m_d3dContext.GetVideoContext()->VideoProcessorSetOutputBackgroundColor(m_videoProcessor.Get(), TRUE, &background);

    // The AMD D3D11 path must not rely on driver defaults for YUV interpretation.
    // The legacy interface covers BT.601/709 range selection; ColorSpace1 also
    // describes BT.2020 and HLG sources when the driver exposes it.
    if (m_d3dContext.GetVendorId() == 0x1002) {
        auto legacySpace = [](int colorspace, int range) {
            D3D11_VIDEO_PROCESSOR_COLOR_SPACE value{};
            value.Usage = 0;
            value.RGB_Range = range == AVCOL_RANGE_JPEG ? 0 : 1;
            value.YCbCr_Matrix = colorspace == AVCOL_SPC_BT709 ? 1 : 0;
            value.Nominal_Range = range == AVCOL_RANGE_JPEG
                ? D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_0_255
                : D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_16_235;
            return value;
        };
        auto* vc = m_d3dContext.GetVideoContext();
        const auto in1 = legacySpace(colorSpace1, colorRange1);
        const auto in2 = legacySpace(colorSpace2, colorRange2);
        ComPtr<ID3D11VideoContext1> vc1;
        ComPtr<ID3D11VideoProcessorEnumerator1> enum1;
        if (SUCCEEDED(vc->QueryInterface(IID_PPV_ARGS(&vc1))) &&
            SUCCEEDED(m_vpEnum.As(&enum1))) {
            auto dxgiColorSpace = [](int colorspace, int range, int transfer) {
                if (colorspace == AVCOL_SPC_BT2020_NCL || colorspace == AVCOL_SPC_BT2020_CL) {
                    if (transfer == AVCOL_TRC_ARIB_STD_B67)
                        return range == AVCOL_RANGE_JPEG ? DXGI_COLOR_SPACE_YCBCR_FULL_GHLG_TOPLEFT_P2020
                                                         : DXGI_COLOR_SPACE_YCBCR_STUDIO_GHLG_TOPLEFT_P2020;
                    if (transfer == AVCOL_TRC_SMPTE2084)
                        return DXGI_COLOR_SPACE_YCBCR_STUDIO_G2084_LEFT_P2020;
                    return range == AVCOL_RANGE_JPEG ? DXGI_COLOR_SPACE_YCBCR_FULL_G22_LEFT_P2020
                                                     : DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P2020;
                }
                return range == AVCOL_RANGE_JPEG ? DXGI_COLOR_SPACE_YCBCR_FULL_G22_LEFT_P709
                                                 : DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709;
            };
            const auto input1 = dxgiColorSpace(colorSpace1, colorRange1, transfer1);
            const auto input2 = dxgiColorSpace(colorSpace2, colorRange2, transfer2);
            const auto output = DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709;
            BOOL conversion1 = FALSE, conversion2 = FALSE;
            HRESULT check1 = S_OK, check2 = S_OK;
            if (!m_loggedColorSpaceDiagnostics) {
                check1 = enum1->CheckVideoProcessorFormatConversion(DXGI_FORMAT_P010, input1, DXGI_FORMAT_NV12, output, &conversion1);
                check2 = enum1->CheckVideoProcessorFormatConversion(DXGI_FORMAT_P010, input2, DXGI_FORMAT_NV12, output, &conversion2);
            }
            if (m_d3dContext.debug_gpu_copies && !m_loggedColorSpaceDiagnostics) {
                std::cerr << "[D3D11 VP ColorSpace1] stream0=" << (int)input1
                          << " stream1=" << (int)input2 << " output=" << (int)output
                          << " convert_check_hr=0x" << std::hex << (unsigned)check1 << "/0x" << (unsigned)check2
                          << std::dec << " supported=" << conversion1 << "/" << conversion2 << std::endl;
            }
            m_loggedColorSpaceDiagnostics = true;
            vc1->VideoProcessorSetStreamColorSpace1(m_videoProcessor.Get(), 0, input1);
            vc1->VideoProcessorSetStreamColorSpace1(m_videoProcessor.Get(), 1, input2);
            vc1->VideoProcessorSetOutputColorSpace1(m_videoProcessor.Get(), amdTwoStage ? DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709 : output);
        } else {
            vc->VideoProcessorSetStreamColorSpace(m_videoProcessor.Get(), 0, &in1);
            vc->VideoProcessorSetStreamColorSpace(m_videoProcessor.Get(), 1, &in2);
        }
    }

    std::vector<D3D11_VIDEO_PROCESSOR_STREAM> streams;

    // Stream 0: Video 1
    D3D11_VIDEO_PROCESSOR_STREAM st1 = {};
    st1.Enable = TRUE;
    st1.pInputSurface = m_inputView1.Get();
    m_d3dContext.GetVideoContext()->VideoProcessorSetStreamSourceRect(m_videoProcessor.Get(), 0, TRUE, &srcRect1);
    m_d3dContext.GetVideoContext()->VideoProcessorSetStreamDestRect(m_videoProcessor.Get(), 0, TRUE, &dstRect1);
    m_d3dContext.GetVideoContext()->VideoProcessorSetStreamAlpha(m_videoProcessor.Get(), 0, FALSE, 1.0f);
    streams.push_back(st1);

    // Stream 1: Video 2
    D3D11_VIDEO_PROCESSOR_STREAM st2 = {};
    st2.Enable = TRUE;
    st2.pInputSurface = m_inputView2.Get();
    m_d3dContext.GetVideoContext()->VideoProcessorSetStreamSourceRect(m_videoProcessor.Get(), 1, TRUE, &srcRect2);
    m_d3dContext.GetVideoContext()->VideoProcessorSetStreamDestRect(m_videoProcessor.Get(), 1, TRUE, &dstRect2);
    m_d3dContext.GetVideoContext()->VideoProcessorSetStreamAlpha(m_videoProcessor.Get(), 1, FALSE, 1.0f);
    streams.push_back(st2);

    UINT streamIdx = 2;
    auto setOverlayColorSpace = [&](UINT index) {
        D3D11_VIDEO_PROCESSOR_COLOR_SPACE rgb{};
        rgb.Usage = 0;
        rgb.RGB_Range = 0; // full-range RGB texture from Direct2D
        rgb.Nominal_Range = D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_0_255;
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamColorSpace(m_videoProcessor.Get(), index, &rgb);
        ComPtr<ID3D11VideoContext1> vc1;
        if (m_d3dContext.GetVendorId() == 0x1002 && SUCCEEDED(m_d3dContext.GetVideoContext()->QueryInterface(IID_PPV_ARGS(&vc1))))
            vc1->VideoProcessorSetStreamColorSpace1(m_videoProcessor.Get(), index, DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709);
    };
    if (!m_useAmdOverlayShader && overlay1 && overlay1->GetInputView() && !overlay1->IsEmpty()) {
        D3D11_VIDEO_PROCESSOR_STREAM stOv1 = {};
        stOv1.Enable = TRUE;
        stOv1.pInputSurface = overlay1->GetInputView();
        RECT srcOv1 = { 0, 0, overlay1->GetWidth(), overlay1->GetHeight() };
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamSourceRect(m_videoProcessor.Get(), streamIdx, TRUE, &srcOv1);
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamDestRect(m_videoProcessor.Get(), streamIdx, TRUE, &ovDst1);
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamAlpha(m_videoProcessor.Get(), streamIdx, TRUE, 1.0f);
        setOverlayColorSpace(streamIdx);
        streams.push_back(stOv1);
        streamIdx++;
    }

    if (!m_useAmdOverlayShader && overlay2 && overlay2->GetInputView() && !overlay2->IsEmpty()) {
        D3D11_VIDEO_PROCESSOR_STREAM stOv2 = {};
        stOv2.Enable = TRUE;
        stOv2.pInputSurface = overlay2->GetInputView();
        RECT srcOv2 = { 0, 0, overlay2->GetWidth(), overlay2->GetHeight() };
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamSourceRect(m_videoProcessor.Get(), streamIdx, TRUE, &srcOv2);
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamDestRect(m_videoProcessor.Get(), streamIdx, TRUE, &ovDst2);
        m_d3dContext.GetVideoContext()->VideoProcessorSetStreamAlpha(m_videoProcessor.Get(), streamIdx, TRUE, 1.0f);
        setOverlayColorSpace(streamIdx);
        streams.push_back(stOv2);
        streamIdx++;
    }

    auto* videoContext = m_d3dContext.GetVideoContext();
    ComPtr<ID3D11VideoContext1> videoContext1;
    videoContext->QueryInterface(IID_PPV_ARGS(&videoContext1));
    if (amdTwoStage && videoContext1) {
        auto rotationEnum = [](int degrees) {
            if (degrees == 90) return D3D11_VIDEO_PROCESSOR_ROTATION_90;
            if (degrees == 180) return D3D11_VIDEO_PROCESSOR_ROTATION_180;
            if (degrees == 270) return D3D11_VIDEO_PROCESSOR_ROTATION_270;
            return D3D11_VIDEO_PROCESSOR_ROTATION_IDENTITY;
        };
        videoContext1->VideoProcessorSetStreamRotation(m_videoProcessor.Get(), 0, m_rotation1 != 0, rotationEnum(m_rotation1));
        videoContext1->VideoProcessorSetStreamRotation(m_videoProcessor.Get(), 1, m_rotation2 != 0, rotationEnum(m_rotation2));
    }
    if (amdTwoStage && videoContext1)
        videoContext1->VideoProcessorSetOutputColorSpace1(m_videoProcessor.Get(), DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709);
    PipelineProfile::Scope measure("COMPOSITOR_MS");
    PipelineProfile::GpuScope gpu(m_d3dContext.GetDevice(),m_d3dContext.GetContext(),"COMPOSITOR_GPU_MS");
    HRESULT hr = videoContext->VideoProcessorBlt(
        m_videoProcessor.Get(),
        amdTwoStage ? m_overlayBaseView.Get() : m_outputView.Get(),
        0,
        (UINT)streams.size(),
        streams.data()
    );

    if (FAILED(hr)) {
        m_d3dContext.LogViolation("VideoProcessorBlt failed with HR: 0x%x (streams=%u, device_removed=0x%x)", hr, (unsigned)streams.size(), m_d3dContext.GetDevice()->GetDeviceRemovedReason());
        return false;
    }

    if (amdTwoStage) {
      if (shaderOverlay) {
        auto ensureSrv = [&](TelemetryRenderer* overlay, ComPtr<ID3D11ShaderResourceView>& srv, ID3D11Texture2D*& last) -> bool {
            if (!overlay || overlay->IsEmpty()) { srv.Reset(); last = nullptr; return true; }
            ID3D11Texture2D* texture = overlay->GetTexture();
            if (texture != last || !srv) {
                srv.Reset();
                HRESULT viewHr = m_d3dContext.GetDevice()->CreateShaderResourceView(texture, nullptr, &srv);
                if (FAILED(viewHr)) return false;
                last = texture;
            }
            return true;
        };
        if (!ensureSrv(overlay1, m_overlaySrv1, m_lastOverlayTexture1) ||
            !ensureSrv(overlay2, m_overlaySrv2, m_lastOverlayTexture2)) {
            m_d3dContext.LogViolation("AMD overlay shader SRV creation failed (device_removed=0x%x)", m_d3dContext.GetDevice()->GetDeviceRemovedReason());
            return false;
        }
        struct RectConstants { float r1[4]; float r2[4]; } constants{};
        auto toNormalized = [&](RECT r, float dst[4]) {
            dst[0] = float(r.left) / m_outWidth; dst[1] = float(r.top) / m_outHeight;
            dst[2] = float(r.right) / m_outWidth; dst[3] = float(r.bottom) / m_outHeight;
        };
        if (overlay1 && !overlay1->IsEmpty()) toNormalized(ovDst1, constants.r1);
        if (overlay2 && !overlay2->IsEmpty()) toNormalized(ovDst2, constants.r2);
        D3D11_MAPPED_SUBRESOURCE mapped{};
        hr = m_d3dContext.GetContext()->Map(m_overlayConstants.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
        if (FAILED(hr)) return false;
        memcpy(mapped.pData, &constants, sizeof(constants));
        m_d3dContext.GetContext()->Unmap(m_overlayConstants.Get(), 0);

        auto* ctx = m_d3dContext.GetContext();
        D3D11_VIEWPORT viewport{ 0.0f, 0.0f, float(m_outWidth), float(m_outHeight), 0.0f, 1.0f };
        ctx->RSSetViewports(1, &viewport);
        ctx->OMSetRenderTargets(1, m_overlayRtv.GetAddressOf(), nullptr);
        ctx->IASetInputLayout(nullptr);
        ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        ctx->VSSetShader(m_overlayVertexShader.Get(), nullptr, 0);
        ctx->PSSetShader(m_overlayPixelShader.Get(), nullptr, 0);
        ID3D11ShaderResourceView* srvs[] = { m_overlayBaseSrv.Get(), m_overlaySrv1.Get(), m_overlaySrv2.Get() };
        ctx->PSSetShaderResources(0, 3, srvs);
        ID3D11SamplerState* sampler = m_overlaySampler.Get(); ctx->PSSetSamplers(0, 1, &sampler);
        ID3D11Buffer* cb = m_overlayConstants.Get(); ctx->PSSetConstantBuffers(0, 1, &cb);
        ctx->Draw(3, 0);
        ID3D11ShaderResourceView* nullSrvs[] = { nullptr, nullptr, nullptr };
        ctx->PSSetShaderResources(0, 3, nullSrvs);
        ID3D11RenderTargetView* nullRtv = nullptr; ctx->OMSetRenderTargets(1, &nullRtv, nullptr);
      }

        ID3D11Texture2D* finalTexture = shaderOverlay ? m_overlayTexture.Get() : m_overlayBaseTexture.Get();
        if (!m_overlayFinalInputView || m_lastOverlayFinalTexture != finalTexture) {
            m_overlayFinalInputView.Reset();
            D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC view{};
            view.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
            hr = m_d3dContext.GetVideoDevice()->CreateVideoProcessorInputView(
                finalTexture, m_vpEnum.Get(), &view, &m_overlayFinalInputView);
            if (FAILED(hr)) {
                m_d3dContext.LogViolation("AMD BGRA final input view failed hr=0x%x", hr);
                return false;
            }
            m_lastOverlayFinalTexture = finalTexture;
        }
        D3D11_VIDEO_PROCESSOR_STREAM finalStream{};
        finalStream.Enable = TRUE; finalStream.pInputSurface = m_overlayFinalInputView.Get();
        RECT full = { 0, 0, m_outWidth, m_outHeight };
        videoContext->VideoProcessorSetOutputTargetRect(m_videoProcessor.Get(), TRUE, &full);
        videoContext->VideoProcessorSetStreamSourceRect(m_videoProcessor.Get(), 0, TRUE, &full);
        videoContext->VideoProcessorSetStreamDestRect(m_videoProcessor.Get(), 0, TRUE, &full);
        videoContext->VideoProcessorSetStreamAlpha(m_videoProcessor.Get(), 0, FALSE, 1.0f);
        if (videoContext1) {
            videoContext1->VideoProcessorSetStreamRotation(m_videoProcessor.Get(), 0, FALSE, D3D11_VIDEO_PROCESSOR_ROTATION_IDENTITY);
            videoContext1->VideoProcessorSetOutputColorSpace1(m_videoProcessor.Get(), DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709);
            videoContext1->VideoProcessorSetStreamColorSpace1(m_videoProcessor.Get(), 0, DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709);
        }
        D3D11_VIDEO_PROCESSOR_COLOR_SPACE rgb{}; rgb.RGB_Range = 0; rgb.Nominal_Range = D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_0_255;
        videoContext->VideoProcessorSetStreamColorSpace(m_videoProcessor.Get(), 0, &rgb);
        videoContext->VideoProcessorSetOutputColorSpace(m_videoProcessor.Get(), &csOut);
        videoContext->VideoProcessorSetOutputBackgroundColor(m_videoProcessor.Get(), TRUE, &background);
        hr = videoContext->VideoProcessorBlt(m_videoProcessor.Get(), m_outputView.Get(), 0, 1, &finalStream);
        if (FAILED(hr)) {
            m_d3dContext.LogViolation("AMD BGRA-to-NV12 VideoProcessorBlt failed hr=0x%x device_removed=0x%x", hr, m_d3dContext.GetDevice()->GetDeviceRemovedReason());
            return false;
        }
    }

    m_d3dContext.LogDebug("COMPOSE: input1=0x%p (slice %d), input2=0x%p (slice %d), output=0x%p, streams=%u",
                         tex1, slice1, tex2, slice2, m_outputTexture.Get(), (unsigned)streams.size());

    return true;
}
