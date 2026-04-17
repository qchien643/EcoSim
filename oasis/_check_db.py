import sqlite3, os

db = r"e:\code\project\DUT_STARTUP\EcoSim\oasis\data\ecosim_simulation.db"
if not os.path.exists(db):
    print("DB not found")
    exit()

conn = sqlite3.connect(db)
c = conn.cursor()

# 1. Comment distribution by post
print("=== COMMENTS PER POST ===")
c.execute("SELECT post_id, COUNT(*) as cnt FROM comment GROUP BY post_id ORDER BY post_id")
for pid, cnt in c.fetchall():
    print(f"  post_{pid}: {cnt} comments")

# 2. Per-agent comment pattern
print("\n=== COMMENTS BY AGENT -> POST ===")
c.execute("SELECT user_id, post_id FROM comment ORDER BY user_id, post_id")
for uid, pid in c.fetchall():
    print(f"  agent_{uid} -> post_{pid}")

# 3. Total counts
c.execute("SELECT COUNT(*) FROM post")
print(f"\nTotal posts: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM comment")
print(f"Total comments: {c.fetchone()[0]}")

# 4. Check if comment table has correct post_id values
print("\n=== FIRST 5 COMMENTS (full detail) ===")
c.execute("SELECT comment_id, post_id, user_id, substr(content,1,60) FROM comment ORDER BY comment_id LIMIT 5")
cols = ["comment_id", "post_id", "user_id", "content"]
for row in c.fetchall():
    print(f"  {dict(zip(cols, row))}")

conn.close()
