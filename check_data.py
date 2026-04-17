import sqlite3, os, json, sys
sys.stdout.reconfigure(encoding='utf-8')

sim_dir = "e:\\code\\project\\DUT_STARTUP\\EcoSim\\data\\simulations"
sims = [d for d in os.listdir(sim_dir) if os.path.isdir(os.path.join(sim_dir, d))]
print("Simulations:", sims)

for s in sims:
    db = os.path.join(sim_dir, s, "oasis_simulation.db")
    if not os.path.exists(db):
        continue
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"\n{s}: tables={tables}")
    for t in tables:
        cur.execute(f"SELECT count(*) FROM [{t}]")
        print(f"  {t}: {cur.fetchone()[0]} rows")
    if "user" in tables:
        cur.execute("SELECT user_id, name FROM user LIMIT 3")
        for r in cur.fetchall():
            print(f"  user: id={r[0]} name={r[1]}")
    if "trace" in tables:
        cur.execute("SELECT DISTINCT action FROM trace")
        print(f"  trace actions: {[r[0] for r in cur.fetchall()]}")
        cur.execute("SELECT user_id, action FROM trace WHERE action != 'sign_up' LIMIT 5")
        for r in cur.fetchall():
            print(f"  trace: uid={r[0]} action={r[1]}")
    conn.close()

# FalkorDB
try:
    from falkordb import FalkorDB
    fdb = FalkorDB(host="localhost", port=6379)
    graphs = fdb.list_graphs()
    print(f"\nFalkorDB graphs: {graphs}")
    for gname in graphs[:2]:
        g = fdb.select_graph(gname)
        r = g.query("MATCH (n) RETURN labels(n), n.name, substring(toString(n.summary),0,120) LIMIT 8")
        print(f"\nGraph '{gname}' nodes:")
        for row in r.result_set:
            print(f"  labels={row[0]} name={row[1]} summary={row[2]}")
        # Also try edges
        r2 = g.query("MATCH ()-[r]->() RETURN type(r), r.fact LIMIT 5")
        print(f"  Edges:")
        for row in r2.result_set:
            print(f"  type={row[0]} fact={str(row[1])[:100] if row[1] else ''}")
except Exception as e:
    print(f"FalkorDB: {e}")
