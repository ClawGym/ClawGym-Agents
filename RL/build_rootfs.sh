#!/usr/bin/env bash
# build_rootfs.sh — Prepare the OpenClaw rootfs for chroot-based execution.
#
# Applies all manual customizations that were previously done by hand:
#   1. /dev device nodes
#   2. pip install (remove EXTERNALLY-MANAGED)
#   3. en_US.UTF-8 locale generation
#   4. Static /proc (for tasks needing procfs)
#   5. Additional packages (ruby, php, sudo)
#
# Usage:
#   ./build_rootfs.sh /tmp/openclaw-bundle/rootfs
#
# Requires: root (for mknod), host must have /usr/share/i18n for locale copy.

set -euo pipefail

ROOTFS="${1:?Usage: $0 <rootfs-path>}"

if [ ! -d "$ROOTFS/app" ]; then
    echo "ERROR: $ROOTFS does not look like an OpenClaw rootfs (no /app)" >&2
    exit 1
fi

echo "=== Building rootfs: $ROOTFS ==="

# -----------------------------------------------------------------------
# 1. /dev device nodes
# -----------------------------------------------------------------------
echo "[1/6] Creating /dev device nodes..."
mkdir -p "$ROOTFS/dev"
declare -A DEVNODES=(
    [null]="1 3"
    [zero]="1 5"
    [full]="1 7"
    [random]="1 8"
    [urandom]="1 9"
    [tty]="5 0"
)
for dev in "${!DEVNODES[@]}"; do
    read -r major minor <<< "${DEVNODES[$dev]}"
    if [ ! -c "$ROOTFS/dev/$dev" ]; then
        mknod -m 666 "$ROOTFS/dev/$dev" c "$major" "$minor"
        echo "  created /dev/$dev ($major,$minor)"
    else
        echo "  /dev/$dev already exists"
    fi
done

# -----------------------------------------------------------------------
# 2. pip install + remove EXTERNALLY-MANAGED + fix apt for user namespace
# -----------------------------------------------------------------------
echo "[2/6] Setting up pip and apt..."
# Remove EXTERNALLY-MANAGED if present (blocks pip install outside venv)
find "$ROOTFS/usr/lib" -name "EXTERNALLY-MANAGED" -delete 2>/dev/null || true

# Fix apt to work inside user namespace (unshare --user):
# apt normally drops to _apt user for downloads, which fails in user ns.
echo 'APT::Sandbox::User "root";' > "$ROOTFS/etc/apt/apt.conf.d/99no-sandbox"
# Fix ownership so root can write to apt cache dirs in user ns
chown -R root:root "$ROOTFS/var/cache/apt" "$ROOTFS/var/lib/apt" 2>/dev/null || true
chmod -R 755 "$ROOTFS/var/cache/apt" "$ROOTFS/var/lib/apt" 2>/dev/null || true
rm -rf "$ROOTFS/var/cache/apt/archives/partial/"* "$ROOTFS/var/lib/apt/lists/partial/"* 2>/dev/null || true
# Copy resolv.conf for DNS in chroot
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null || true

if [ ! -f "$ROOTFS/usr/local/bin/pip" ]; then
    echo "  Installing pip via get-pip.py..."
    # Download get-pip.py if not cached
    GET_PIP="/tmp/get-pip.py"
    if [ ! -f "$GET_PIP" ]; then
        curl -sSL https://bootstrap.pypa.io/get-pip.py -o "$GET_PIP"
    fi
    cp "$GET_PIP" "$ROOTFS/tmp/get-pip.py"
    unshare --user --map-root-user -- chroot "$ROOTFS" \
        python3 /tmp/get-pip.py --break-system-packages 2>&1 | tail -3
    rm -f "$ROOTFS/tmp/get-pip.py"
else
    echo "  pip already installed"
fi

# -----------------------------------------------------------------------
# 3. Locale: en_US.UTF-8
# -----------------------------------------------------------------------
echo "[3/6] Setting up en_US.UTF-8 locale..."
# Copy i18n data from host if missing
if [ ! -d "$ROOTFS/usr/share/i18n/locales" ]; then
    echo "  Copying /usr/share/i18n from host..."
    cp -a /usr/share/i18n "$ROOTFS/usr/share/i18n"
fi

# Generate locale
if ! unshare --user --map-root-user -- chroot "$ROOTFS" locale -a 2>/dev/null | grep -q "en_US"; then
    echo "  Generating en_US.UTF-8 locale..."
    mkdir -p "$ROOTFS/usr/lib/locale"
    unshare --user --map-root-user -- chroot "$ROOTFS" \
        localedef -i en_US -f UTF-8 en_US.UTF-8 2>&1 || true
else
    echo "  en_US.UTF-8 locale already exists"
fi

# -----------------------------------------------------------------------
# 4. Static /proc (fake procfs for chroot environments)
# -----------------------------------------------------------------------
echo "[4/6] Setting up static /proc..."
# Remove stale PID directories and old /proc/self (leftover from host /proc snapshot)
find "$ROOTFS/proc" -maxdepth 1 -type d -regex '.*/[0-9]+' -exec rm -rf {} + 2>/dev/null || true
rm -rf "$ROOTFS/proc/self" 2>/dev/null || true

