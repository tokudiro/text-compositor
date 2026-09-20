"""Pythonワーカー（常駐サブプロセス方式）の、起動から最初のPDF生成までの時間とメモリを測る（#166）。

子プロセスが、(1)起動して`import text_compositor.build`を終えた時点で"ready"を、(2)最初の1件のビルドを終えた
時点で"done"を、標準出力へ出す。親が、起動からの経過時間を測る。ワーカーの実際の実装（#167）ではなく、
起動時間の見積もりのための最小のもの。
"""
import os
import statistics
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHILD = r'''
import os, sys, time
sys.path.insert(0, r"%REPO%")
t0 = time.perf_counter()
import text_compositor.build as B
from text_compositor import deps as D, project as P
print("ready", flush=True)
font_dir = D.ensure_fonts()
project = sys.argv[1]
config = os.path.join(project, "text-compositor.config.yaml")
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    P._build_one(os.path.dirname(B.__file__), r"%REPO%", font_dir, config)
print("done", flush=True)
import ctypes
from ctypes import wintypes
class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
k32 = ctypes.windll.kernel32
k32.GetCurrentProcess.restype = wintypes.HANDLE
pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
gpmi = ctypes.windll.psapi.GetProcessMemoryInfo
gpmi.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
gpmi(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
print("mem %d %d" % (pmc.PeakWorkingSetSize, pmc.WorkingSetSize), flush=True)
sys.stdin.readline()  # 親が終了を指示するまで常駐する
'''.replace("%REPO%", REPO)


def make_project(tmp):
    os.makedirs(os.path.join(tmp, "inputs"), exist_ok=True)
    with open(os.path.join(tmp, "text-compositor.config.yaml"), "w", encoding="utf-8") as f:
        f.write("document:\n  title: t\n  cover: template\nchapters:\n  - a.md\n")
    with open(os.path.join(tmp, "inputs", "a.md"), "w", encoding="utf-8") as f:
        f.write("# 見出し\n\n本文の段落。\n\n- 項目\n")


def peak_ws_mb(pid):
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000 | 0x0400, False, pid)  # QUERY_LIMITED_INFORMATION | QUERY_INFORMATION
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    k32.CloseHandle(h)
    return pmc.PeakWorkingSetSize / 1e6, pmc.WorkingSetSize / 1e6


def main(runs=10):
    tmp = tempfile.mkdtemp(prefix="worker-")
    make_project(tmp)
    rows = []
    for i in range(runs):
        t = time.perf_counter()
        p = subprocess.Popen([sys.executable, "-c", CHILD, tmp], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             text=True, encoding="utf-8")
        ready = done = None
        while True:
            line = p.stdout.readline().strip()
            if line == "ready":
                ready = (time.perf_counter() - t) * 1000
            elif line == "done":
                done = (time.perf_counter() - t) * 1000
            elif line.startswith("mem "):
                _, peak_b, cur_b = line.split()
                peak, cur = int(peak_b) / 1e6, int(cur_b) / 1e6
                break
            elif not line and p.poll() is not None:
                break
        p.stdin.write("\n")
        p.stdin.flush()
        p.wait(timeout=10)
        rows.append((ready, done, peak, cur))
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    for name, idx in (("起動→import完了(ready)", 0), ("起動→最初のPDF生成完了(done)", 1), ("ピークのワーキングセット MB", 2), ("最初の生成後の常駐メモリ MB", 3)):
        v = [r[idx] for r in rows]
        print(f"  {name}: 1回目={v[0]:.0f} 2回目以降 mean={statistics.mean(v[1:]):.0f} min={min(v[1:]):.0f} max={max(v[1:]):.0f}")


if __name__ == "__main__":
    main()
