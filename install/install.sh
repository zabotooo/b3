#!/bin/bash
# B3 (BuildBrickBlocks) installer for Raspberry Pi OS bookworm with a Build HAT.
#
#   Install or update:  curl -sSL https://raw.githubusercontent.com/zabotooo/b3/main/install/install.sh | sudo bash
#   Uninstall:          curl -sSL …/install.sh | sudo bash -s -- uninstall [--purge]
#
#   B3_VERSION=0.1.0   install that release instead of the latest
#   B3_ARCHIVE=file    install a local release archive (b3.tar.gz) instead of downloading
#   B3_ROOT=dir        prefix for every system path (tests only)
set -euo pipefail

B3_REPO="zabotooo/b3"
ROOT="${B3_ROOT:-}"
OPT="$ROOT/opt/b3"
DATA="$ROOT/var/lib/b3"
UNIT="$ROOT/etc/systemd/system/b3.service"
SERVICE_USER=b3
REBOOT=0

say() { echo "b3: $*"; }
die() { echo "b3: error: $*" >&2; exit 1; }

need_root() {
    [ -n "$ROOT" ] || [ "$(id -u)" = 0 ] || die "run as root: curl -sSL … | sudo bash"
}

archive_url() {
    if [ -n "${B3_VERSION:-}" ]; then
        echo "https://github.com/$B3_REPO/releases/download/v$B3_VERSION/b3.tar.gz"
    else
        echo "https://github.com/$B3_REPO/releases/latest/download/b3.tar.gz"
    fi
}

setup_uart() {
    # raspi-config: get_serial_hw prints 0 when the UART is on, get_serial_cons 0 when the console is on
    if [ "$(raspi-config nonint get_serial_hw)" != 0 ]; then
        say "enabling the serial port for the Build HAT"
        raspi-config nonint do_serial_hw 0
        REBOOT=1
    fi
    if [ "$(raspi-config nonint get_serial_cons)" = 0 ]; then
        say "disabling the serial console (the Build HAT needs the port)"
        raspi-config nonint do_serial_cons 1
        REBOOT=1
    fi
}

install_packages() {
    say "installing packages"
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-build-hat python3-aiohttp alsa-utils
}

ensure_user() {
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        # dialout: /dev/serial0, gpio: Build HAT reset pin, audio: sound output
        useradd --system --user-group --home-dir /var/lib/b3 --no-create-home \
            --shell /usr/sbin/nologin --groups dialout,gpio,audio "$SERVICE_USER"
    fi
}

fetch_release() {  # $1: empty work dir; leaves the release in $1/b3
    local archive="${B3_ARCHIVE:-}"
    if [ -z "$archive" ]; then
        archive="$1/b3.tar.gz"
        say "downloading $(archive_url)"
        curl -fsSL "$(archive_url)" -o "$archive" || die "download failed: $(archive_url)"
    fi
    tar --no-same-owner -xzf "$archive" -C "$1" || die "not a B3 release archive: $archive"
    [ -f "$1/b3/VERSION" ] || die "not a B3 release archive (no b3/VERSION): $archive"
}

install_files() {  # $1: unpacked release
    mkdir -p "$(dirname "$OPT")" "$(dirname "$UNIT")"
    rm -rf "$OPT.new" "$OPT.old"
    cp -a "$1" "$OPT.new"
    systemctl stop b3 2>/dev/null || true
    if [ -e "$OPT" ]; then
        mv "$OPT" "$OPT.old"
    fi
    mv "$OPT.new" "$OPT"
    rm -rf "$OPT.old"
    cp "$OPT/install/b3.service" "$UNIT"
}

write_config() {
    mkdir -p "$DATA"
    if [ ! -f "$DATA/config.toml" ]; then
        local pin audio=""
        pin=$(printf '%04d' $(( $(od -An -N2 -tu2 /dev/urandom) % 10000 )))
        if aplay -l 2>/dev/null | grep -q '^card [0-9]*: Headphones'; then
            audio='audio_device = "plughw:CARD=Headphones,DEV=0"'
        fi
        cat > "$DATA/config.toml" <<EOF
# B3 settings; restart after a change: sudo systemctl restart b3
pin = "$pin"
data_dir = "/var/lib/b3"
static_dir = "/opt/b3/editor"
http_port = 80
$audio
EOF
        chmod 600 "$DATA/config.toml"
    fi
    chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA"
}

start_service() {
    systemctl daemon-reload
    systemctl enable b3
    systemctl restart b3
}

offer_reboot() {
    say "The serial port settings changed; the Build HAT works after a reboot."
    if [ -z "$ROOT" ] && (exec </dev/tty) 2>/dev/null; then
        local answer=""
        read -r -p "b3: Reboot now? [y/N] " answer </dev/tty || true
        if [ "$answer" = y ] || [ "$answer" = Y ]; then
            reboot
        fi
    fi
    say "Reboot later with: sudo reboot"
}

do_install() {
    need_root
    WORK=$(mktemp -d)  # global: the EXIT trap runs after this function returns
    trap 'rm -rf "$WORK"' EXIT
    fetch_release "$WORK"  # first: a failed download leaves the system as it was
    setup_uart
    install_packages
    ensure_user
    install_files "$WORK/b3"
    write_config
    start_service
    local pin
    pin=$(sed -n 's/^pin = "\(.*\)"$/\1/p' "$DATA/config.toml")
    say "B3 $(cat "$OPT/VERSION") is running."
    say "Open http://$(hostname).local in a browser. PIN: $pin"
    if [ "$REBOOT" = 1 ]; then
        offer_reboot
    fi
}

do_uninstall() {
    need_root
    systemctl disable --now b3 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    rm -rf "$OPT"
    if [ "${1:-}" = --purge ]; then
        rm -rf "$DATA"
        userdel "$SERVICE_USER" 2>/dev/null || true
        say "B3 removed, with its projects and settings."
    else
        say "B3 removed. Projects and settings are kept in /var/lib/b3 (uninstall --purge removes them)."
    fi
}

case "${1:-install}" in
    install) do_install ;;
    uninstall) shift; do_uninstall "$@" ;;
    *) echo "usage: install.sh [install | uninstall [--purge]]" >&2; exit 2 ;;
esac
