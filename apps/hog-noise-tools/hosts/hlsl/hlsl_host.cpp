// HogNoise tools: the HLSL host harness. noise.hlsl's compiled entry points dispatched through D3D11 (FXC's cs_5_0)
// or D3D12 (DXC's cs_6_0) on WARP, written from hog_noise/shaders/README.md alone.
//
// The frames, the refusals and the loop are frames.h's, shared with the Vulkan harness; this file is the two D3D back
// ends. Run with --api d3d11|d3d12. Built by build.bat with MSVC; the .exe is gitignored.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "../frames.h"

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "d3d12.lib")
#pragma comment(lib, "dxgi.lib")

using Microsoft::WRL::ComPtr;
using frames::Backend;
using frames::Bytes;
using frames::Request;
using frames::round_up;
using frames::Unavailable;

namespace {

void check(HRESULT hr, const char* what) {
    if (FAILED(hr)) {
        char text[160];
        std::snprintf(text, sizeof text, "%s failed: HRESULT 0x%08lX", what, static_cast<unsigned long>(hr));
        throw std::runtime_error(text);
    }
}

std::string utf8(const wchar_t* wide) {
    int n = WideCharToMultiByte(CP_UTF8, 0, wide, -1, nullptr, 0, nullptr, nullptr);
    std::string out(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, wide, -1, out.data(), n, nullptr, nullptr);
    return out;
}

ComPtr<IDXGIAdapter1> warp_adapter() {
    ComPtr<IDXGIFactory4> factory;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) throw Unavailable("CreateDXGIFactory1 failed: no DXGI");
    ComPtr<IDXGIAdapter1> adapter;
    if (FAILED(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)))) throw Unavailable("no WARP adapter");
    return adapter;
}

std::string describe(IDXGIAdapter1* adapter, const char* api) {
    DXGI_ADAPTER_DESC1 desc{};
    check(adapter->GetDesc1(&desc), "IDXGIAdapter1::GetDesc1");
    return utf8(desc.Description) + " (" + api + ")";
}

// ---------------------------------------------------------------- D3D11

struct D3D11 : Backend {
    ComPtr<ID3D11Device> dev;
    ComPtr<ID3D11DeviceContext> ctx;
    std::vector<ComPtr<ID3D11ComputeShader>> programs;
    ComPtr<ID3D11ShaderResourceView> tables;

