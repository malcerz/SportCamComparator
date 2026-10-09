#include "ExportPreview.h"
#include <wincodec.h>
#include <objidl.h>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <vector>
#include <deque>
#include <chrono>
#include <algorithm>
#include <cassert>
#include <iostream>

struct ExportPreview::Worker {
    struct Image { std::vector<BYTE> pixels; double pts; int64_t frame; };
    std::mutex mutex;
    std::condition_variable ready;
    std::deque<Image> queue;
    std::atomic<bool> stop{false}, failed{false};
    std::atomic<uint64_t> generated{0}, encodedBytes{0}, dropped{0}, cpuUs{0};
    std::string reason;
    HANDLE wake = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    ~Worker() { CloseHandle(wake); }

    void Run(std::string pipeName, int w, int h) {
        HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        ComPtr<IWICImagingFactory> factory;
        HANDLE pipe = INVALID_HANDLE_VALUE;
        HANDLE event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        auto fail = [&](const char* message) {
            std::lock_guard<std::mutex> lock(mutex);
            reason = message; failed = true;
        };
        if (FAILED(com) || FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr,
                CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory)))) fail("WIC initialization failed");
        std::wstring path = L"\\\\.\\pipe\\";
        path.append(pipeName.begin(), pipeName.end()); // GUI names are ASCII UUIDs.
        if (!failed && !stop) {
            pipe = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
                               FILE_FLAG_OVERLAPPED, nullptr);
            if (pipe == INVALID_HANDLE_VALUE) fail("Preview IPC connection failed");
        }
        while (!failed && !stop) {
            Image image;
            {
                std::unique_lock<std::mutex> lock(mutex);
                ready.wait(lock, [&] { return stop || !queue.empty(); });
                if (stop) break;
                image = std::move(queue.back());
                dropped += queue.size() - 1;
                queue.clear();
            }
            auto started = std::chrono::steady_clock::now();
            ComPtr<IStream> stream;
            ComPtr<IWICBitmapEncoder> encoder;
            ComPtr<IWICBitmapFrameEncode> frame;
            ComPtr<IPropertyBag2> options;
            HRESULT hr = CreateStreamOnHGlobal(nullptr, TRUE, &stream);
            if (SUCCEEDED(hr)) hr = factory->CreateEncoder(GUID_ContainerFormatJpeg, nullptr, &encoder);
            if (SUCCEEDED(hr)) hr = encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache);
            if (SUCCEEDED(hr)) hr = encoder->CreateNewFrame(&frame, &options);
            if (SUCCEEDED(hr)) {
                PROPBAG2 property{}; property.pstrName = const_cast<wchar_t*>(L"ImageQuality");
                VARIANT value{}; value.vt = VT_R4; value.fltVal = .8f;
                hr = options->Write(1, &property, &value);
            }
            if (SUCCEEDED(hr)) hr = frame->Initialize(options.Get());
            if (SUCCEEDED(hr)) hr = frame->SetSize(w, h);
            // WIC JPEG uses BGR. Convert only the already downscaled thumbnail.
            std::vector<BYTE> bgr(size_t(w)*h*3);
            for (size_t i=0; i<size_t(w)*h; ++i)
                std::copy_n(image.pixels.data()+i*4, 3, bgr.data()+i*3);
            WICPixelFormatGUID format = GUID_WICPixelFormat24bppBGR;
            if (SUCCEEDED(hr)) hr = frame->SetPixelFormat(&format);
            if (SUCCEEDED(hr) && format != GUID_WICPixelFormat24bppBGR) hr = E_FAIL;
            if (SUCCEEDED(hr)) hr = frame->WritePixels(h, w*3, static_cast<UINT>(bgr.size()), bgr.data());
            if (SUCCEEDED(hr)) hr = frame->Commit();
            if (SUCCEEDED(hr)) hr = encoder->Commit();
            if (FAILED(hr)) { fail("WIC JPEG encoding failed"); break; }
            STATSTG stat{};
            hr = stream->Stat(&stat, STATFLAG_NONAME);
            LARGE_INTEGER zero{};
            if (SUCCEEDED(hr)) hr = stream->Seek(zero, STREAM_SEEK_SET, nullptr);
            std::string metadata = nlohmann::json({{"type","preview"},{"frame",image.frame},
                {"pts",image.pts},{"width",w},{"height",h},{"encoding","jpeg"}}).dump();
            uint32_t header[2] = {static_cast<uint32_t>(metadata.size()), static_cast<uint32_t>(stat.cbSize.QuadPart)};
            std::vector<BYTE> packet(8 + metadata.size() + header[1]);
            memcpy(packet.data(), header, 8);
            memcpy(packet.data()+8, metadata.data(), metadata.size());
            ULONG got = 0;
            if (SUCCEEDED(hr)) hr = stream->Read(packet.data()+8+metadata.size(), header[1], &got);
            if (FAILED(hr) || got != header[1]) { fail("JPEG memory stream read failed"); break; }
            generated++; encodedBytes += got;
            cpuUs += static_cast<uint64_t>(std::chrono::duration<double,std::micro>(
                std::chrono::steady_clock::now()-started).count());
            if (stop) break;
            // Only the CPU worker waits, for at most 20 ms. A partial timed-out
            // packet cannot be dropped on a byte stream: disconnect and disable.
            size_t offset = 0;
            while (offset < packet.size() && !stop && !failed) {
                ResetEvent(event);
                OVERLAPPED io{}; io.hEvent = event;
                DWORD written = 0;
                BOOL ok = WriteFile(pipe, packet.data()+offset,
                    static_cast<DWORD>(packet.size()-offset), &written, &io);
                if (!ok && GetLastError() == ERROR_IO_PENDING) {
                    HANDLE events[] = {wake, event};
                    DWORD result = WaitForMultipleObjects(2, events, FALSE, 20);
                    if (result != WAIT_OBJECT_0+1) {
                        CancelIoEx(pipe, &io);
                        // Worker only: keep OVERLAPPED and buffer alive until cancellation completes.
                        GetOverlappedResult(pipe, &io, &written, TRUE);
                        dropped++;
                        if (!stop) fail("Preview IPC backpressure; channel disabled");
                        break;
                    }
                    ok = GetOverlappedResult(pipe, &io, &written, FALSE);
                }
                if (!ok || !written) { if (!stop) fail("Preview IPC disconnected"); break; }
                offset += written;
            }
        }
        if (pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe);
        CloseHandle(event);
        factory.Reset();
        if (SUCCEEDED(com)) CoUninitialize();
    }
};

