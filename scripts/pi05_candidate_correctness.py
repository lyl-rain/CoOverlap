"""Short, fixed-load Pi0.5 candidate checks. Run only with project approval.

This script never changes FlashRT source or the checkpoint. Its first stage
checks the checkpoint's full 50-action, 10-step workload on the Orin backend.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx


CHECKPOINT = Path("/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5")
PROMPT = "pick up the black bowl and place it on the plate"
SEED = 41


def main() -> None:
    config = json.loads((CHECKPOINT / "config.json").read_text())
    assert config["type"] == "pi05"
    assert config["chunk_size"] == 50
    assert config["num_inference_steps"] == 10
    assert config["state_cond"] is False

    rng = np.random.RandomState(SEED)
    observation = {
        "image": rng.randint(0, 255, (224, 224, 3), dtype=np.uint8),
        "wrist_image": rng.randint(0, 255, (224, 224, 3), dtype=np.uint8),
        "state": rng.uniform(-1.0, 1.0, 8).astype(np.float32),
    }
    frontend = Pi05TorchFrontendRtx(
        CHECKPOINT,
        num_views=2,
        chunk_size=config["chunk_size"],
        num_steps=config["num_inference_steps"],
        hardware="rtx_sm87",
        state_prompt_mode="exact",
    )
    frontend.set_prompt(PROMPT, state=observation["state"])
    frontend.calibrate(observation)
    pipeline = frontend.pipeline
    assert pipeline is not None
    assert frontend.chunk_size == pipeline.chunk_size == 50
    assert pipeline.num_steps == 10
    result = frontend.infer(observation)["actions"]
    assert result.shape == (50, 7), result.shape
    assert np.isfinite(result).all()
    print(json.dumps({
        "status": "PASS",
        "checkpoint": str(CHECKPOINT),
        "hardware": frontend.hardware,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "input_image_shape": list(frontend._stack_images(observation).shape),
        "input_image_dtype": str(frontend._stack_images(observation).dtype),
        "state_shape": list(observation["state"].shape),
        "prompt_tokens": frontend.current_prompt_len,
        "chunk_size": pipeline.chunk_size,
        "denoise_steps": pipeline.num_steps,
        "use_fp8": pipeline.use_fp8,
        "use_fp8_decoder": pipeline.use_fp8_decoder,
        "use_int8_decoder": pipeline.use_int8_decoder,
        "output_shape": list(result.shape),
        "output_finite": bool(np.isfinite(result).all()),
        "output_sample": result[0, :5].tolist(),
        "torch_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "torch_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "proc_vmhwm": next((line.strip() for line in Path("/proc/self/status").read_text().splitlines() if line.startswith("VmHWM:")), None),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
