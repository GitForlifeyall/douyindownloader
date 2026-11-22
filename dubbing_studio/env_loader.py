#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/env_loader.py
============================
Environment loader and platform runtime setup.
- Auto-loads .env from root or package directory.
- Configures Windows UTF-8 stdout/stderr.
- Configures NVIDIA CUDA & cuDNN DLL search paths for ONNX Runtime & PyTorch/Whisper.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Union


def configure_runtime_environment(env_file: Optional[Union[str, Path]] = None) -> None:
    """Load .env file and set up CUDA DLLs and console encodings."""
    # 1. UTF-8 console output for Windows
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 1.5 Ensure project root and tools/ are in sys.path
    project_root = Path(__file__).resolve().parent.parent
    tools_dir = project_root / "tools"
    for d in (project_root, tools_dir):
        d_str = str(d)
        if d_str not in sys.path:
            sys.path.insert(0, d_str)

    # 2. Discover and load .env file
    candidates = [
        Path(env_file) if env_file else None,
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent / "TikTokDownloader" / ".env",
    ]

    for p in candidates:
        if p and p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k:
                        os.environ[k] = v
            break

    # 3. Add CUDA / cuDNN DLLs to Windows search path
    if sys.platform == "win32":
        venv_candidates = [
            Path(sys.prefix) / "Lib" / "site-packages",
            Path(__file__).resolve().parent.parent / "TikTokDownloader" / ".venv" / "Lib" / "site-packages",
        ]
        
        dll_subdirs = [
            "nvidia/cublas/bin",
            "nvidia/cudnn/bin",
            "nvidia/cuda_nvrtc/bin",
            "nvidia/cuda_runtime/bin",
            "nvidia/cufft/bin",
            "nvidia/curand/bin",
            "nvidia/cusparse/bin",
            "nvidia/nvjitlink/bin",
            "onnxruntime/capi",
        ]

        for venv_site in venv_candidates:
            if not venv_site.exists():
                continue
            for sub in dll_subdirs:
                dll_dir = venv_site / sub
                if dll_dir.exists():
                    try:
                        os.add_dll_directory(str(dll_dir))
                    except Exception:
                        pass
                    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")


# Run automatically on module import
configure_runtime_environment()
