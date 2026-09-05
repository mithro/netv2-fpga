# Producing HDCP-encrypted HDMI output on the BCM2835 (RPi Zero W) — feasibility deep-dive

**Status: research in progress.** Goal: make the Pi Zero W source (`rpiz-3`, BCM2835,
VideoCore IV) emit *HDCP 1.x-encrypted* HDMI so the NeTV2's HDCP-input datapath can be
exercised. Scope is deliberately restricted to the on-board Broadcom video hardware — no
external HDCP transmitter chip, no lab generator. This is interoperability testing of the
researcher's own equipment.

This document separates the problem into the layers that the reflexive "the Pi can't do
HDCP" answer wrongly collapses together:

1. **Silicon** — does the BCM2835 HDMI TX contain an HDCP cipher engine, and is it
   reachable from the ARM?
2. **Keys** — can HDCP device keys be *loaded* into that engine from software rather than
   only read from fused OTP? What key material exists (test vectors, the leaked master key)?
3. **Firmware/VPU** — does the closed VideoCore firmware gate register/clock access or own
   the key path, such that firmware changes would be required?
4. **Driver** — what must be added to `vc4` to drive authentication + the cipher and expose
   the DRM "Content Protection" property?

## Confirmed on-device baseline (measured on rpiz-3)

Device: `rpiz-3`, `Linux 6.18.39+rpt-rpi-v6 ... armv6l` (Raspbian), BCM2835, vc4-kms-v3d.

- The DRM HDMI connector exposes **no "Content Protection" property** (checked previously by
  enumerating connector properties).
- `vc4.ko` (decompressed: 2810 strings; 511 match `drm_/vc4_hdmi/connector`, so the binary
  and the search are sound) contains **zero** strings matching
  `hdcp|content.protection|ksv|aksv|bksv|crypt|cipher`.
- `drm.ko` carries **no** "Content Protection"/"HDCP" strings.
- Kernel config exposes **no** `HDCP`/`CONTENT_PROTECT` options in this build.

Conclusion for the software layer: HDCP is entirely absent from the shipped driver stack —
this is a "not implemented" state, established as the starting point, **not** proof that the
underlying silicon lacks the capability. The silicon/keys/firmware questions are researched
in the sections below.

<!-- Sections to be filled from research threads:
     - Silicon: BCM2835 HDMI TX HDCP engine + register map
     - Keys: master-key leak, test vectors, KSV/SRM
     - Firmware/VPU gating
     - Driver work items (vc4 + drm_hdcp helpers)
     - Overall feasibility verdict + effort estimate + risks
-->

## Silicon — HDMI register mapping observed on rpiz-3

From `/proc/iomem` (the ranges Linux/vc4 actually claimed):

```
20902000-209025ff : 20902000.hdmi hdmi   # HDMI CORE registers, 0x600 bytes
20808000-208080ff : 20902000.hdmi hd     # HDMI "HD" block,     0x100 bytes
```

- ARM-physical `0x20902000` == VideoCore bus `0x7e902000` (the documented HDMI base).
- vc4 maps only **0x600** of HDMI-core space. This is the range the *driver* requested, not
  necessarily the physical extent of the Broadcom HDMI IP. **Open question for the register
  research:** does the HDMI block physically extend beyond `0x209025ff` with an HDCP cipher /
  key-RAM region at higher offsets that Linux simply never maps (and that `/dev/mem` could
  still reach)? No device-tree node advertises `hdcp`.

## Driver layer — what extending vc4 requires (from Linux source)

Sources read directly (Linux master): `include/drm/display/drm_hdcp.h`,
`drivers/gpu/drm/display/drm_hdcp_helper.c`, `drivers/gpu/drm/i915/display/intel_hdcp.c`,
`drivers/gpu/drm/vc4/vc4_hdmi.c`, `include/uapi/drm/drm_mode.h`.

