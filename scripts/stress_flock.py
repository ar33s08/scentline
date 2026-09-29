"""Concurrency stress: N files x 3 concurrent writer processes each.
Asserts zero lost deposits (walks == 3 on every file)."""

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
PY = os.path.join(HERE, ".venv", "bin", "python")
WORKER = "/tmp/stress_worker.py"

with open(WORKER, "w") as f:
    f.write(
        "import sys, time\n"
        "from scentline import TrailStore, Trail, Step\n"
        "s = TrailStore(sys.argv[1])\n"
        "time.sleep(0.02)\n"
        "s.deposit(Trail(url='https://e.com', dom_sha='d', "
        "steps=[Step('click', '#a')]), now=time.time())\n"
    )

procs = []
for i in range(1, 9):
    path = f"/tmp/stress{i}.trails.jsonl"
    for suffix in ("", ".lock", ".events.log"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    for _ in range(3):
        procs.append(subprocess.Popen([PY, WORKER, path],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE))

fails = 0
for p in procs:
    _, err = p.communicate()
    if p.returncode != 0:
        fails += 1
        print("WORKER FAILED:", err.decode()[:400])

sys.path.insert(0, HERE)
from scentline import TrailStore  # noqa: E402

bad = []
for f in sorted(glob.glob("/tmp/stress*.trails.jsonl")):
    st = TrailStore(f).stat()
    print(f, st)
    if st["walks"] != 3:
        bad.append((f, st))

assert fails == 0, f"{fails} worker processes failed"
assert not bad, f"lost deposits: {bad}"
print("FLOCK STRESS OK: 8 files x 3 concurrent writers = 24 processes, zero losses")