mkdir -p "$ROOTFS/proc/self"

# /proc/cpuinfo — use host's if not present
if [ ! -f "$ROOTFS/proc/cpuinfo" ]; then
    cat /proc/cpuinfo > "$ROOTFS/proc/cpuinfo"
fi

# /proc/meminfo
if [ ! -f "$ROOTFS/proc/meminfo" ]; then
    cat /proc/meminfo > "$ROOTFS/proc/meminfo"
fi

# /proc/version
if [ ! -f "$ROOTFS/proc/version" ]; then
    cat /proc/version > "$ROOTFS/proc/version"
fi

# /proc/stat
if [ ! -f "$ROOTFS/proc/stat" ]; then
    cat /proc/stat > "$ROOTFS/proc/stat"
fi

# /proc/uptime
echo "100000.00 800000.00" > "$ROOTFS/proc/uptime"

# /proc/loadavg
echo "0.50 0.50 0.50 1/200 1000" > "$ROOTFS/proc/loadavg"

# /proc/filesystems
if [ ! -f "$ROOTFS/proc/filesystems" ]; then
    cat /proc/filesystems > "$ROOTFS/proc/filesystems"
fi

# /proc/mounts — minimal set for chroot
cat > "$ROOTFS/proc/mounts" << 'EOF'
rootfs / rootfs rw 0 0
/dev/root / ext4 rw,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev 0 0
devtmpfs /dev devtmpfs rw,nosuid,relatime,size=0k,nr_inodes=0,mode=755 0 0
EOF

# /proc/cmdline
echo "linux" > "$ROOTFS/proc/cmdline"

# /proc/self — basic entries for current process simulation
cat > "$ROOTFS/proc/self/status" << 'EOF'
Name:	bash
Umask:	0022
State:	S (sleeping)
Tgid:	1
Ngid:	0
Pid:	1
PPid:	0
TracerPid:	0
Uid:	0	0	0	0
Gid:	0	0	0	0
FDSize:	256
VmPeak:	    8192 kB
VmSize:	    8192 kB
VmRSS:	     4096 kB
Threads:	1
EOF

echo "0 (bash) S 0 0 0 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 0 8192000 1024 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 0 0 0 0 0 0" > "$ROOTFS/proc/self/stat"
echo "bash" > "$ROOTFS/proc/self/comm"
echo "" > "$ROOTFS/proc/self/cmdline"

# /proc/self/exe — symlink to bash (many tools check this)
ln -sf /bin/bash "$ROOTFS/proc/self/exe" 2>/dev/null || true

# /proc/self/cwd
ln -sf /workspace "$ROOTFS/proc/self/cwd" 2>/dev/null || true

# /proc/self/fd — empty dir
mkdir -p "$ROOTFS/proc/self/fd"

# /proc/self/maps — empty (some tools check existence)
touch "$ROOTFS/proc/self/maps"

# /proc/self/environ
echo -n "HOME=/root\0PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\0" > "$ROOTFS/proc/self/environ"

echo "  Static /proc ready (cleaned PID dirs, created essential files)"

# -----------------------------------------------------------------------
# 5. Install additional packages for task coverage
# -----------------------------------------------------------------------
# -----------------------------------------------------------------------
# 5. (Skipped) No pre-installed packages
# -----------------------------------------------------------------------
# We deliberately do NOT pre-install packages like ruby, php, sudo etc.
# Each container should behave identically to Docker: a clean environment
# where the agent installs what it needs at runtime.
echo "[5/6] Skipping package pre-install (agents install at runtime)..."

# -----------------------------------------------------------------------
# 6. Permissions fixup
# -----------------------------------------------------------------------
echo "[6/6] Fixing permissions..."
chmod -R a+rX "$ROOTFS/proc" 2>/dev/null || true
chmod 1777 "$ROOTFS/tmp" "$ROOTFS/var/tmp" 2>/dev/null || true

echo ""
echo "=== Rootfs build complete ==="
echo "Summary:"
echo "  /dev nodes: $(ls "$ROOTFS/dev/" | wc -w)"
echo "  pip: $([ -f "$ROOTFS/usr/local/bin/pip" ] && echo 'yes' || echo 'no')"
echo "  locale: $(unshare --user --map-root-user -- chroot "$ROOTFS" locale -a 2>/dev/null | grep -c 'en_US' || echo 0) en_US variants"
echo "  /proc files: $(find "$ROOTFS/proc" -maxdepth 2 -type f | wc -l)"
echo "  ruby: $([ -f "$ROOTFS/usr/bin/ruby" ] && echo 'yes' || echo 'no')"
echo "  php: $([ -f "$ROOTFS/usr/bin/php" ] && echo 'yes' || echo 'no')"
echo "  sudo: $([ -f "$ROOTFS/usr/bin/sudo" ] && echo 'yes' || echo 'no')"
