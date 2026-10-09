#include <d3d11.h>
#include <d3d11_1.h>
#include <iostream>
#include <wrl/client.h>
#include <vector>

using Microsoft::WRL::ComPtr;

int main() {
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    D3D_FEATURE_LEVEL featureLevel;
    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
        nullptr, 0, D3D11_SDK_VERSION,
        &device, &featureLevel, &context
    );
    if (FAILED(hr)) return 1;

    ComPtr<ID3D11VideoDevice> videoDevice;
    device.As(&videoDevice);
    ComPtr<ID3D11VideoContext> videoContext;
    context.As(&videoContext);
    ComPtr<ID3D11VideoContext1> videoContext1;
    context.As(&videoContext1);

    D3D11_VIDEO_PROCESSOR_CONTENT_DESC desc = {};
    desc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    desc.InputWidth = 64;
    desc.InputHeight = 64;
    desc.OutputWidth = 64;
    desc.OutputHeight = 64;
    desc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    ComPtr<ID3D11VideoProcessorEnumerator> vpEnum;
    videoDevice->CreateVideoProcessorEnumerator(&desc, &vpEnum);

    ComPtr<ID3D11VideoProcessor> vp;
    videoDevice->CreateVideoProcessor(vpEnum.Get(), 0, &vp);

    // Create input and output textures (64x64 NV12)
    D3D11_TEXTURE2D_DESC tDesc = {};
    tDesc.Width = 64;
    tDesc.Height = 64;
    tDesc.MipLevels = 1;
    tDesc.ArraySize = 1;
    tDesc.Format = DXGI_FORMAT_NV12;
    tDesc.SampleDesc.Count = 1;
    tDesc.Usage = D3D11_USAGE_DEFAULT;
    tDesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

    ComPtr<ID3D11Texture2D> inTex, outTex;
    device->CreateTexture2D(&tDesc, nullptr, &inTex);
    device->CreateTexture2D(&tDesc, nullptr, &outTex);

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC ivDesc = {};
    ivDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    ComPtr<ID3D11VideoProcessorInputView> inView;
    videoDevice->CreateVideoProcessorInputView(inTex.Get(), vpEnum.Get(), &ivDesc, &inView);

    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC ovDesc = {};
    ovDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    ComPtr<ID3D11VideoProcessorOutputView> outView;
    videoDevice->CreateVideoProcessorOutputView(outTex.Get(), vpEnum.Get(), &ovDesc, &outView);

    // Fill top-left corner of inTex with bright Y (255), rest with dark Y (16)
    std::vector<uint8_t> initData(64 * 64 + 64 * 32, 16);
    // top-left 16x16 pixels bright Y
    for (int y = 0; y < 16; ++y) {
        for (int x = 0; x < 16; ++x) {
            initData[y * 64 + x] = 235;
        }
    }
    // UV = 128
    memset(initData.data() + 64 * 64, 128, 64 * 32);

    context->UpdateSubresource(inTex.Get(), 0, nullptr, initData.data(), 64, 0);

    // Set rotation 180!
    videoContext1->VideoProcessorSetStreamRotation(vp.Get(), 0, TRUE, D3D11_VIDEO_PROCESSOR_ROTATION_180);

    RECT r = {0, 0, 64, 64};
    videoContext->VideoProcessorSetStreamSourceRect(vp.Get(), 0, TRUE, &r);
    videoContext->VideoProcessorSetStreamDestRect(vp.Get(), 0, TRUE, &r);

    D3D11_VIDEO_PROCESSOR_STREAM stream = {};
    stream.Enable = TRUE;
    stream.pInputSurface = inView.Get();

    hr = videoContext->VideoProcessorBlt(vp.Get(), outView.Get(), 0, 1, &stream);
    std::cout << "VideoProcessorBlt with ROTATION_180 HR: 0x" << std::hex << hr << std::dec << std::endl;

    // Read back outTex
    D3D11_TEXTURE2D_DESC sDesc = tDesc;
    sDesc.Usage = D3D11_USAGE_STAGING;
    sDesc.BindFlags = 0;
    sDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> stageTex;
    device->CreateTexture2D(&sDesc, nullptr, &stageTex);

    context->CopyResource(stageTex.Get(), outTex.Get());

    D3D11_MAPPED_SUBRESOURCE mapped = {};
    hr = context->Map(stageTex.Get(), 0, D3D11_MAP_READ, 0, &mapped);
    if (SUCCEEDED(hr)) {
        uint8_t* p = (uint8_t*)mapped.pData;
        // Check top-left corner (0,0) vs bottom-right corner (63,63)
        uint8_t topLeft = p[0];
        uint8_t bottomRight = p[63 * mapped.RowPitch + 63];
        std::cout << "Top-left Y: " << (int)topLeft << std::endl;
        std::cout << "Bottom-right Y: " << (int)bottomRight << std::endl;
        if (topLeft < 50 && bottomRight > 200) {
            std::cout << "SUCCESS: The bright patch moved from top-left to bottom-right! ROTATION_180 WORKS!" << std::endl;
        } else {
            std::cout << "Rotation test unexpected result!" << std::endl;
        }
        context->Unmap(stageTex.Get(), 0);
    }

    return 0;
}