    D3D11() {
        auto adapter = warp_adapter();
        D3D_FEATURE_LEVEL want = D3D_FEATURE_LEVEL_11_0;
        if (FAILED(D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, 0, &want, 1, D3D11_SDK_VERSION,
                                     &dev, nullptr, &ctx)))
            throw Unavailable("D3D11CreateDevice on WARP failed");
        target = describe(adapter.Get(), "D3D11");
    }

    ComPtr<ID3D11Buffer> buffer(const void* data, size_t bytes, UINT bind, UINT misc) {
        D3D11_BUFFER_DESC d{};
        d.ByteWidth = static_cast<UINT>(bytes);
        d.Usage = D3D11_USAGE_DEFAULT;
        d.BindFlags = bind;
        d.MiscFlags = misc;
        D3D11_SUBRESOURCE_DATA init{data, 0, 0};
        ComPtr<ID3D11Buffer> b;
        check(dev->CreateBuffer(&d, data ? &init : nullptr, &b), "ID3D11Device::CreateBuffer");
        return b;
    }

    // a ByteAddressBuffer: a raw view over the whole buffer
    ComPtr<ID3D11ShaderResourceView> raw_srv(const void* data, size_t bytes) {
        auto b = buffer(data, bytes, D3D11_BIND_SHADER_RESOURCE, D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS);
        D3D11_SHADER_RESOURCE_VIEW_DESC v{};
        v.Format = DXGI_FORMAT_R32_TYPELESS;
        v.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
        v.BufferEx.NumElements = static_cast<UINT>(bytes / 4);
        v.BufferEx.Flags = D3D11_BUFFEREX_SRV_FLAG_RAW;
        ComPtr<ID3D11ShaderResourceView> srv;
        check(dev->CreateShaderResourceView(b.Get(), &v, &srv), "CreateShaderResourceView");
        return srv;
    }

    // a cbuffer: its size a multiple of 16
    ComPtr<ID3D11Buffer> constants(const Bytes& data) {
        Bytes padded(round_up(std::max<size_t>(data.size(), 16), 16), 0);
        std::memcpy(padded.data(), data.data(), data.size());
        return buffer(padded.data(), padded.size(), D3D11_BIND_CONSTANT_BUFFER, 0);
    }

    void load(const Bytes& t, const std::vector<Bytes>& blobs) override {
        tables = raw_srv(t.data(), t.size());
        for (size_t i = 0; i < blobs.size(); ++i) {
            ComPtr<ID3D11ComputeShader> cs;
            check(dev->CreateComputeShader(blobs[i].data(), blobs[i].size(), nullptr, &cs),
                  ("CreateComputeShader (" + names.at(i) + ")").c_str());
            programs.push_back(cs);
        }
    }

    std::vector<float> run(const Request& r) override {
        const size_t out_bytes = size_t(r.n) * r.width * 4;
        static const float unused_axis = 0.0f;  // the README: a one-float buffer for an unused coordinate
        auto params = constants(r.params);
        auto grid = constants(r.grid.empty() ? Bytes(48, 0) : r.grid);  // and 48 zero bytes for an unused Grid
        ComPtr<ID3D11ShaderResourceView> srvs[4] = {tables};
        for (int i = 0; i < 3; ++i)
            srvs[1 + i] = i < int(r.axes.size()) ? raw_srv(r.axes[i].data(), r.axes[i].size())
                                                 : raw_srv(&unused_axis, 4);
        auto out = buffer(nullptr, out_bytes, D3D11_BIND_UNORDERED_ACCESS, D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS);
        D3D11_UNORDERED_ACCESS_VIEW_DESC u{};
        u.Format = DXGI_FORMAT_R32_TYPELESS;
        u.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
        u.Buffer.NumElements = static_cast<UINT>(out_bytes / 4);  // the shader's bound: GetDimensions on OUT
        u.Buffer.Flags = D3D11_BUFFER_UAV_FLAG_RAW;
        ComPtr<ID3D11UnorderedAccessView> uav;
        check(dev->CreateUnorderedAccessView(out.Get(), &u, &uav), "CreateUnorderedAccessView");

        ID3D11Buffer* b0 = params.Get();
        ID3D11Buffer* b6 = grid.Get();
        ID3D11ShaderResourceView* t[4] = {srvs[0].Get(), srvs[1].Get(), srvs[2].Get(), srvs[3].Get()};
        ID3D11UnorderedAccessView* u5 = uav.Get();
        ctx->CSSetShader(programs.at(r.entry).Get(), nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &b0);
        ctx->CSSetConstantBuffers(6, 1, &b6);
        ctx->CSSetShaderResources(1, 4, t);
        ctx->CSSetUnorderedAccessViews(5, 1, &u5, nullptr);
        ctx->Dispatch(r.gx, r.gy, 1);
        ID3D11UnorderedAccessView* none = nullptr;
        ctx->CSSetUnorderedAccessViews(5, 1, &none, nullptr);

        D3D11_BUFFER_DESC sd{};
        sd.ByteWidth = static_cast<UINT>(out_bytes);
        sd.Usage = D3D11_USAGE_STAGING;
        sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Buffer> staging;
        check(dev->CreateBuffer(&sd, nullptr, &staging), "CreateBuffer (staging)");
        ctx->CopyResource(staging.Get(), out.Get());
        D3D11_MAPPED_SUBRESOURCE m{};
        check(ctx->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &m), "ID3D11DeviceContext::Map");
        std::vector<float> values(out_bytes / 4);
        std::memcpy(values.data(), m.pData, out_bytes);
        ctx->Unmap(staging.Get(), 0);
        return values;
    }
};

// ---------------------------------------------------------------- D3D12

struct D3D12 : Backend {
    ComPtr<ID3D12Device> dev;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> alloc;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    UINT64 fence_value = 0;
    HANDLE event = nullptr;
    ComPtr<ID3D12RootSignature> root;
    std::vector<ComPtr<ID3D12PipelineState>> programs;
    ComPtr<ID3D12Resource> tables;
    UINT tables_bytes = 0;
    UINT stride = 0;