### What DRM core gives you for free (generic)
- The tri-state **"Content Protection"** connector property
  (`drm_connector_attach_content_protection_property()`), enum values
  `UNDESIRED=0 / DESIRED=1 / ENABLED=2`. Userspace may only set UNDESIRED↔DESIRED; **only the
  driver sets ENABLED**, after it authenticates, and must drop ENABLED→DESIRED (never
  →UNDESIRED) on link loss, then retry.
- `drm_hdcp_update_content_protection()` — push state changes + fire a uevent.
- `drm_hdcp_check_ksvs_revoked()` — loads/parses the SRM firmware blob (`display_hdcp_srm.bin`)
  and reports revoked KSVs.
- The spec-fixed **HDCP 1.4 receiver DDC map** as `#define`s (I2C addr 0x3A / write 0x74):
  Bksv `0x00`, Ri' `0x08`, Aksv `0x10`, An `0x18`, V'H `0x20+4h`, Bcaps `0x40`,
  Bstatus `0x41`, KSV-FIFO `0x43`; watchdog period `DRM_HDCP_CHECK_PERIOD_MS = 128*16 = 2048 ms`.

**There is no generic HDCP cipher/auth engine in DRM core.** Every HDMI driver writes its own
authentication sequence, An generation, cipher enable, and Ri watchdog. (i915's
`intel_hdcp_shim` is Intel-internal, not core.)

### The authentication sequence a driver must implement (i915 `intel_hdcp_auth()` model)
1. Generate An (2×`get_random_u32()`), have the TX capture it.
2. Write An+Aksv to the sink over DDC (0x18 / 0x10).
3. Read+validate Bksv (0x00; must be 20-of-40 ones), then `drm_hdcp_check_ksvs_revoked()`.
4. Program Bksv into the TX cipher.
5. Read Bcaps (0x40) bit6 REPEATER; if set, do the KSV-FIFO/V' downstream path.
6. Enable signalling + cipher (`AUTH_AND_ENC`).
7. Wait R0 ready (sink gets ≤100 ms), then compare Ri' (0x08) against TX Ri, retry 2–3×.
8. Confirm encryption status.
9. Re-verify Ri' every ~2048 ms via a re-queued `delayed_work`; mismatch → ENABLED→DESIRED,
   re-auth.

### vc4 today (CONFIRMED absent)
`vc4_hdmi.c` has no `hdcp`, no `content_protection`, no
`drm_connector_attach_content_protection_property`. `vc4_hdmi_connector_init()` attaches only
TV-margin / colorspace / Broadcast-RGB. Same for the `raspberrypi/linux` downstream tree.
**No out-of-tree vc4 HDCP patch/branch/thread exists anywhere** (searched dri-devel,
raspberrypi/linux, web) — this would be greenfield work.

### Work items, split by how hard each is
| # | Item | Generic (helper exists) | Hardware/BCM-specific (the hard part) |
|---|------|--------------------------|----------------------------------------|
| a | **Load 40 device keys + KSV into the HDMI HDCP engine** | — | **BLOCKING.** BCM key-load register path is undocumented, absent from the open driver. |
| b | DDC I2C for Bksv/An/Aksv/Ri'/Bcaps/Bstatus/KSV-FIFO | offsets + revocation from helper | reuse vc4's existing DDC adapter @0x3A; write the transaction code |
| c | An generation + **cipher enable** + Ri-match read | An = random (generic) | **BLOCKING.** Needs BCM HDMI HDCP TX register offsets (An/Aksv write, cipher on, Ri status). |
| d | CP property attach + atomic-state handling + ~2 s Ri watchdog | all helper/`delayed_work` | wire into vc4 connector init + atomic_check; watchdog body reads TX Ri (HW) |
| e | EDID/HDMI-mode gating | have EDID/display_info | gate on engine present + keyed |

So items **b, d, e are routine** (a few hundred lines, copying i915's shape). Items **a and c
are the whole problem**: they need the BCM HDMI HDCP transmitter register interface (key RAM,
cipher control, Ri status) — undocumented in any open Pi source. That is precisely the gap the
comparable-Broadcom-SoC source archaeology (STB/mobile BSPs) aims to close.
