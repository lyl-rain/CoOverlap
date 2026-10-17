"""Approved short Pi0.5 full/staged/decode-only correctness check.

Uses FlashRT's existing capture hooks and buffers without changing its source.
The same explicit BF16 noise buffer is checked before every graph replay.
The acceptance threshold is exact equality for raw BF16 action buffers.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.subgraphs.pi05.context_denoise_groups import enable
from flash_rt.core.utils.actions import unnormalize_actions


CHECKPOINT = Path("/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5")
PROMPT = "pick up the black bowl and place it on the plate"
OUTPUT = Path("/tmp/cooverlap_pi05_fixed_reference.npz")


def compare(label: str, actual: torch.Tensor, expected: torch.Tensor) -> dict:
    a = actual.float().cpu().numpy()
    b = expected.float().cpu().numpy()
    diff = np.abs(a - b)
    relative = diff / np.maximum(np.abs(b), 1e-6)
    result = {
        "name": label,
        "shape": list(a.shape),
        "finite": bool(np.isfinite(a).all()),
        "exact": bool(torch.equal(actual, expected)),
        "max_abs": float(diff.max()),
        "max_rel": float(relative.max()),
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def main() -> None:
    config = json.loads((CHECKPOINT / "config.json").read_text())
    assert config["chunk_size"] == 50 and config["num_inference_steps"] == 10
    assert config["state_cond"] is False

    rng = np.random.RandomState(41)
    observation = {
        "image": rng.randint(0, 255, (224, 224, 3), dtype=np.uint8),
        "wrist_image": rng.randint(0, 255, (224, 224, 3), dtype=np.uint8),
        "state": rng.uniform(-1.0, 1.0, 8).astype(np.float32),
    }
    frontend = Pi05TorchFrontendRtx(
        CHECKPOINT, num_views=2, chunk_size=50, num_steps=10,
        hardware="rtx_sm87", state_prompt_mode="exact")
    enable(frontend, num_groups=2)
    frontend.set_prompt(PROMPT, state=observation["state"])
    frontend.calibrate(observation)
    pipeline = frontend.pipeline
    assert pipeline is not None and pipeline.chunk_size == 50 and pipeline.num_steps == 10
    assert pipeline.use_fp8 is False and pipeline.use_fp8_decoder is False
    assert pipeline._graph is not None and pipeline._decoder_only_graph is not None
    assert pipeline._context_graph is not None and len(pipeline._denoise_group_graphs) == 2

    stream = frontend._graph_torch_stream
    stream_int = stream.cuda_stream
    stream_handle = ctypes.c_void_p(stream_int)
    images = frontend._stack_images(observation)
    assert images.shape == (2, 224, 224, 3) and images.dtype == torch.bfloat16
    gen = torch.Generator(device="cuda")
    gen.manual_seed(41)
    noises = [torch.randn((50, 32), device="cuda", dtype=torch.bfloat16, generator=gen)
              for _ in range(2)]
    for index, noise in enumerate(noises):
        digest = hashlib.sha256(noise.view(torch.uint8).cpu().numpy().tobytes()).hexdigest()
        print(f"noise{index}_bf16_sha256={digest}", flush=True)

    def read_ptr(ptr: int, nbytes: int) -> torch.Tensor:
        out = torch.empty(nbytes, dtype=torch.uint8, device="cuda")
        rc = frontend._cudart.cudaMemcpyAsync(
            ctypes.c_void_p(out.data_ptr()), ctypes.c_void_p(ptr),
            nbytes, 3, stream_int)
        if rc != 0:
            raise RuntimeError(f"cudaMemcpyAsync D2D failed: {rc}")
        stream.synchronize()
        return out.clone()

    def stage(noise: torch.Tensor) -> None:
        with torch.cuda.stream(stream):
            frontend._copy_tensor_to_pipeline_buf_stream(images, pipeline.input_images_buf, stream_int)
            frontend._copy_tensor_to_pipeline_buf_stream(noise, pipeline.input_noise_buf, stream_int)
        stream.synchronize()
        observed = read_ptr(pipeline.input_noise_buf.ptr.value, noise.numel() * noise.element_size())
        wanted = noise.view(torch.uint8).flatten()
        if not torch.equal(observed, wanted):
            raise AssertionError("staged initial noise bytes differ from fixed source")

    def read_action() -> torch.Tensor:
        out = torch.empty((50, 32), dtype=torch.bfloat16, device="cuda")
        rc = frontend._cudart.cudaMemcpyAsync(
            ctypes.c_void_p(out.data_ptr()), pipeline.input_noise_buf.ptr,
            out.numel() * out.element_size(), 3, stream_int)
        if rc != 0:
            raise RuntimeError(f"cudaMemcpyAsync output failed: {rc}")
        stream.synchronize()
        return out.clone()

    def full(noise: torch.Tensor) -> torch.Tensor:
        stage(noise)
        pipeline._graph.replay(stream_handle)
        stream.synchronize()
        return read_action()

    def context_then_groups(noise: torch.Tensor) -> torch.Tensor:
        stage(noise)
        pipeline._context_graph.replay(stream_handle)
        for graph in pipeline._denoise_group_graphs:
            graph.replay(stream_handle)
        stream.synchronize()
        return read_action()

    ref = full(noises[0])
    enc_k_ptr = pipeline._attn_ptrs["enc_K"]
    enc_v_ptr = pipeline._attn_ptrs["enc_V"]
    ref_k_prefix = read_ptr(enc_k_ptr, 512)
    ref_v_prefix = read_ptr(enc_v_ptr, 512)
    print("encoder_K_prefix_nonzero_bytes", int(torch.count_nonzero(ref_k_prefix).item()), flush=True)
    split = context_then_groups(noises[0])
    split_k_prefix = read_ptr(enc_k_ptr, 512)
    split_v_prefix = read_ptr(enc_v_ptr, 512)
    a = compare("A_full_vs_context_2_groups_raw_bf16", split, ref)
    k = compare("A_encoder_K_prefix_512_bytes", split_k_prefix, ref_k_prefix)
    v = compare("A_encoder_V_prefix_512_bytes", split_v_prefix, ref_v_prefix)
    ref_actions = unnormalize_actions(ref.float().cpu().numpy(), frontend.norm_stats)[:, :7]
    split_actions = unnormalize_actions(split.float().cpu().numpy(), frontend.norm_stats)[:, :7]
    action_abs = np.abs(ref_actions - split_actions)
    action_rel = action_abs / np.maximum(np.abs(ref_actions), 1e-6)
    action_exact = bool(np.array_equal(ref_actions, split_actions))
    print(json.dumps({"name": "A_final_actions", "shape": list(ref_actions.shape),
                      "finite": bool(np.isfinite(ref_actions).all() and np.isfinite(split_actions).all()),
                      "exact": action_exact, "max_abs": float(action_abs.max()),
                      "max_rel": float(action_rel.max())}, sort_keys=True), flush=True)
    np.savez_compressed(
        OUTPUT,
        image=observation["image"], wrist_image=observation["wrist_image"],
        state=observation["state"],
        noise0_bf16_bytes=noises[0].view(torch.uint8).cpu().numpy(),
        noise1_bf16_bytes=noises[1].view(torch.uint8).cpu().numpy(),
        reference_raw_bf16_bytes=ref.view(torch.uint8).cpu().numpy(),
        split_raw_bf16_bytes=split.view(torch.uint8).cpu().numpy(),
        reference_actions=ref_actions, split_actions=split_actions,
        prompt=np.array(PROMPT), prompt_tokens=np.array(frontend.current_prompt_len),
        checkpoint_config_sha256=np.array(hashlib.sha256((CHECKPOINT / "config.json").read_bytes()).hexdigest()),
    )
    print("reference_file", str(OUTPUT), "bytes", OUTPUT.stat().st_size, flush=True)
    if not (a["exact"] and k["exact"] and v["exact"] and action_exact):
        raise AssertionError("A exact BF16, encoder K/V, or action equality failed; stopping before B")

    for index, noise in enumerate(noises):
        expected = full(noise)
        stage(noise)
        pipeline._decoder_only_graph.replay(stream_handle)
        stream.synchronize()
        actual = read_action()
        b = compare(f"B_decoder_only_noise{index}_raw_bf16", actual, expected)
        if not b["exact"]:
            raise AssertionError(f"B noise{index} exact equality failed")

    print(json.dumps({
        "status": "PASS", "checkpoint": str(CHECKPOINT),
        "prompt_tokens": frontend.current_prompt_len,
        "chunk_size": pipeline.chunk_size, "denoise_steps": pipeline.num_steps,
        "effective_precision": "BF16", "graph_groups": len(pipeline._denoise_group_graphs),
        "enc_K_ptr": enc_k_ptr, "enc_V_ptr": enc_v_ptr,
        "torch_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "torch_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
