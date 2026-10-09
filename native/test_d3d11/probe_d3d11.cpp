#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <d2d1.h>
#include <iostream>
#include <vector>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_d3d11va.h>
#include <libavutil/opt.h>
}

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "avcodec.lib")
#pragma comment(lib, "avformat.lib")
#pragma comment(lib, "avutil.lib")

int main() {
    std::cout << "[Probe] Starting D3D11 & FFmpeg probe..." << std::endl;

    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL featureLevel;
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;

    UINT flags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT | D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags,
                                   featureLevels, 2, D3D11_SDK_VERSION, &device, &featureLevel, &context);
    if (FAILED(hr)) {
        std::cerr << "[Probe] D3D11CreateDevice failed: 0x" << std::hex << hr << std::endl;
        return 1;
    }
    std::cout << "[Probe] D3D11 device created successfully. Feature Level: 0x" << std::hex << featureLevel << std::dec << std::endl;

    // Check VideoDevice
    ID3D11VideoDevice* videoDevice = nullptr;
    ID3D11VideoContext* videoContext = nullptr;
    hr = device->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&videoDevice);
    context->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&videoContext);
    ID3D11Texture2D* outTex = nullptr;
    if (FAILED(hr) || !videoDevice || !videoContext) {
        std::cerr << "[Probe] ID3D11VideoDevice or ID3D11VideoContext not supported!" << std::endl;
    } else {
        std::cout << "[Probe] ID3D11VideoDevice supported!" << std::endl;

        D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
        contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
        contentDesc.InputWidth = 3840;
        contentDesc.InputHeight = 2160;
        contentDesc.OutputWidth = 3840;
        contentDesc.OutputHeight = 2160;
        contentDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

        ID3D11VideoProcessorEnumerator* vpEnum = nullptr;
        hr = videoDevice->CreateVideoProcessorEnumerator(&contentDesc, &vpEnum);
        if (SUCCEEDED(hr) && vpEnum) {
            D3D11_VIDEO_PROCESSOR_CAPS caps = {};
            vpEnum->GetVideoProcessorCaps(&caps);
            std::cout << "[Probe] VideoProcessorEnumerator created! MaxStreamStates: " << caps.MaxStreamStates
                      << ", MaxInputStreams: " << caps.MaxInputStreams << std::endl;

            UINT flagsNV12 = 0;
            vpEnum->CheckVideoProcessorFormat(DXGI_FORMAT_NV12, &flagsNV12);
            std::cout << "[Probe] Format NV12 support flags: 0x" << std::hex << flagsNV12 << std::dec << std::endl;

            UINT flagsP010 = 0;
            vpEnum->CheckVideoProcessorFormat(DXGI_FORMAT_P010, &flagsP010);
            std::cout << "[Probe] Format P010 support flags: 0x" << std::hex << flagsP010 << std::dec << std::endl;

            UINT flagsRGBA = 0;
            vpEnum->CheckVideoProcessorFormat(DXGI_FORMAT_B8G8R8A8_UNORM, &flagsRGBA);
            std::cout << "[Probe] Format B8G8R8A8 support flags: 0x" << std::hex << flagsRGBA << std::dec << std::endl;

            ID3D11VideoProcessor* vp = nullptr;
            hr = videoDevice->CreateVideoProcessor(vpEnum, 0, &vp);
            if (SUCCEEDED(hr) && vp) {
                std::cout << "[Probe] ID3D11VideoProcessor created successfully!" << std::endl;

                // Test creating input & output views for NV12
                D3D11_TEXTURE2D_DESC texDesc = {};
                texDesc.Width = 3840;
                texDesc.Height = 2160;
                texDesc.MipLevels = 1;
                texDesc.ArraySize = 1;
                texDesc.Format = DXGI_FORMAT_NV12;
                texDesc.SampleDesc.Count = 1;
                texDesc.Usage = D3D11_USAGE_DEFAULT;
                texDesc.BindFlags = D3D11_BIND_DECODER; // or SHADER_RESOURCE

                ID3D11Texture2D* inTex = nullptr;
                hr = device->CreateTexture2D(&texDesc, nullptr, &inTex);
                std::cout << "[Probe] Create inTex NV12: 0x" << std::hex << hr << std::dec << std::endl;

                texDesc.BindFlags = D3D11_BIND_RENDER_TARGET; // For video processor output
                hr = device->CreateTexture2D(&texDesc, nullptr, &outTex);
                std::cout << "[Probe] Create outTex (RENDER_TARGET): 0x" << std::hex << hr << std::dec << std::endl;

                D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
                inViewDesc.FourCC = 0;
                inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
                inViewDesc.Texture2D.MipSlice = 0;
                inViewDesc.Texture2D.ArraySlice = 0;
                ID3D11VideoProcessorInputView* inView = nullptr;
                hr = videoDevice->CreateVideoProcessorInputView(inTex, vpEnum, &inViewDesc, &inView);
                std::cout << "[Probe] CreateVideoProcessorInputView: 0x" << std::hex << hr << std::dec << std::endl;

                D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outViewDesc = {};
                outViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
                outViewDesc.Texture2D.MipSlice = 0;
                ID3D11VideoProcessorOutputView* outView = nullptr;
                hr = videoDevice->CreateVideoProcessorOutputView(outTex, vpEnum, &outViewDesc, &outView);
                std::cout << "[Probe] CreateVideoProcessorOutputView: 0x" << std::hex << hr << std::dec << std::endl;

                // Test creating NV12 overlay texture
                D3D11_TEXTURE2D_DESC ovDesc = {};
                ovDesc.Width = 600;
                ovDesc.Height = 200;
                ovDesc.MipLevels = 1;
                ovDesc.ArraySize = 1;
                ovDesc.Format = DXGI_FORMAT_NV12;
                ovDesc.SampleDesc.Count = 1;
                ovDesc.Usage = D3D11_USAGE_DEFAULT;
                ovDesc.BindFlags = D3D11_BIND_DECODER;

                ID3D11Texture2D* rgbaTex = nullptr;
                hr = device->CreateTexture2D(&ovDesc, nullptr, &rgbaTex);
                std::cout << "[Probe] Create ovTex NV12: 0x" << std::hex << hr << std::dec << std::endl;

                // Fill with Y=20 (dark), U=128, V=128
                std::vector<uint8_t> ovData(600 * 200 + 600 * 100);
                memset(ovData.data(), 20, 600 * 200); // Y plane
                memset(ovData.data() + 600 * 200, 128, 600 * 100); // UV plane
                context->UpdateSubresource(rgbaTex, 0, nullptr, ovData.data(), 600, 0);

                D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC rgbaViewDesc = {};
                rgbaViewDesc.FourCC = 0;
                rgbaViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
                rgbaViewDesc.Texture2D.MipSlice = 0;
                rgbaViewDesc.Texture2D.ArraySlice = 0;
                ID3D11VideoProcessorInputView* rgbaView = nullptr;
                hr = videoDevice->CreateVideoProcessorInputView(rgbaTex, vpEnum, &rgbaViewDesc, &rgbaView);
                std::cout << "[Probe] CreateVideoProcessorInputView NV12 Overlay: 0x" << std::hex << hr << std::dec << std::endl;

                if (inView && outView && rgbaView) {
                    D3D11_VIDEO_PROCESSOR_STREAM streams[2] = {};
                    streams[0].Enable = TRUE;
                    streams[0].pInputSurface = inView;

                    RECT srcRect = { 0, 0, 3840, 2160 };
                    RECT dstRect = { 0, 0, 1920, 2160 };
                    videoContext->VideoProcessorSetStreamSourceRect(vp, 0, TRUE, &srcRect);
                    videoContext->VideoProcessorSetStreamDestRect(vp, 0, TRUE, &dstRect);

                    streams[1].Enable = TRUE;
                    streams[1].pInputSurface = rgbaView;
                    RECT rgbaSrc = { 0, 0, 600, 200 };
                    RECT rgbaDst = { 50, 50, 650, 250 };
                    videoContext->VideoProcessorSetStreamSourceRect(vp, 1, TRUE, &rgbaSrc);
                    videoContext->VideoProcessorSetStreamDestRect(vp, 1, TRUE, &rgbaDst);
                    videoContext->VideoProcessorSetStreamAlpha(vp, 1, TRUE, 1.0f);

                    RECT targetRect = { 0, 0, 3840, 2160 };
                    videoContext->VideoProcessorSetOutputTargetRect(vp, TRUE, &targetRect);

                    D3D11_VIDEO_PROCESSOR_COLOR_SPACE csRGB = {};
                    csRGB.Usage = 0;
                    csRGB.RGB_Range = 0; // 0-255 Full
                    csRGB.YCbCr_Matrix = 1; // 709
                    csRGB.Nominal_Range = D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_0_255;
                    videoContext->VideoProcessorSetStreamColorSpace(vp, 1, &csRGB);

                    D3D11_VIDEO_PROCESSOR_COLOR_SPACE csYUV = {};
                    csYUV.Usage = 0;
                    csYUV.RGB_Range = 1; // Studio
                    csYUV.YCbCr_Matrix = 1; // 709
                    csYUV.Nominal_Range = D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_16_235;
                    videoContext->VideoProcessorSetStreamColorSpace(vp, 0, &csYUV);
                    videoContext->VideoProcessorSetOutputColorSpace(vp, &csYUV);

                    hr = videoContext->VideoProcessorBlt(vp, outView, 0, 2, streams);
                    std::cout << "[Probe] VideoProcessorBlt with 2 streams (NV12 + RGBA overlay with color space): 0x" << std::hex << hr << std::dec << std::endl;

                    // Read back a pixel from outTex where overlay was placed (50, 50)
                    D3D11_TEXTURE2D_DESC oDesc = texDesc;
                    oDesc.Usage = D3D11_USAGE_STAGING;
                    oDesc.BindFlags = 0;
                    oDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
                    ID3D11Texture2D* oStaging = nullptr;
                    device->CreateTexture2D(&oDesc, nullptr, &oStaging);
                    context->CopyResource(oStaging, outTex);
                    D3D11_MAPPED_SUBRESOURCE oMapped = {};
                    context->Map(oStaging, 0, D3D11_MAP_READ, 0, &oMapped);
                    uint8_t* pY = (uint8_t*)oMapped.pData;
                    // Position (50, 50)
                    int yVal = pY[50 * oMapped.RowPitch + 50];
                    std::cout << "[Probe] Y at (50,50) = " << yVal << std::endl;
                    // UV plane starts at height * RowPitch
                    int uvOffset = 2160 * oMapped.RowPitch + (50 / 2) * oMapped.RowPitch + (50 / 2) * 2;
                    int uVal = pY[uvOffset];
                    int vVal = pY[uvOffset + 1];
                    std::cout << "[Probe] UV at (50,50) = U:" << uVal << ", V:" << vVal << std::endl;
                    context->Unmap(oStaging, 0);
                    oStaging->Release();
                }

                if (rgbaView) rgbaView->Release();
                if (rgbaTex) rgbaTex->Release();

                if (inView) inView->Release();
                if (outView) outView->Release();
                if (inTex) inTex->Release();
                // outTex kept for encode test below

                vp->Release();
            } else {
                std::cout << "[Probe] CreateVideoProcessor failed: 0x" << std::hex << hr << std::dec << std::endl;
            }
            vpEnum->Release();
        } else {
            std::cout << "[Probe] CreateVideoProcessorEnumerator failed: 0x" << std::hex << hr << std::dec << std::endl;
        }
        videoDevice->Release();
        videoContext->Release();
    }

    // Now test FFmpeg D3D11VA hw_device_ctx
    AVBufferRef* hw_device_ctx = av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_D3D11VA);
    if (!hw_device_ctx) {
        std::cerr << "[Probe] av_hwdevice_ctx_alloc failed!" << std::endl;
        return 1;
    }
    AVHWDeviceContext* dev_ctx = (AVHWDeviceContext*)hw_device_ctx->data;
    AVD3D11VADeviceContext* d3d11_ctx = (AVD3D11VADeviceContext*)dev_ctx->hwctx;
    d3d11_ctx->device = device;
    device->AddRef();
    d3d11_ctx->device_context = context;
    context->AddRef();

    int ret = av_hwdevice_ctx_init(hw_device_ctx);
    if (ret < 0) {
        std::cerr << "[Probe] av_hwdevice_ctx_init failed: " << ret << std::endl;
        return 1;
    }
    std::cout << "[Probe] FFmpeg D3D11VA hw_device_ctx initialized successfully!" << std::endl;

    // Test opening hevc_amf with D3D11 frames context
    const AVCodec* enc_codec = avcodec_find_encoder_by_name("hevc_amf");
    if (!enc_codec) {
        std::cout << "[Probe] hevc_amf encoder not found in FFmpeg." << std::endl;
    } else {
        std::cout << "[Probe] Found hevc_amf encoder!" << std::endl;
        AVCodecContext* enc_ctx = avcodec_alloc_context3(enc_codec);
        enc_ctx->width = 3840;
        enc_ctx->height = 2160;
        enc_ctx->pix_fmt = AV_PIX_FMT_D3D11;
        enc_ctx->time_base = AVRational{ 1001, 30000 };
        enc_ctx->framerate = AVRational{ 30000, 1001 };
        enc_ctx->bit_rate = 20000000;

        AVBufferRef* hw_frames_ref = av_hwframe_ctx_alloc(hw_device_ctx);
        AVHWFramesContext* frames_ctx = (AVHWFramesContext*)hw_frames_ref->data;
        AVD3D11VAFramesContext* frames_hwctx = (AVD3D11VAFramesContext*)frames_ctx->hwctx;
        frames_ctx->format = AV_PIX_FMT_D3D11;
        frames_ctx->sw_format = AV_PIX_FMT_NV12;
        frames_ctx->width = 3840;
        frames_ctx->height = 2160;
        frames_ctx->initial_pool_size = 0;
        frames_hwctx->BindFlags = D3D11_BIND_SHADER_RESOURCE;

        ret = av_hwframe_ctx_init(hw_frames_ref);
        if (ret < 0) {
            std::cout << "[Probe] av_hwframe_ctx_init failed: " << ret << std::endl;
        } else {
            std::cout << "[Probe] av_hwframe_ctx_init SUCCEEDED for NV12 D3D11 frames (individual pool)!" << std::endl;
            enc_ctx->hw_frames_ctx = av_buffer_ref(hw_frames_ref);

            ret = avcodec_open2(enc_ctx, enc_codec, nullptr);
            if (ret < 0) {
                char errbuf[256];
                av_strerror(ret, errbuf, sizeof(errbuf));
                std::cout << "[Probe] avcodec_open2 hevc_amf failed: " << errbuf << std::endl;
            } else {
                std::cout << "[Probe] avcodec_open2 hevc_amf SUCCEEDED with zero-copy D3D11 hardware frames!" << std::endl;
                
                // Let's test allocating one hardware frame and sending it to the encoder!
                AVFrame* frame = av_frame_alloc();
                ret = av_hwframe_get_buffer(hw_frames_ref, frame, 0);
                if (ret < 0) {
                    std::cout << "[Probe] av_hwframe_get_buffer failed: " << ret << std::endl;
                } else {
                    std::cout << "[Probe] av_hwframe_get_buffer SUCCEEDED! Texture: " << frame->data[0]
                              << ", slice: " << (intptr_t)frame->data[1] << std::endl;
                    ID3D11Texture2D* encTex = (ID3D11Texture2D*)frame->data[0];
                    int encSlice = (int)(intptr_t)frame->data[1];

                    // Test CopySubresourceRegion from outTex to encTex
                    // NV12 has 2 planes (subresource 0 for Y, 1 for UV) or unified subresource depending on D3D11
                    // For planar/hybrid like NV12: Subresource index = MipSlice + (ArraySlice * MipLevels)
                    // For NV12 in D3D11, subresource 0 is the entire surface or planes
                    context->CopySubresourceRegion(encTex, D3D11CalcSubresource(0, encSlice, 1), 0, 0, 0,
                                                   outTex, 0, nullptr);
                    std::cout << "[Probe] CopySubresourceRegion to encTex SUCCEEDED!" << std::endl;

                    frame->pts = 0;
                    ret = avcodec_send_frame(enc_ctx, frame);
                    std::cout << "[Probe] avcodec_send_frame returned: " << ret << std::endl;

                    AVPacket* pkt = av_packet_alloc();
                    ret = avcodec_receive_packet(enc_ctx, pkt);
                    std::cout << "[Probe] avcodec_receive_packet returned: " << ret
                              << (ret == 0 ? " (got packet!)" : " (need more frames)") << std::endl;
                    av_packet_free(&pkt);
                }
                av_frame_free(&frame);
                avcodec_free_context(&enc_ctx);
            }
        }
        av_buffer_unref(&hw_frames_ref);
    }

    if (outTex) outTex->Release();
    av_buffer_unref(&hw_device_ctx);
    context->Release();
    device->Release();
    std::cout << "[Probe] Done." << std::endl;
    return 0;
}
