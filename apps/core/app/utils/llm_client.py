"""
LLMClient — adapter re-export từ ecosim_common.

Module này giữ để backward-compat với các import hiện tại:
    from app.utils.llm_client import LLMClient

Mã nguồn thật ở `shared/src/ecosim_common/llm_client.py`. Thay đổi
ở đó sẽ tự động phản ánh cho Core + Simulation. Không sửa file này —
chỉ còn là shim.
"""

from ecosim_common.llm_client import LLMClient

__all__ = ["LLMClient"]
