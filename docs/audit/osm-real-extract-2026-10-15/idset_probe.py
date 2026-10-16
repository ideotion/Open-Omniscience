import os, sys, osmium
def rss():
    for l in open("/proc/self/status"):
        if l.startswith("VmRSS"): return int(l.split()[1])/1024
for name, span, n in (("ways", 1_350_000_000, 1_500_000), ("nodes", 12_000_000_000, 2_000_000)):
    s = osmium.index.IdSet(); base = rss(); step = span // n
    out = []
    for i in range(n):
        s.set((i + 1) * step)
        if i % (n // 10) == 0: out.append(round(rss() - base))
    out.append(round(rss() - base))
    print(name, "sorted ids spread over", span, "MB added at 0,10..100% of the pass:", out)