    D3D12() {
        auto adapter = warp_adapter();
        if (FAILED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&dev))))
            throw Unavailable("D3D12CreateDevice on WARP failed");
        target = describe(adapter.Get(), "D3D12");
        D3D12_COMMAND_QUEUE_DESC q{};
        q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        check(dev->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)), "CreateCommandQueue");
        check(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&alloc)),
              "CreateCommandAllocator");
        check(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc.Get(), nullptr, IID_PPV_ARGS(&list)),
              "CreateCommandList");
        check(list->Close(), "ID3D12GraphicsCommandList::Close");
        check(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event) throw std::runtime_error("CreateEventW failed: error " + std::to_string(GetLastError()));
        stride = dev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        make_root_signature();
    }

    ~D3D12() override {
        if (event) CloseHandle(event);
    }

    // The README's bindings as one descriptor table, b0, t1-t4, u5, b6, in that order. A table, not root
    // descriptors: the shader bounds every invocation by GetDimensions on OUT, and a root descriptor has no size.
    void make_root_signature() {
        D3D12_DESCRIPTOR_RANGE ranges[4] = {
            {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
            {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 4, 1, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
            {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 5, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
            {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 6, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
        };
        D3D12_ROOT_PARAMETER table{};
        table.ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        table.DescriptorTable.NumDescriptorRanges = 4;
        table.DescriptorTable.pDescriptorRanges = ranges;
        table.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_ROOT_SIGNATURE_DESC desc{1, &table, 0, nullptr, D3D12_ROOT_SIGNATURE_FLAG_NONE};
        ComPtr<ID3DBlob> blob, error;
        HRESULT hr = D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &error);
        if (FAILED(hr) && error) throw std::runtime_error(static_cast<const char*>(error->GetBufferPointer()));
        check(hr, "D3D12SerializeRootSignature");
        check(dev->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
              "CreateRootSignature");
    }

    ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE heap, size_t bytes, D3D12_RESOURCE_FLAGS flags,
                                  D3D12_RESOURCE_STATES state) {
        D3D12_HEAP_PROPERTIES hp{};
        hp.Type = heap;
        D3D12_RESOURCE_DESC d{};
        d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width = bytes;
        d.Height = 1;
        d.DepthOrArraySize = 1;
        d.MipLevels = 1;
        d.SampleDesc.Count = 1;
        d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        d.Flags = flags;
        ComPtr<ID3D12Resource> r;
        check(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&r)),
              "CreateCommittedResource");
        return r;
    }

    // an upload-heap buffer holding ``data``, at least ``size`` bytes
    ComPtr<ID3D12Resource> upload(const void* data, size_t n, size_t size) {
        auto r = buffer(D3D12_HEAP_TYPE_UPLOAD, size, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_GENERIC_READ);
        void* p = nullptr;
        check(r->Map(0, nullptr, &p), "ID3D12Resource::Map (upload)");
        std::memset(p, 0, size);
        std::memcpy(p, data, n);
        r->Unmap(0, nullptr);
        return r;
    }

    void load(const Bytes& t, const std::vector<Bytes>& blobs) override {
        tables_bytes = static_cast<UINT>(t.size());
        tables = upload(t.data(), t.size(), t.size());
        for (size_t i = 0; i < blobs.size(); ++i) {
            D3D12_COMPUTE_PIPELINE_STATE_DESC d{};
            d.pRootSignature = root.Get();
            d.CS = {blobs[i].data(), blobs[i].size()};
            ComPtr<ID3D12PipelineState> pso;
            check(dev->CreateComputePipelineState(&d, IID_PPV_ARGS(&pso)),
                  ("CreateComputePipelineState (" + names.at(i) + ")").c_str());
            programs.push_back(pso);
        }
    }

    void raw_srv(ID3D12Resource* r, UINT bytes, D3D12_CPU_DESCRIPTOR_HANDLE at) {
        D3D12_SHADER_RESOURCE_VIEW_DESC v{};
        v.Format = DXGI_FORMAT_R32_TYPELESS;
        v.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        v.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        v.Buffer.NumElements = bytes / 4;
        v.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
        dev->CreateShaderResourceView(r, &v, at);
    }

    void cbv(ID3D12Resource* r, UINT size, D3D12_CPU_DESCRIPTOR_HANDLE at) {
        D3D12_CONSTANT_BUFFER_VIEW_DESC v{r->GetGPUVirtualAddress(), size};
        dev->CreateConstantBufferView(&v, at);
    }

    void wait() {
        check(queue->Signal(fence.Get(), ++fence_value), "ID3D12CommandQueue::Signal");
        if (fence->GetCompletedValue() < fence_value) {
            check(fence->SetEventOnCompletion(fence_value, event), "SetEventOnCompletion");
            // a failed wait would read the output back before the GPU wrote it
            if (WaitForSingleObject(event, INFINITE) != WAIT_OBJECT_0)
                throw std::runtime_error("WaitForSingleObject on the fence failed: error " +
                                         std::to_string(GetLastError()));
        }
        check(dev->GetDeviceRemovedReason(), "the D3D12 device (removed)");
    }

    std::vector<float> run(const Request& r) override {
        const size_t out_bytes = size_t(r.n) * r.width * 4;
        static const float unused_axis = 0.0f;  // the README: a one-float buffer for an unused coordinate
        const Bytes grid_bytes = r.grid.empty() ? Bytes(48, 0) : r.grid;  // and 48 zero bytes for an unused Grid
        // a constant buffer view is a multiple of 256 bytes
        auto params = upload(r.params.data(), r.params.size(), round_up(r.params.size(), 256));
        auto grid = upload(grid_bytes.data(), grid_bytes.size(), round_up(grid_bytes.size(), 256));
        std::vector<ComPtr<ID3D12Resource>> axes;
        for (int i = 0; i < 3; ++i)
            axes.push_back(i < int(r.axes.size()) ? upload(r.axes[i].data(), r.axes[i].size(), r.axes[i].size())
                                                  : upload(&unused_axis, 4, 4));
        auto out = buffer(D3D12_HEAP_TYPE_DEFAULT, out_bytes, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                          D3D12_RESOURCE_STATE_COMMON);
        auto readback = buffer(D3D12_HEAP_TYPE_READBACK, out_bytes, D3D12_RESOURCE_FLAG_NONE,
                               D3D12_RESOURCE_STATE_COPY_DEST);

        D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 7,
                                      D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
        ComPtr<ID3D12DescriptorHeap> heap;
        check(dev->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)), "CreateDescriptorHeap");
        auto slot = [&](int i) {
            D3D12_CPU_DESCRIPTOR_HANDLE h = heap->GetCPUDescriptorHandleForHeapStart();
            h.ptr += SIZE_T(i) * stride;
            return h;
        };
        cbv(params.Get(), static_cast<UINT>(round_up(r.params.size(), 256)), slot(0));
        raw_srv(tables.Get(), tables_bytes, slot(1));
        for (int i = 0; i < 3; ++i)
            raw_srv(axes[i].Get(), static_cast<UINT>(i < int(r.axes.size()) ? r.axes[i].size() : 4), slot(2 + i));
        D3D12_UNORDERED_ACCESS_VIEW_DESC u{};
        u.Format = DXGI_FORMAT_R32_TYPELESS;
        u.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        u.Buffer.NumElements = static_cast<UINT>(out_bytes / 4);  // the shader's bound: GetDimensions on OUT
        u.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
        dev->CreateUnorderedAccessView(out.Get(), nullptr, &u, slot(5));
        cbv(grid.Get(), static_cast<UINT>(round_up(grid_bytes.size(), 256)), slot(6));

        check(alloc->Reset(), "ID3D12CommandAllocator::Reset");
        check(list->Reset(alloc.Get(), programs.at(r.entry).Get()), "ID3D12GraphicsCommandList::Reset");
        list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[] = {heap.Get()};
        list->SetDescriptorHeaps(1, heaps);
        list->SetComputeRootDescriptorTable(0, heap->GetGPUDescriptorHandleForHeapStart());
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition.pResource = out.Get();
        b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        list->ResourceBarrier(1, &b);
        list->Dispatch(r.gx, r.gy, 1);
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        list->ResourceBarrier(1, &b);
        list->CopyBufferRegion(readback.Get(), 0, out.Get(), 0, out_bytes);
        check(list->Close(), "ID3D12GraphicsCommandList::Close");
        ID3D12CommandList* lists[] = {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        wait();

        std::vector<float> values(out_bytes / 4);
        void* p = nullptr;
        D3D12_RANGE whole{0, out_bytes};
        check(readback->Map(0, &whole, &p), "ID3D12Resource::Map (readback)");
        std::memcpy(values.data(), p, out_bytes);
        D3D12_RANGE none{0, 0};
        readback->Unmap(0, &none);
        return values;
    }
};

std::unique_ptr<Backend> open_backend(const std::string& api) {
    if (api == "d3d11") return std::make_unique<D3D11>();
    if (api == "d3d12") return std::make_unique<D3D12>();
    throw std::runtime_error("unknown --api " + api + ": d3d11 or d3d12");
}

}  // namespace

int main(int argc, char** argv) { return frames::serve(argc, argv, open_backend); }