ExportPreview::~ExportPreview() { Stop(); }
void ExportPreview::Stop() {
    enabled = false;
    if (worker) {
        worker->stop = true;
        SetEvent(worker->wake);
        worker->ready.notify_one();
        // Detached worker owns its state and CPU pixels; cancellation never joins JPEG/IPC.
    }
    for (auto& slot : slots) if (slot.pending) { drops++; slot.pending = false; }
}
void ExportPreview::Disable(const std::string& reason) {
    std::cerr << nlohmann::json({{"type","warning"},
        {"message","PREVIEW_DISABLED_AFTER_ERROR: " + reason}}).dump() << std::endl;
    Stop();
}

void ExportPreview::Initialize(ID3D11Texture2D* canvas, const std::string& pipe, bool injectFailure,
                               int requestedWidth, int requestedHeight, double requestedFps) try {
    if (pipe.empty()) return;
    if (injectFailure) { Disable("diagnostic preview failure"); return; }
    D3D11_TEXTURE2D_DESC source{}; canvas->GetDesc(&source);
    double scale = (std::min)({1., double(requestedWidth)/source.Width, double(requestedHeight)/source.Height});
    width = (std::max)(2, int(source.Width*scale)/2*2); height = (std::max)(2, int(source.Height*scale)/2*2);
    sampleInterval = 1.0/(std::max)(0.1, (std::min)(5.0, requestedFps));
    assert(width<=1600 && height<=900);
    auto check = [&](HRESULT hr, const char* reason) { if (FAILED(hr)) { Disable(reason); return false; } return true; };
    D3D11_VIDEO_PROCESSOR_CONTENT_DESC content{};
    content.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    content.InputWidth = source.Width; content.InputHeight = source.Height;
    content.OutputWidth = width; content.OutputHeight = height;
    content.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;
    if (!check(ctx.GetVideoDevice()->CreateVideoProcessorEnumerator(&content,&enumerator),"Preview enumerator")) return;
    if (!check(ctx.GetVideoDevice()->CreateVideoProcessor(enumerator.Get(),0,&processor),"Preview processor")) return;
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width=width; desc.Height=height; desc.MipLevels=1; desc.ArraySize=1;
    desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM; desc.SampleDesc.Count=1;
    desc.Usage=D3D11_USAGE_DEFAULT; desc.BindFlags=D3D11_BIND_RENDER_TARGET;
    if (!check(ctx.GetDevice()->CreateTexture2D(&desc,nullptr,&thumbnailTexture),"Preview BGRA texture")) return;
    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC iv{}; iv.ViewDimension=D3D11_VPIV_DIMENSION_TEXTURE2D;
    if (!check(ctx.GetVideoDevice()->CreateVideoProcessorInputView(canvas,enumerator.Get(),&iv,&input),"Preview final canvas view")) return;
    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC ov{}; ov.ViewDimension=D3D11_VPOV_DIMENSION_TEXTURE2D;
    if (!check(ctx.GetVideoDevice()->CreateVideoProcessorOutputView(thumbnailTexture.Get(),enumerator.Get(),&ov,&output),"Preview BGRA view")) return;
    desc.Usage=D3D11_USAGE_STAGING; desc.BindFlags=0; desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    for (auto& slot : slots) {
        if (!check(ctx.GetDevice()->CreateTexture2D(&desc,nullptr,&slot.staging),"Preview staging")) return;
        D3D11_QUERY_DESC q{D3D11_QUERY_EVENT,0};
        if (!check(ctx.GetDevice()->CreateQuery(&q,&slot.done),"Preview completion query")) return;
        q.Query=D3D11_QUERY_TIMESTAMP;
        if (!check(ctx.GetDevice()->CreateQuery(&q,&slot.begin),"Preview timestamp") ||
            !check(ctx.GetDevice()->CreateQuery(&q,&slot.end),"Preview timestamp")) return;
        q.Query=D3D11_QUERY_TIMESTAMP_DISJOINT;
        if (!check(ctx.GetDevice()->CreateQuery(&q,&slot.disjoint),"Preview disjoint query")) return;
    }
    RECT src{0,0,LONG(source.Width),LONG(source.Height)}, dst{0,0,width,height};
    auto vc=ctx.GetVideoContext();
    vc->VideoProcessorSetStreamSourceRect(processor.Get(),0,TRUE,&src);
    vc->VideoProcessorSetStreamDestRect(processor.Get(),0,TRUE,&dst);
    vc->VideoProcessorSetOutputTargetRect(processor.Get(),TRUE,&dst);
    vc->VideoProcessorSetStreamFrameFormat(processor.Get(),0,D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
    vc->VideoProcessorSetStreamAutoProcessingMode(processor.Get(),0,FALSE);
    D3D11_VIDEO_PROCESSOR_COLOR_SPACE yuv{}; yuv.YCbCr_Matrix=1;
    vc->VideoProcessorSetStreamColorSpace(processor.Get(),0,&yuv);
    D3D11_VIDEO_PROCESSOR_COLOR_SPACE rgb{}; rgb.RGB_Range=0;
    vc->VideoProcessorSetOutputColorSpace(processor.Get(),&rgb);
    worker=std::make_shared<Worker>();
    auto state=worker;
    std::thread([state,pipe,w=width,h=height]{
        try { state->Run(pipe,w,h); }
        catch (const std::exception& error) {
            std::lock_guard<std::mutex> lock(state->mutex);
            state->reason = error.what(); state->failed = true;
        }
    }).detach();
    enabled=true;
} catch (const std::exception& error) { Disable(error.what()); }

void ExportPreview::Tick(double pts, int64_t frame) try {
    if (!enabled) return;
    if (worker->failed) { Disable(worker->reason); return; }
    auto dc=ctx.GetContext();
    // Poll old submissions before scheduling this frame, never immediately map a new copy.
    for (auto& slot : slots) if (slot.pending && slot.frame < frame) {
        BOOL complete=FALSE;
        HRESULT hr=dc->GetData(slot.done.Get(),&complete,sizeof(complete),D3D11_ASYNC_GETDATA_DONOTFLUSH);
        if (FAILED(hr)) { Disable("Preview completion query failed"); return; }
        if (hr==S_FALSE || !complete) continue;
        Worker::Image image{{},slot.pts,slot.frame};
        image.pixels.resize(size_t(width)*height*4);
        D3D11_MAPPED_SUBRESOURCE mapped{};
        hr=dc->Map(slot.staging.Get(),0,D3D11_MAP_READ,D3D11_MAP_FLAG_DO_NOT_WAIT,&mapped);
        if (hr==DXGI_ERROR_WAS_STILL_DRAWING) continue;
        if (FAILED(hr)) { Disable("Preview nonblocking Map failed"); return; }
        for (int y=0;y<height;++y) memcpy(image.pixels.data()+size_t(y)*width*4,
            static_cast<BYTE*>(mapped.pData)+size_t(y)*mapped.RowPitch,size_t(width)*4);
        dc->Unmap(slot.staging.Get(),0);
        readbacks++; bytes+=image.pixels.size(); slot.pending=false;
        UINT64 begin=0,end=0; D3D11_QUERY_DATA_TIMESTAMP_DISJOINT timing{};
        if (dc->GetData(slot.disjoint.Get(),&timing,sizeof(timing),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK &&
            !timing.Disjoint && timing.Frequency &&
            dc->GetData(slot.begin.Get(),&begin,sizeof(begin),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK &&
            dc->GetData(slot.end.Get(),&end,sizeof(end),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK) {
            gpuMs+=1000.*double(end-begin)/timing.Frequency; gpuSamples++;
        }
        std::unique_lock<std::mutex> lock(worker->mutex,std::try_to_lock);
        if (!lock.owns_lock()) { drops++; continue; }
        if (worker->queue.size()==2) { worker->queue.pop_front(); worker->dropped++; }
        worker->queue.push_back(std::move(image));
        lock.unlock(); worker->ready.notify_one();
    }
    if (pts < nextPts) return;
    nextPts+=sampleInterval; requests++;
    Slot* available=nullptr;
    for (auto& slot : slots) if (!slot.pending) { available=&slot; break; }
    if (!available) { drops++; return; }
    auto& slot=*available;
    dc->Begin(slot.disjoint.Get()); dc->End(slot.begin.Get());
    D3D11_VIDEO_PROCESSOR_STREAM stream{}; stream.Enable=TRUE; stream.pInputSurface=input.Get();
    HRESULT hr=ctx.GetVideoContext()->VideoProcessorBlt(processor.Get(),output.Get(),0,1,&stream);
    if (FAILED(hr)) { dc->End(slot.disjoint.Get()); Disable("Preview GPU scale/color conversion failed"); return; }
    dc->CopyResource(slot.staging.Get(),thumbnailTexture.Get());
    dc->End(slot.end.Get()); dc->End(slot.disjoint.Get()); dc->End(slot.done.Get());
    slot.pending=true; slot.pts=pts; slot.frame=frame;
} catch (const std::exception& error) { Disable(error.what()); }

nlohmann::json ExportPreview::Metrics() const {
    uint64_t generated=worker?worker->generated.load():0;
    return {{"PREVIEW_REQUEST_COUNT",requests},{"PREVIEW_GENERATED_COUNT",generated},
        {"PREVIEW_DROPPED_COUNT",drops+(worker?worker->dropped.load():0)},
        {"PREVIEW_READBACK_COUNT",readbacks},{"PREVIEW_READBACK_BYTES",bytes},
        {"PREVIEW_ENCODED_BYTES",worker?worker->encodedBytes.load():0},
        {"PREVIEW_AVG_GPU_MS",gpuSamples?gpuMs/gpuSamples:0.},
        {"PREVIEW_AVG_CPU_MS",generated?double(worker->cpuUs.load())/generated/1000.:0.},
        {"PREVIEW_GPU_TIMING_SAMPLES",gpuSamples},{"PREVIEW_WIDTH",width},{"PREVIEW_HEIGHT",height},
        {"PREVIEW_STAGING_SLOTS",3},{"PREVIEW_RENDER_THREAD_WAIT_COUNT",0}};
}
