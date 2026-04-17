import sqlite3, os, sys

db = r"e:\code\project\DUT_STARTUP\EcoSim\oasis\data\ecosim_simulation.db"
out_path = r"e:\code\project\DUT_STARTUP\EcoSim\oasis\data\sim_results.txt"

if not os.path.exists(db):
    print("DB not found!")
    exit(1)

conn = sqlite3.connect(db)
c = conn.cursor()

with open(out_path, "w", encoding="utf-8") as f:
    # List tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    f.write("Tables: {}\n".format(tables))
    for t in tables:
        c.execute("SELECT COUNT(*) FROM " + t)
        f.write("  {}: {} rows\n".format(t, c.fetchone()[0]))
    f.write("\n")

    # Show users
    f.write("=== USERS ===\n")
    c.execute("SELECT user_id, user_name, name, bio FROM user")
    for r in c.fetchall():
        bio = (r[3] or "")[:80]
        f.write("  [{}] @{} | {} | {}\n".format(r[0], r[1], r[2], bio))
    f.write("\n")

    # Show posts
    f.write("=== POSTS ===\n")
    c.execute("SELECT post_id, user_id, content, num_likes, num_dislikes FROM post")
    for r in c.fetchall():
        content = (r[2] or "")
        f.write("  Post#{} by user#{} | likes={} dislikes={}\n".format(r[0], r[1], r[3], r[4]))
        f.write("    {}\n\n".format(content))
    f.write("\n")

    # Show comments
    f.write("=== COMMENTS ===\n")
    c.execute("SELECT comment_id, post_id, user_id, content FROM comment")
    for r in c.fetchall():
        content = (r[3] or "")
        f.write("  Comment#{} on Post#{} by user#{}\n".format(r[0], r[1], r[2]))
        f.write("    {}\n\n".format(content))
    f.write("\n")

    # Show traces
    f.write("=== TRACES (last 30) ===\n")
    c.execute("SELECT user_id, action, info, created_at FROM trace ORDER BY created_at DESC LIMIT 30")
    for r in c.fetchall():
        info_str = (r[2] or "")[:120]
        f.write("  [{}] user#{} -> {}: {}\n".format(r[3], r[0], r[1], info_str))

    # Stats
    f.write("\n=== SUMMARY ===\n")
    for t in ["user", "post", "comment", "like", "dislike", "follow", "trace"]:
        try:
            c.execute("SELECT COUNT(*) FROM " + t)
            f.write("  {}: {}\n".format(t, c.fetchone()[0]))
        except:
            pass

conn.close()
print("Results saved to: " + out_path)
