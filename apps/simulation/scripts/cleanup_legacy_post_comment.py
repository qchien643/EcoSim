"""Phase 13 one-shot cleanup — xóa :Post / :Comment / structural edges khỏi
mọi sim graph cũ trong FalkorDB.

Sims trước Phase 13 lưu post/comment/like/follow/vote vào graph (duplicate
với oasis_simulation.db). Phase 13 chuyển KG thành semantic-only — script
này dọn legacy data trong sim graphs đã COMPLETED.

Usage:
    cd apps/simulation && .venv/Scripts/python scripts/cleanup_legacy_post_comment.py [--dry-run]
"""
import os
import sys

from falkordb import FalkorDB


DRY_RUN = "--dry-run" in sys.argv


def main() -> int:
    fdb = FalkorDB(
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", 6379)),
    )
    graphs = fdb.list_graphs()
    sim_graphs = [name for name in graphs if name.startswith("sim_")]
    print(f"Found {len(sim_graphs)} sim graphs to clean (dry_run={DRY_RUN})")

    total_post = 0
    total_comment = 0
    total_followed = 0
    for graph_name in sim_graphs:
        g = fdb.select_graph(graph_name)
        try:
            r_post = g.query("MATCH (n:Post) RETURN count(n)")
            r_comment = g.query("MATCH (n:Comment) RETURN count(n)")
            r_followed = g.query("MATCH ()-[r:FOLLOWED]->() RETURN count(r)")
        except Exception as e:
            print(f"  [{graph_name}] query fail: {e}")
            continue

        n_post = r_post.result_set[0][0] if r_post.result_set else 0
        n_comment = r_comment.result_set[0][0] if r_comment.result_set else 0
        n_followed = r_followed.result_set[0][0] if r_followed.result_set else 0

        total_post += n_post
        total_comment += n_comment
        total_followed += n_followed

        if n_post == 0 and n_comment == 0 and n_followed == 0:
            print(f"  [{graph_name}] already clean")
            continue

        print(f"  [{graph_name}] Post={n_post} Comment={n_comment} FOLLOWED={n_followed}")
        if DRY_RUN:
            continue

        # DETACH DELETE :Post + :Comment xóa luôn edges incident
        # ([:POSTED], [:WROTE], [:COMMENTED_ON], [:LIKED], [:DISLIKED],
        # [:VOTED_*], [:REPOSTED], [:REFERENCES])
        g.query("MATCH (p:Post) DETACH DELETE p")
        g.query("MATCH (c:Comment) DETACH DELETE c")
        # FOLLOWED edges agent→agent (không incident với Post/Comment)
        g.query("MATCH ()-[r:FOLLOWED]->() DELETE r")
        print(f"  [{graph_name}] cleaned")

    print(
        f"\nTotal: -{total_post} Post, -{total_comment} Comment, "
        f"-{total_followed} FOLLOWED edges across {len(sim_graphs)} graphs"
    )
    if DRY_RUN:
        print("(dry-run, no changes applied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
