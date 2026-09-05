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
