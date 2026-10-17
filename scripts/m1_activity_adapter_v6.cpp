// Narrow observation adapter derived from the installed NVIDIA
// extras/CUPTI/samples/activity_trace_async and common record/buffer helpers.
// No model calls, CUDA synchronization, algorithm choice or Kernel launches.
#include <cupti.h>
#include <cstdlib>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <string>
#include <sstream>
#include <fstream>
#include <mutex>
#include <atomic>
#include <unistd.h>
#include <fcntl.h>
#include <dlfcn.h>
static std::mutex mu;
static std::vector<std::string> records;
static std::vector<CUpti_ActivityKind> enabled;
static std::atomic<size_t> outstanding{0};
static uint64_t dropped=0,invalid=0,parse_errors=0,callback_errors=0,adapter_overflow=0,buffers=0;
static bool attempted=false,stopped=false;
static std::string quote(const char* p){
 std::string s="\""; if(p)for(const unsigned char* q=(const unsigned char*)p;*q;++q){
  if(*q=='"'||*q=='\\'){s+='\\';s+=*q;}else if(*q<32){char b[7];std::snprintf(b,7,"\\u%04x",*q);s+=b;}else s+=*q;
 }return s+'"';
}
static void add(const std::string& s){if(records.size()<300000)records.push_back(s);else ++adapter_overflow;}
static int api(const char* name,CUptiResult rc){
 std::lock_guard<std::mutex> g(mu);std::ostringstream o;o<<"{\"type\":\"collector_API\",\"name\":"<<quote(name)<<",\"rc\":"<<int(rc)<<"}";add(o.str());return int(rc);
}
static void CUPTIAPI requested(uint8_t** b,size_t* size,size_t* maxrec){
 *b=nullptr;*size=8*1024*1024;*maxrec=0;
 if(posix_memalign((void**)b,64,*size)!=0){*size=0;std::lock_guard<std::mutex> g(mu);++callback_errors;}else ++outstanding;
}
static void CUPTIAPI completed(CUcontext context,uint32_t stream,uint8_t* b,size_t size,size_t valid){
 std::lock_guard<std::mutex> guard(mu);++buffers;CUpti_Activity* rec=nullptr;CUptiResult rc;
 while((rc=cuptiActivityGetNextRecord(b,valid,&rec))==CUPTI_SUCCESS){
  std::ostringstream o;
  if(rec->kind==CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL){
   auto* k=(CUpti_ActivityKernel11*)rec;
   o<<"{\"type\":\"kernel\",\"activity_kind\":10,\"pid\":"<<getpid()<<",\"device\":"<<k->deviceId<<",\"context\":"<<k->contextId<<",\"stream\":"<<k->streamId<<",\"correlation\":"<<k->correlationId<<",\"start\":"<<k->start<<",\"end\":"<<k->end<<",\"name\":"<<quote(k->name)<<",\"graph\":"<<k->graphId<<"}";
   if(!k->start||!k->end||k->end<k->start)++invalid;
  }else if(rec->kind==CUPTI_ACTIVITY_KIND_RUNTIME||rec->kind==CUPTI_ACTIVITY_KIND_DRIVER){
   auto* a=(CUpti_ActivityAPI*)rec;const char* name=nullptr;
   auto nr=cuptiGetCallbackName(rec->kind==CUPTI_ACTIVITY_KIND_RUNTIME?CUPTI_CB_DOMAIN_RUNTIME_API:CUPTI_CB_DOMAIN_DRIVER_API,a->cbid,&name);
   o<<"{\"type\":\"api\",\"kind\":"<<int(rec->kind)<<",\"pid\":"<<a->processId<<",\"thread\":"<<a->threadId<<",\"correlation\":"<<a->correlationId<<",\"start\":"<<a->start<<",\"end\":"<<a->end<<",\"return_value\":"<<a->returnValue<<",\"name\":"<<quote(name)<<",\"name_rc\":"<<int(nr)<<"}";
  }else if(rec->kind==CUPTI_ACTIVITY_KIND_MEMCPY){
   auto* m=(CUpti_ActivityMemcpy6*)rec;
   o<<"{\"type\":\"memcpy\",\"pid\":"<<getpid()<<",\"context\":"<<m->contextId<<",\"stream\":"<<m->streamId<<",\"correlation\":"<<m->correlationId<<",\"start\":"<<m->start<<",\"end\":"<<m->end<<",\"bytes\":"<<m->bytes<<"}";
   if(!m->start||!m->end||m->end<m->start)++invalid;
  }else if(rec->kind==CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION){
   auto* e=(CUpti_ActivityExternalCorrelation*)rec;
   o<<"{\"type\":\"external\",\"kind\":"<<int(e->externalKind)<<",\"pid\":"<<getpid()<<",\"correlation\":"<<e->correlationId<<",\"external_id\":"<<e->externalId<<"}";
  }else{o<<"{\"type\":\"other\",\"activity_kind\":"<<int(rec->kind)<<"}";}
  add(o.str());
 }
 if(rc!=CUPTI_ERROR_MAX_LIMIT_REACHED){++parse_errors;add("{\"type\":\"parse_error\",\"rc\":"+std::to_string(int(rc))+"}");}
 size_t n=0;rc=cuptiActivityGetNumDroppedRecords(context,stream,&n);dropped+=n;
 if(rc!=CUPTI_SUCCESS)++callback_errors;
 add("{\"type\":\"buffer_complete\",\"valid_bytes\":"+std::to_string(valid)+",\"dropped\":"+std::to_string(n)+",\"drop_query_rc\":"+std::to_string(int(rc))+"}");
 free(b);--outstanding;
}
extern "C" const char* m1_abi(){
 static std::string s="{\"kernel_record\":\"CUpti_ActivityKernel11\",\"kernel_size\":"+std::to_string(sizeof(CUpti_ActivityKernel11))+",\"api_size\":"+std::to_string(sizeof(CUpti_ActivityAPI))+",\"memcpy_size\":"+std::to_string(sizeof(CUpti_ActivityMemcpy6))+",\"concurrent_kind\":"+std::to_string(int(CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL))+",\"CUPTI_API_VERSION\":"+std::to_string(CUPTI_API_VERSION)+"}";return s.c_str();
}
extern "C" const char* m1_library_path(){Dl_info info{};return dladdr((void*)&cuptiActivityEnable,&info)?info.dli_fname:"UNKNOWN";}
extern "C" int m1_runtime_version(){uint32_t v=0;return cuptiGetVersion(&v)==CUPTI_SUCCESS?int(v):-1;}
extern "C" int m1_start(){
 if(attempted)return 9000;attempted=true;
 if(m1_runtime_version()!=CUPTI_API_VERSION)return 9010;
 int r=api("cuptiActivityRegisterCallbacks",cuptiActivityRegisterCallbacks(requested,completed));if(r)return r;
 for(auto kind:{CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION,CUPTI_ACTIVITY_KIND_RUNTIME,CUPTI_ACTIVITY_KIND_DRIVER,CUPTI_ACTIVITY_KIND_MEMCPY,CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL}){
  r=api("cuptiActivityEnable",cuptiActivityEnable(kind));if(r)return r;enabled.push_back(kind);
 }
 uint32_t version=0;r=api("cuptiGetVersion",cuptiGetVersion(&version));
 {std::lock_guard<std::mutex> g(mu);add("{\"type\":\"start\",\"pid\":"+std::to_string(getpid())+",\"CUPTI_version\":"+std::to_string(version)+"}");}
 return r;
}
extern "C" int m1_push(uint64_t id){return int(cuptiActivityPushExternalCorrelationId(CUPTI_EXTERNAL_CORRELATION_KIND_CUSTOM0,id));}
extern "C" int m1_pop(){uint64_t id=0;return int(cuptiActivityPopExternalCorrelationId(CUPTI_EXTERNAL_CORRELATION_KIND_CUSTOM0,&id));}
extern "C" int m1_stop(const char* path){
 if(stopped)return 9002;stopped=true;int error=0;
 // Caller synchronizes once after all diagnostic work. Flush itself never
 // issues CUDA synchronization. No callbacks write files during measured work.
 for(auto it=enabled.rbegin();it!=enabled.rend();++it){int r=api("cuptiActivityDisable",cuptiActivityDisable(*it));if(r&&!error)error=r;}
 int r=api("cuptiActivityFlushAll",cuptiActivityFlushAll(CUPTI_ACTIVITY_FLAG_FLUSH_FORCED));if(r&&!error)error=r;
 size_t n=0;r=api("cuptiActivityGetNumDroppedRecords_final",cuptiActivityGetNumDroppedRecords(nullptr,0,&n));if(r&&!error)error=r;
 {std::lock_guard<std::mutex> g(mu);dropped+=n;
  std::ofstream f(path,std::ios::out|std::ios::trunc);if(!f)return 9003;
  for(const auto& s:records)f<<s<<'\n';
  f<<"{\"type\":\"summary\",\"dropped\":"<<dropped<<",\"invalid_GPU_timestamps\":"<<invalid<<",\"parse_errors\":"<<parse_errors<<",\"callback_errors\":"<<callback_errors<<",\"adapter_overflow\":"<<adapter_overflow<<",\"buffers\":"<<buffers<<",\"outstanding_CUPTI_owned_buffers\":"<<outstanding.load()<<",\"exported_records\":"<<records.size()<<",\"stop_rc\":"<<error<<"}\n";f.flush();if(!f)return 9004;
 }
 int fd=open(path,O_WRONLY|O_CLOEXEC);if(fd<0)return 9005;r=fsync(fd);close(fd);return error?error:(r?9006:0);
}
