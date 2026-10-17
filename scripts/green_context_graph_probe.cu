// Day 2E short CUDA 13.2 graph-node resource probe. No model or perf test.
#include <cuda_runtime.h>
#include <cstdio>
#include <set>
#include <vector>

__global__ void graph_probe(int* ids, int* values, int n) {
    int sm;
    asm volatile("mov.u32 %0, %%smid;" : "=r"(sm));
    int i=blockIdx.x*blockDim.x+threadIdx.x;
    if (i<n) { ids[i]=sm; values[i]=i+17; }
}
static bool ck(cudaError_t e,const char* what) {
    std::printf("api=%s code=%d name=%s\n",what,int(e),cudaGetErrorString(e));
    return e==cudaSuccess;
}
int main() {
    constexpr int N=4096, BLOCK=64;
    int status=1;
    cudaDevResource all{},remaining{},bound{};
    cudaDevResourceDesc_t desc=nullptr;
    cudaExecutionContext_t ctx=nullptr;
    cudaStream_t ordinary=nullptr,green=nullptr;
    cudaGraph_t normal_graph=nullptr,green_graph=nullptr;
    cudaGraphExec_t normal_exec=nullptr,green_exec=nullptr;
    cudaEvent_t done=nullptr;
    int *ids=nullptr,*values=nullptr;
    unsigned count=0;
    std::vector<cudaDevResource> groups;
    std::vector<int> hids(N),hvalues(N);
    std::set<int> normal_ids,green_ids;
    if (!ck(cudaSetDevice(0),"set_device")) goto cleanup;
    if (!ck(cudaDeviceGetDevResource(0,&all,cudaDevResourceTypeSm),"query_all_sm")) goto cleanup;
    std::printf("all_sm=%u min=%u align=%u\n",all.sm.smCount,all.sm.minSmPartitionSize,all.sm.smCoscheduledAlignment);
    if (all.sm.smCount!=16 || all.sm.minSmPartitionSize>8 || all.sm.smCoscheduledAlignment==0 ||
        8%all.sm.smCoscheduledAlignment!=0) { std::fprintf(stderr,"unexpected SM resource\n"); goto cleanup; }
    if (!ck(cudaDevSmResourceSplitByCount(nullptr,&count,&all,nullptr,0,8),"query_groups")) goto cleanup;
    if (count<1 || count>16) goto cleanup;
    groups.resize(count);
    if (!ck(cudaDevSmResourceSplitByCount(groups.data(),&count,&all,&remaining,0,8),"split_8_sm")) goto cleanup;
    if (groups[0].sm.smCount!=8) goto cleanup;
    if (!ck(cudaDevResourceGenerateDesc(&desc,&groups[0],1),"generate_desc")) goto cleanup;
    if (!ck(cudaGreenCtxCreate(&ctx,desc,0,0),"create_green_ctx")) goto cleanup;
    if (!ck(cudaStreamCreateWithFlags(&ordinary,cudaStreamNonBlocking),"create_ordinary_stream")) goto cleanup;
    if (!ck(cudaExecutionCtxStreamCreate(&green,ctx,cudaStreamNonBlocking,0),"create_green_stream")) goto cleanup;
    if (!ck(cudaStreamGetDevResource(green,&bound,cudaDevResourceTypeSm),"query_green_stream")) goto cleanup;
    if (bound.sm.smCount!=8) goto cleanup;
    if (!ck(cudaMalloc(reinterpret_cast<void**>(&ids),N*sizeof(int)),"malloc_ids")) goto cleanup;
    if (!ck(cudaMalloc(reinterpret_cast<void**>(&values),N*sizeof(int)),"malloc_values")) goto cleanup;
    if (!ck(cudaEventCreateWithFlags(&done,cudaEventDisableTiming),"create_event")) goto cleanup;

    for (int kind=0;kind<2;++kind) {
        cudaStream_t stream=kind?green:ordinary;
        cudaGraph_t* graph=kind?&green_graph:&normal_graph;
        cudaGraphExec_t* exec=kind?&green_exec:&normal_exec;
        if (!ck(cudaStreamBeginCapture(stream,cudaStreamCaptureModeGlobal),"begin_capture")) goto cleanup;
        graph_probe<<<N/BLOCK,BLOCK,0,stream>>>(ids,values,N);
        if (!ck(cudaGetLastError(),"capture_kernel_launch")) goto cleanup;
        if (!ck(cudaStreamEndCapture(stream,graph),"end_capture")) goto cleanup;
        size_t nodes=0;
        if (!ck(cudaGraphGetNodes(*graph,nullptr,&nodes),"graph_node_count")) goto cleanup;
        std::printf("graph=%s node_count=%zu\n",kind?"green":"ordinary",nodes);
        if (nodes!=1) { std::fprintf(stderr,"unexpected graph node count\n"); goto cleanup; }
        if (!ck(cudaGraphInstantiate(exec,*graph,0),"instantiate_graph")) goto cleanup;
        for (int trial=0;trial<3;++trial) {
            if (!ck(cudaGraphLaunch(*exec,stream),"graph_launch")) goto cleanup;
            if (!ck(cudaEventRecord(done,stream),"event_record")) goto cleanup;
            if (!ck(cudaEventSynchronize(done),"event_sync")) goto cleanup;
            if (!ck(cudaMemcpy(hids.data(),ids,N*sizeof(int),cudaMemcpyDeviceToHost),"copy_ids")) goto cleanup;
            if (!ck(cudaMemcpy(hvalues.data(),values,N*sizeof(int),cudaMemcpyDeviceToHost),"copy_values")) goto cleanup;
            for (int i=0;i<N;++i) {
                if (hvalues[i]!=i+17 || hids[i]<0 || hids[i]>=16) {
                    std::fprintf(stderr,"invalid output kind=%d trial=%d i=%d value=%d sm=%d\n",
                                 kind,trial,i,hvalues[i],hids[i]); goto cleanup;
                }
                (kind?green_ids:normal_ids).insert(hids[i]);
            }
        }
    }
    std::printf("ordinary_graph_sm_ids (%zu):",normal_ids.size());
    for(int id:normal_ids) std::printf(" %d",id);
    std::printf("\ngreen_graph_sm_ids (%zu):",green_ids.size());
    for(int id:green_ids) std::printf(" %d",id);
    std::printf("\n");
    if (green_ids.empty() || green_ids.size()>8 || normal_ids.size()!=16) goto cleanup;
    status=0;
cleanup:
    if (done && !ck(cudaEventDestroy(done),"destroy_event")) status=1;
    if (normal_exec && !ck(cudaGraphExecDestroy(normal_exec),"destroy_normal_exec")) status=1;
    if (green_exec && !ck(cudaGraphExecDestroy(green_exec),"destroy_green_exec")) status=1;
    if (normal_graph && !ck(cudaGraphDestroy(normal_graph),"destroy_normal_graph")) status=1;
    if (green_graph && !ck(cudaGraphDestroy(green_graph),"destroy_green_graph")) status=1;
    if (ids && !ck(cudaFree(ids),"free_ids")) status=1;
    if (values && !ck(cudaFree(values),"free_values")) status=1;
    if (ordinary && !ck(cudaStreamDestroy(ordinary),"destroy_ordinary_stream")) status=1;
    if (green && !ck(cudaStreamDestroy(green),"destroy_green_stream")) status=1;
    if (ctx && !ck(cudaExecutionCtxDestroy(ctx),"destroy_green_context")) status=1;
    std::printf("status=%s\n",status?"FAIL":"PASS");
    return status;
}
