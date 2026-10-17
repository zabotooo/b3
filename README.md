# B3 — BuildBrickBlocks

Word-block programming, in the style of the LEGO® SPIKE™ word blocks, for the
[Raspberry Pi Build HAT](https://www.raspberrypi.com/products/build-hat/). Programs run in the browser
and drive the motors and sensors on the Pi through a small daemon (`hatd`).

B3 is a community project and is not affiliated with or endorsed by the LEGO Group.

## Install on a Raspberry Pi

Raspberry Pi OS bookworm with a Build HAT, connected to your network:

    curl -sSL https://raw.githubusercontent.com/zabotooo/b3/main/install/install.sh | sudo bash

The installer prints the address (`http://<hostname>.local`) and a PIN. Open the address on a tablet or
computer in the same network and enter the PIN. Run the same line again to update.
Uninstall with `… | sudo bash -s -- uninstall` (add `--purge` to also remove projects and settings).

Settings are in `/var/lib/b3/config.toml` (PIN, `http_port`, `audio_device`);
restart after a change with `sudo systemctl restart b3`.

## Development

- `hatd/` — Python daemon (aiohttp, `buildhat`); tests: `cd hatd && python -m pytest`.
  Running it with the editor and a simulator: `hatd/docs/dev-editor.md`.
- `editor/` — fork of [scratch-editor](https://github.com/scratchfoundation/scratch-editor); B3 blocks are in
  `editor/packages/scratch-vm/src/extensions/b3/`.
- `install/` — installer, systemd unit, release packaging. `ci/` — end-to-end test script.
- Design: `docs/superpowers/specs/2026-10-14-b3-design.md`.

## License

AGPL-3.0, see `LICENSE`. The editor is based on Scratch by the Scratch Foundation (AGPL-3.0);
"Scratch" is their trademark (see `editor/TRADEMARK`).
