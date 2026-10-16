#!/bin/bash
# Run a command inside a memory-limited cgroup that the command itself sees at the mount root, pinned to two cores:
# the closest a sandbox gets to the 2-core / 3.5 GB reference VM. Needs root, cgroup v1 (memory controller) and
# `unshare -m`; it does not make the CPU as slow as the VM's, so times are THIS machine's.
#   usage: refvm.sh NAME LIMIT_MIB command...      e.g.  refvm.sh refvm 3584 python scripts/osm_reference_run.py ...
# The reader's own check (src/osm/reader.py cgroup_headroom_bytes) reads <mount root>/memory.limit_in_bytes, which in a
# real container is the container's own limit; the bind mount below makes the sandbox answer the same way.
set -e
BASE=/sys/fs/cgroup/memory$(sed -n 's/^[0-9]*:memory:\(.*\)$/\1/p' /proc/self/cgroup)
CG=$BASE/$1
LIM=$2
shift 2
mkdir -p "$CG"
echo $((LIM * 1024 * 1024)) > "$CG/memory.limit_in_bytes"
exec unshare -m bash -c "mount --bind '$CG' /sys/fs/cgroup/memory && echo \$\$ > /sys/fs/cgroup/memory/cgroup.procs && exec taskset -c 0,1 \"\$@\"" _ "$@"
