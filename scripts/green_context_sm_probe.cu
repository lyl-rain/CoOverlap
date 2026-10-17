// CUDA 13.2 Green Context functional probe. Prepare/review only; DO NOT run
// before separate approval. No timing or model performance measurement.
#include <cuda_runtime.h>
#include <algorithm>
#include <cstdio>
#include <set>
#include <vector>

__global__ void probe(int* ids, int* values, int n) {
    int sm;
    asm volatile("mov.u32 %0, %%smid;" : "=r"(sm));
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) { ids[i] = sm; values[i] = i + 7; }
}

static bool check(cudaError_t e, const char* where) {
    if (e == cudaSuccess) return true;
    std::fprintf(stderr, "%s: %d %s\n", where, int(e), cudaGetErrorString(e));
    return false;
}

int main() {
    constexpr int N = 4096;
    constexpr int BLOCK = 64;
    int* ids = nullptr; int* vals = nullptr;
    cudaStream_t ordinary = nullptr, green = nullptr;
    cudaExecutionContext_t ctx = nullptr;
    cudaEvent_t done = nullptr;
    int rc = 1;
    cudaDevResource all{}, remaining{}, bound{};
    cudaDevResource ordinary_bound{};
    cudaDevResourceDesc_t desc = nullptr;
    std::vector<cudaDevResource> groups;
    unsigned count = 0;
    std::set<int> normal_ids, green_ids;
    std::vector<int> hids(N), hvals(N);

    if (!check(cudaSetDevice(0), "cudaSetDevice")) goto cleanup;
    if (!check(cudaDeviceGetDevResource(0, &all, cudaDevResourceTypeSm), "query SM resource")) goto cleanup;
    std::printf("device SM=%u min=%u align=%u\n", all.sm.smCount,
                all.sm.minSmPartitionSize, all.sm.smCoscheduledAlignment);
    // Reviewed initial request: 8 SM, only if the queried resource permits it.
    if (all.sm.smCount != 16 || all.sm.minSmPartitionSize > 8 ||
        (8 % all.sm.smCoscheduledAlignment) != 0) {
        std::fprintf(stderr, "unexpected resource constraints; stop without creating context\n");
        goto cleanup;
    }
    if (!check(cudaDevSmResourceSplitByCount(nullptr, &count, &all, nullptr, 0, 8),
               "query split group count")) goto cleanup;
    if (count < 1 || count > 16) {
        std::fprintf(stderr, "invalid group count=%u\n", count); goto cleanup;
    }
    groups.resize(count);
    if (!check(cudaDevSmResourceSplitByCount(groups.data(), &count, &all, &remaining, 0, 8),
               "create resource groups")) goto cleanup;
    std::printf("groups=%u first=%u remaining=%u\n", count, groups[0].sm.smCount,
                remaining.type == cudaDevResourceTypeSm ? remaining.sm.smCount : 0);
    if (groups[0].sm.smCount != 8) {
        std::fprintf(stderr, "first group is not exactly 8 SM; stop\n"); goto cleanup;
    }
    if (!check(cudaDevResourceGenerateDesc(&desc, &groups[0], 1), "generate descriptor")) goto cleanup;
    if (!check(cudaGreenCtxCreate(&ctx, desc, 0, 0), "create Green Context")) goto cleanup;
    if (!check(cudaStreamCreateWithFlags(&ordinary, cudaStreamNonBlocking), "ordinary stream")) goto cleanup;
    if (!check(cudaExecutionCtxStreamCreate(&green, ctx, cudaStreamNonBlocking, 0),
               "Green Context stream")) goto cleanup;
    if (!check(cudaStreamGetDevResource(ordinary, &ordinary_bound, cudaDevResourceTypeSm),
               "query ordinary stream resource")) goto cleanup;
    if (!check(cudaStreamGetDevResource(green, &bound, cudaDevResourceTypeSm),
               "query Green stream resource")) goto cleanup;
    std::printf("ordinary stream reported SM=%u; Green stream reported SM=%u\n",
                ordinary_bound.sm.smCount, bound.sm.smCount);
    if (bound.sm.smCount != 8) goto cleanup;
    if (!check(cudaMalloc(reinterpret_cast<void**>(&ids), N * sizeof(int)), "malloc ids")) goto cleanup;
    if (!check(cudaMalloc(reinterpret_cast<void**>(&vals), N * sizeof(int)), "malloc values")) goto cleanup;
    if (!check(cudaEventCreateWithFlags(&done, cudaEventDisableTiming), "create event")) goto cleanup;

    for (int which = 0; which < 2; ++which) {
        cudaStream_t s = which ? green : ordinary;
        for (int trial = 0; trial < 3; ++trial) {
            probe<<<N / BLOCK, BLOCK, 0, s>>>(ids, vals, N);
            if (!check(cudaGetLastError(), "kernel launch")) goto cleanup;
            if (!check(cudaEventRecord(done, s), "event record")) goto cleanup;
            if (!check(cudaEventSynchronize(done), "event synchronize")) goto cleanup;
            if (!check(cudaMemcpy(hids.data(), ids, N * sizeof(int), cudaMemcpyDeviceToHost),
                       "copy ids")) goto cleanup;
            if (!check(cudaMemcpy(hvals.data(), vals, N * sizeof(int), cudaMemcpyDeviceToHost),
                       "copy values")) goto cleanup;
            for (int i = 0; i < N; ++i) {
                if (hvals[i] != i + 7 || hids[i] < 0 || hids[i] >= int(all.sm.smCount)) {
                    std::fprintf(stderr, "bad result at %d: value=%d sm=%d\n", i, hvals[i], hids[i]);
                    goto cleanup;
                }
                (which ? green_ids : normal_ids).insert(hids[i]);
            }
        }
    }
    std::printf("ordinary unique SM IDs (%zu):", normal_ids.size());
    for (int id : normal_ids) std::printf(" %d", id);
    std::printf("\nGreen unique SM IDs (%zu):", green_ids.size());
    for (int id : green_ids) std::printf(" %d", id);
    std::printf("\n");
    if (green_ids.empty() || green_ids.size() > 8) {
        std::fprintf(stderr, "Green observed SM set exceeds quota or is empty\n"); goto cleanup;
    }
    // The ordinary stream may use a subset under light load; this alone does
    // not identify the exact allowed SM set. Preserve both sets for review.
    rc = 0;
cleanup:
    if (done && !check(cudaEventDestroy(done), "destroy event")) rc = 1;
    if (ids && !check(cudaFree(ids), "free ids")) rc = 1;
    if (vals && !check(cudaFree(vals), "free values")) rc = 1;
    if (ordinary && !check(cudaStreamDestroy(ordinary), "destroy ordinary stream")) rc = 1;
    if (green && !check(cudaStreamDestroy(green), "destroy Green stream")) rc = 1;
    if (ctx && !check(cudaExecutionCtxDestroy(ctx), "destroy Green Context")) rc = 1;
    return rc;
}
