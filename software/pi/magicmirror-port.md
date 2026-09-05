# MagicMirror overlay app — trixie port plan (status)

The 2019 overlay UI was **MagicMirror 2.5.0** (Node/npm), autostarted by
**pm2** under an lightdm-autologin X session, rendering `MMM-json-feed` (on the
`netv2` branch) which polled `http://127.0.0.1:6502/`. That JSON feed came from
the pm2 app `netv2-status` (`netv2-status.js`, node `serialport`), which read
SoC telemetry off `/dev/ttyS0` after sending `json on` to the firmware REPL.

## What this phase delivered

The **programming/update/status tooling** is fully ported:

| 2019 (Raspbian 9) | trixie replacement |
| --- | --- |
| `netv2-status.js` (node serialport + pm2) | `../netv2_status.py` (pyserial + `http.server`) |
| `pm2 resurrect` / `pm2-pi.service` | `../systemd/netv2-status.service` (+ `netv2-status.env`) |
| `http://127.0.0.1:6502/` JSON on `/` | **unchanged** — same endpoint and contract |

Because the endpoint and JSON contract are unchanged, the existing
`MMM-json-feed` config entry (`url: 'http://127.0.0.1:6502/'`,
`updateInterval: 2000`) works against the Python reporter **with no change**.

## What is NOT ported here, and why

The MagicMirror **application itself** (the Node app, its `config.js`, the
`MMM-json-feed` `netv2` branch, the lightdm/X autostart) is **not** ported in
this phase. It is deliberately deferred because it is only useful once the
**overlay gateware** is running: the overlay is what composites the MagicMirror
window onto the pass-through HDMI, and the overlay gateware/firmware is a
separate modernisation track. Porting the UI before that track lands would
produce a window that renders to the Pi's own HDMI but is never composited onto
the video path, and would emit no real telemetry (the `json on` REPL and the
telemetry field set — `readbw`, `writebw`, per-input `ph*/sp*/wer*/charsync`,
`x`, `y`, `pclk`, `temp` — are defined by the overlay firmware).

## Port plan for when the overlay gateware lands

1. **MagicMirror runtime.** Install a current MagicMirror (v2.2x+) via the
   maintained installer or `git clone` + `npm install` on trixie's Node
   (Debian ships Node 20; MagicMirror supports it). Drop the 2018 `~/n`
   Node-version-manager arrangement.
2. **Autostart.** Replace `pm2` with a systemd user (or system) service running
   `npm start` in the MagicMirror directory under the autologin X session —
   parallel to `netv2-status.service`. This removes the pm2 dependency entirely.
3. **`MMM-json-feed`.** Re-evaluate the `netv2` fork against current upstream:
   the fork existed mainly to keep the deprecated singular `url` option and a
   37-line 2-file delta. Prefer plain upstream with `urls: [...]` if it now
   works; otherwise re-apply the small delta. Point it at
   `http://127.0.0.1:6502/` (served by `netv2_status.py`).
4. **`config.js`.** Recreate the 2019 module list (alert, updatenotification,
   clock, MMM-json-feed@top_left, compliments, newsfeed). `MMM-ImagesPhotos`
   and `MMM-Remote-Control` were present but disabled — leave disabled.
5. **Telemetry contract.** Confirm the modern overlay firmware still answers
   `json on` with the >200-char JSON record `netv2_status.py` expects; if the
   firmware changes the schema, the reporter forwards it verbatim (it is
   format-agnostic) but the MMM-json-feed titles/fields may need updating.
6. **Colourspace/console helpers.** The 2019 `set_rgb.sh` / `set_ycrcb.sh` /
   `set_res.sh` / `set_governor.sh` helpers are overlay-firmware- and
   X11-specific; port them alongside the UI, routing any REPL writes through the
   golden-unit guard's `console_command` check.
