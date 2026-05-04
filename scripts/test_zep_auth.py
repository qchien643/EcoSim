"""
Auth + connectivity smoke test cho Zep Cloud.

Chạy:
    python scripts/test_zep_auth.py

Mục tiêu (read-only, không mutate Zep state):
1. Verify ZEP_API_KEY env set
2. Verify zep-cloud package installed
3. Init AsyncZep client
4. List existing graphs (auth check)
5. Print sample (or "no graphs yet")

Không tạo/xóa graph để tiết kiệm credit + tránh contaminate user account.
"""

import asyncio
import sys
from pathlib import Path

# Add libs/ecosim-common to path khi chạy standalone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs" / "ecosim-common" / "src"))


async def main():
    from ecosim_common.config import EcoSimConfig
    EcoSimConfig.init()  # load .env

    api_key = EcoSimConfig.zep_api_key()
    if not api_key:
        print("[FAIL] ZEP_API_KEY env không set. Set trong .env trước khi test.")
        return 1

    # Don't print key, just first/last chars
    masked = f"{api_key[:6]}***{api_key[-4:]}" if len(api_key) > 10 else "***"
    print(f"[ok] ZEP_API_KEY found: {masked}")

    try:
        from zep_cloud.client import AsyncZep
    except ImportError as e:
        print(f"[FAIL] zep-cloud package missing: {e}")
        print("   Run: pip install zep-cloud")
        return 1
    print("[ok] zep-cloud package importable")

    client = AsyncZep(api_key=api_key)
    print("[ok] AsyncZep client initialized")

    print("\n>> Calling client.graph.list_all(page_size=10)...")
    try:
        result = await client.graph.list_all(page_size=10)
    except Exception as e:
        print(f"[FAIL] list_all failed: {type(e).__name__}: {e}")
        return 1

    # SDK trả object có .graphs field (list)
    graphs = getattr(result, "graphs", None) or []
    total = getattr(result, "total_count", len(graphs))
    print(f"[ok] Auth OK. Existing graphs in account: {total}")

    if graphs:
        print("\nSample graphs (first 5):")
        for g in graphs[:5]:
            gid = getattr(g, "graph_id", "?")
            name = getattr(g, "name", "(no name)")
            desc = getattr(g, "description", "") or ""
            print(f"  - {gid:30s} {name[:30]:30s} {desc[:40]}")
    else:
        print("(No graphs yet - account clean [ok])")

    print("\n[PASS] Zep Cloud auth test. Ready for KG_BUILDER=zep_hybrid.")
    return 0


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
