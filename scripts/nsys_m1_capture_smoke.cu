#include <cuda_runtime.h>
#include <nvtx3/nvToolsExt.h>
#include <cstdio>
#include <cstring>

__global__ void add_one(int* data) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < 32) data[i] = i + 1;
}

static bool check(cudaError_t status, const char* step) {
    std::printf("%s cuda_status=%d (%s)\n", step, int(status), cudaGetErrorString(status));
    return status == cudaSuccess;
}

int main() {
    nvtxDomainHandle_t domain = nvtxDomainCreateA("CoOverlapM1");
    nvtxStringHandle_t registered = nvtxDomainRegisterStringA(domain, "M1_SMOKE");
    nvtxEventAttributes_t attr{};
    attr.version = NVTX_VERSION;
    attr.size = NVTX_EVENT_ATTRIB_STRUCT_SIZE;
    attr.messageType = NVTX_MESSAGE_TYPE_REGISTERED;
    attr.message.registered = registered;
    nvtxDomainRangePushEx(domain, &attr);
    int* device = nullptr;
    int host[32]{};
    bool ok = check(cudaMalloc(&device, sizeof(host)), "malloc");
    if (ok) {
        add_one<<<1, 32>>>(device);
        ok = check(cudaGetLastError(), "kernel_launch");
    }
    if (ok) ok = check(cudaMemcpy(host, device, sizeof(host), cudaMemcpyDeviceToHost), "copy_sync");
    if (device) ok = check(cudaFree(device), "free") && ok;
    nvtxDomainRangePop(domain);
    nvtxDomainDestroy(domain);
    for (int i = 0; i < 32; ++i) if (host[i] != i + 1) ok = false;
    std::printf("numeric_status=%s first=%d last=%d\n", ok ? "PASS" : "FAIL", host[0], host[31]);
    return ok ? 0 : 1;
}
