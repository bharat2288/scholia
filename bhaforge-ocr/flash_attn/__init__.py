"""
Compatibility shim for DotsMOCR import-time flash-attn coupling.

The upstream model imports `flash_attn_varlen_func` even when the model is
configured to use PyTorch SDPA instead of flash-attn. This shim keeps module
import working on machines where the real flash-attn package is unavailable.
"""

IS_COMPAT_SHIM = True


def flash_attn_varlen_func(*args, **kwargs):
    raise RuntimeError(
        "flash-attn shim invoked unexpectedly. Install real flash-attn or keep "
        "BHAFORGE_OCR_ATTN_IMPLEMENTATION=sdpa."
    )
