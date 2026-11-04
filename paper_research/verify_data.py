"""Check the downloaded research files against pinned upstream metadata.

Run: python3 paper_research/verify_data.py
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"


def check(path, size, digest, lfs=False):
    # ponytail: checks the pinned download only; refresh metadata for a new release.
    partial = path.with_name(path.name + ".part")
    if path.exists() and partial.exists():
        raise ValueError(f"Both final and partial files exist: {path}")
    actual = path if path.exists() else partial
    if actual.stat().st_size != size:
        raise ValueError(f"Wrong size: {actual}")
    hasher = hashlib.sha256() if lfs else hashlib.sha1()
    if not lfs:
        hasher.update(f"blob {size}\0".encode())
    with actual.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError(f"Checksum mismatch: {actual}")
    if path.suffix == ".json":
        json.loads(actual.read_text(encoding="utf-8"))
    print(f"OK {actual.relative_to(ROOT)}", flush=True)


def main():
    files = json.loads((ROOT / "matraix/source_files.json").read_text())
    count = 0
    for entry in files:
        if entry["type"] != "file" or entry["path"] == ".gitattributes":
            continue
        lfs = entry.get("lfs")
        check(
            ROOT / "matraix/persona_1m" / entry["path"],
            entry["size"],
            lfs["oid"] if lfs else entry["oid"],
            bool(lfs),
        )
        count += 1
    tree = json.loads((ROOT / "posim/source_tree.json").read_text())
    blobs = {entry["path"]: entry for entry in tree["tree"] if entry["type"] == "blob"}
    paths = ["README.md", "README_CN.md", "run_scripts/README.md",
             "posim/data/data_loader.py", "posim/data/preprocessor.py"]
    for scenario in ("tianjiaerhuan", "wudatushuguan", "xibeiyuzhicai"):
        paths.append(f"run_scripts/{scenario}/config.json")
        paths.extend(f"run_scripts/{scenario}/data/{name}.json"
                     for name in ("events", "initial_posts", "relations", "users"))
    for name in paths:
        check(ROOT / "posim" / name, blobs[name]["size"], blobs[name]["sha"])
        count += 1
    print(f"Verified {count} files against pinned upstream metadata.")


if __name__ == "__main__":
    main()
