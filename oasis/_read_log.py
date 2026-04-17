"""Extract key markers from simulation log to file."""
import os

log = r"e:\code\project\DUT_STARTUP\EcoSim\data\simulations\sim_e7f2da35\simulation.log"
out = r"e:\code\project\DUT_STARTUP\EcoSim\oasis\_log_analysis.txt"

with open(log, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

with open(out, "w", encoding="utf-8") as o:
    o.write(f"Total lines: {len(lines)}\n\n")
    
    o.write("=== KEY MARKERS ===\n")
    for i, line in enumerate(lines):
        ls = line.strip()
        for kw in ["ROUND", "Phase", "wave", "ERROR", "Traceback", "Posted", 
                    "Generating", "likes", "Index", "Post creation", "====",
                    "comments", "Summary", "env.step", "update rec"]:
            if kw in ls:
                o.write(f"L{i+1}: {ls[:200]}\n")
                break
    
    o.write("\n=== LAST 20 LINES ===\n")
    for line in lines[-20:]:
        o.write(line.rstrip()[:200] + "\n")

print(f"Written to {out}")
