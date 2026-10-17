#include <pybind11/pybind11.h>
#include "gemm_runner.h"
namespace py = pybind11;
PYBIND11_MODULE(flash_rt_gemm_diag, m) {
    py::class_<GemmRunner>(m, "GemmRunner", py::module_local())
        .def(py::init<>())
        .def("resource_info", [](const GemmRunner& r) {
            py::dict d;
            d["workspace_ptr"] = r.workspace_ptr();
            d["workspace_bytes"] = r.workspace_bytes();
            d["handle_ptr"] = r.handle_ptr();
            d["scale_a_ptr"] = r.scale_a_ptr();
            d["scale_b_ptr"] = r.scale_b_ptr();
            return d;
        })
        .def("bf16_nn", [](GemmRunner& r, uintptr_t a, uintptr_t b, uintptr_t d,
                            int M, int N, int K, uintptr_t stream) {
            r.bf16_nn(reinterpret_cast<void*>(a), reinterpret_cast<void*>(b),
                      reinterpret_cast<void*>(d), M, N, K,
                      reinterpret_cast<cudaStream_t>(stream));
        }, py::arg("A"), py::arg("B"), py::arg("D"), py::arg("M"), py::arg("N"),
           py::arg("K"), py::arg("stream")=0)
        .def("autotune_bf16_nn", [](GemmRunner& r, uintptr_t a, uintptr_t b, uintptr_t d,
                                     int M, int N, int K, int num_algos) {
            r.autotune_bf16_nn(reinterpret_cast<void*>(a), reinterpret_cast<void*>(b),
                              reinterpret_cast<void*>(d), M, N, K, num_algos);
        }, py::arg("A"), py::arg("B"), py::arg("D"), py::arg("M"), py::arg("N"),
           py::arg("K"), py::arg("num_algos")=8);
}
