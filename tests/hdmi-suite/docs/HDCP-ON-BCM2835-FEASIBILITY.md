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

## Key material — what a source needs, and what test keys exist

Primary sources read directly: **HDCP 1.4 specification (Rev 1.4, 8 July 2009, Digital Content
Protection LLC)** and **Crosby, Goldberg, Johnson, Song, Wagner, "A Cryptanalysis of the
High-bandwidth Digital Content Protection System," ACM-CCS8 DRM Workshop 2001.**

### What an HDCP 1.4 transmitter holds
A **Device Key Set** = a **40-bit KSV** (Key Selection Vector) + **40 secret 56-bit Device
Private Keys** (spec §1.2, §2.1). Authentication (§2.2.1): TX sends `Aksv` + a 64-bit random
`An`; RX returns `Bksv`; each side computes the shared secret `Km` by **summing the 40-of-its-own
keys selected by the *other* side's KSV bits** (mod 2^56); the block cipher then derives
`Ks, M0, R0`; the link is authentic iff `R0 == R0'` (read back within 100 ms). The KSV **must
have exactly 20 ones and 20 zeros** — the receiver rejects any other (§2.2.1); this balance is
what makes the linear summation scheme work. Link integrity `Ri` is re-checked every ~2 s /
128th frame (§2.2.3).

### Three sources of key material, and whether a real sink accepts them
1. **Spec Appendix A facsimile keys (p.58+).** The spec prints four test devices (Transmitter
   A1/A2, Receiver B1/B2) each with a KSV + 40 keys, plus full cipher test vectors (e.g. the
   worked `Km = 5309c7d22fcecc`). Purpose: let an implementer **self-test the cipher/summation
   logic** without holding real secret keys. **Caveat (decisive):** these KSVs are
   *non-production* — chosen only so the four facsimile devices interoperate *with each other*.
   A source loaded with facsimile TX keys computes a `Km` that does **not** match a real
   production sink's `Km'` → `R0 != R0'` → **authentication fails against real hardware.** Good
   for validating your cipher; useless for making a real NeTV2 lock.
2. **Master-key-derived keys.** In September 2010 the genuine HDCP **master key** (a 40×40
   matrix of 56-bit values — the authority's keygen secret) was published; **Intel confirmed it
   authentic** (spokesman Tom Waldrop, via Engadget: *"It does appear to be a master key… You
   can derive keys for devices from this published material that do work"*). From it, anyone can
   run the authority's keygen to mint a **valid `(KSV, 40 keys)` for any balanced KSV**, and
   because the scheme is deterministic/linear those keys are indistinguishable from factory
   keys — **a compliant sink computes a matching `Km'` and *will* authenticate.** This exact
   outcome was predicted by Crosby et al. (2001): *"after recovering the private keys of 40
   devices… an attacker can… forge new device keys as though he were the trusted center…
   bypass any revocation list."* (HDCP is essentially Blom's scheme, broken by a conspiracy
   attack.) **This document does not reproduce the master-key values or provide keygen code**;
   its existence and implications are cited as public record.
3. **Real licensed keys** (from DCP LLC under the Adopter Agreement, fused in OTP): what a
   commercial product ships. Not available to this project and not the point.

For the researcher's goal — making a **real NeTV2 sink** authenticate a Pi source — only option
2 yields keys a real sink accepts. Option 1 only proves the cipher math.

### Revocation / SRM
The **SRM** (System Renewability Message) is a DCP-DSA-signed list of revoked **sink** KSVs that
a transmitter checks before outputting (spec §5; DRM's `drm_hdcp_check_ksvs_revoked()` parses
`display_hdcp_srm.bin`). It is unforgeable but targets the **sink** direction — the source's own
KSV is generally not what's checked when driving a sink. For a two-device bench you control, a
**freshly generated balanced KSV** (not a known-published value, and specifically **not** the
published Appendix A facsimile KSVs, which are the obvious blacklist candidates) is essentially
never pre-listed. Felten's summary: the leak *"renders the key revocation feature impotent"*
because testers can mint unlimited fresh unrevoked KSVs.

### Legal framing (factual, not legal advice)
DMCA §1201 targets *circumventing access controls to reach protected copyrighted works* (e.g.
stripping HDCP off a commercial stream). *Producing* HDCP as a compliant **source** to exercise
the HDCP-**input** path of hardware you own, driving only your own test patterns with no
protected commercial content, is a different activity — generating protection, not defeating it.
Intel signalled it would invoke the DMCA against uses of the leaked key (Techdirt, 2010-09-20),
and the HDCP Adopter Agreement / robustness rules and any key-material licensing are separate
considerations. For real legal exposure, consult qualified counsel.

## Silicon — the BCM2835 HDMI/HDCP block (source archaeology)

**The HDMI TX is Broadcom-native VideoCore IP, not Synopsys DesignWare.** The mainline `vc4`
driver drives BCM2835/2711/2712 with Broadcom-named registers; there is no `dw-hdmi` bridge in
the path (this corrects an earlier working assumption that Pi 4 / BCM2711 used DesignWare — it
does not; it is the `vc4` "VC5" variant). DT (`raspberrypi/linux` `bcm2835-common.dtsi`):
```
hdmi: hdmi@7e902000 {
    compatible = "brcm,bcm2835-hdmi";
    reg = <0x7e902000 0x600>,   // HDMI core   (Linux maps only 0x600)
          <0x7e808000 0x100>;   // HD / "hdmi mailbox" block
    clocks = <&clocks BCM2835_PLLH_PIX>, <&clocks BCM2835_CLOCK_HSM>;
    clock-names = "pixel", "hdmi";
};
```

**A separate, unmapped "hdcp" block exists.** Herman Hermitage's reverse-engineered VideoCore
MMIO map lists, at the bus level:
- `0x7E808000` — **hdmi mailbox** (mapped by vc4 as the "HD" block)
- `0x7E809000` — **hdcp mailbox** ← *not* in the DT `reg` list; **Linux never maps it**
- `0x7E902000` — HDMI core (mapped, 0x600)

So the HDCP engine most likely lives at ~`0x7E809000`, in a window the Linux/vc4 stack never
touches. The map gives only the block *label* — **no register offsets, no key-RAM layout**.
(Source: hermanhermitage/videocoreiv wiki, MMIO register map.)

**The register-level HDCP layout is not public.** The "BCM2835 ARM Peripherals" datasheet
explicitly omits HDMI — §1.1: *"There are a number of peripherals … intended to be controlled
by the GPU. These are omitted from this datasheet. Accessing these peripherals from the ARM is
not recommended."* HDMI is a GPU-controlled peripheral. The comparable open Broadcom trees
(STB `stblinux` bcm7xxx, mobile Capri/Hawaii BSPs) do **not** expose this IP's HDCP registers —
Broadcom STB HDCP lives in the closed **Nexus/Magnum** stack (`BCHP_HDMI_*`/`BHDM_HDCP_*`
defines, not open source). No public register dump of the VideoCore HDCP engine (offsets, key
RAM, An/Aksv/Bksv/Ri, cipher-enable) was found.

## Firmware/VPU — the actual (and only public) key path

**The BCM2835 HDCP cipher is real and has a software key-download interface — through the VPU
firmware, not the ARM.** Broadcom's *public* userland exposes it. Verified verbatim from
`raspberrypi/userland` master:

`interface/vmcs_host/vc_hdmi.h`:
```c
typedef enum { HDMI_CP_NONE = 0, HDMI_CP_HDCP = 1 } HDMI_CP_MODE_T;   // HDCP 1.x
#define HDCP_KEY_BLOCK_SIZE 328   /* KSV, padding, device keys and hash. */
#define HDCP_KSV_LENGTH     5
#define HDCP_MAX_DEVICE     127
#define HDCP_MAX_DEPTH      7
// VC_HDMI_NOTIFY_T status flags:
VC_HDMI_HDCP_UNAUTH       = (1<<4),  // auth broken (e.g. Ri mismatch) / not active
VC_HDMI_HDCP_AUTH         = (1<<5),  // HDCP active
VC_HDMI_HDCP_KEY_DOWNLOAD = (1<<6),  // key download ok/fail
VC_HDMI_HDCP_SRM_DOWNLOAD = (1<<7),  // revocation-list download ok/fail
```
`interface/vmcs_host/vc_vchi_tvservice.c`:
```c
int vc_tv_hdmi_set_hdcp_key_id(uint32_t display_id, const uint8_t *key) {
   TV_HDCP_SET_KEY_PARAM_T param;
   memcpy(param.key, key, HDCP_KEY_BLOCK_SIZE);          // 328 bytes = KSV + 40 keys + hash
   return tvservice_send_command(VC_TV_HDCP_SET_KEY, display_id, &param, sizeof(param), 0);
}
int vc_tv_hdmi_set_hdcp_revoked_list_id(uint32_t display_id, const uint8_t *list, uint32_t num_keys){
   TV_HDCP_SET_SRM_PARAM_T param = {VC_HTOV32(num_keys)};
   int r = tvservice_send_command(VC_TV_HDCP_SET_SRM, display_id, &param, sizeof(param), 0);
   if (r==0 && num_keys && list) r = vchi_bulk_queue_transmit(..., list, num_keys*HDCP_KSV_LENGTH, ...);
   return r;
}
```

**What this means:**
- Keys *can* be supplied from software — as a **328-byte block** (KSV + 40 device keys + hash),
  handed to the **VPU firmware** via the `tvservice` VCHI command `VC_TV_HDCP_SET_KEY`. The VPU,
  not the ARM, writes them into the HDCP engine's key RAM. There is **no ARM MMIO register write
  in any public source** that loads HDCP keys directly.
- Note the 328-byte block already includes a **hash** — the firmware likely validates the key
  block's integrity (and may additionally gate on an OTP "HDCP enabled" fuse). RPi engineers
  state the key is "normally programmed into the OTP" and that production Pi firmware ships with
  **HDCP disabled and no valid key**.

### Firmware-as-gatekeeper (your hypothesis — assessed)
- **Documented HDMI registers:** ARM/vc4 has *direct* MMIO (ioremap + `HDMI_READ/WRITE`, no
  mailbox) for the mapped 0x600 core + 0x100 HD windows. For those, the ARM is bus master.
- **HSM clock:** `BCM2835_CLOCK_HSM` comes from the ARM-side clock manager (`clk-bcm2835`), so
  the ARM *can* enable/set it without firmware — CONFIRMED from the DT `clocks` property.
- **HDCP engine:** *not* in the mapped windows (it's the unmapped ~`0x7E809000` block), and the
  only public control path is the VPU-mediated VCHI command. So HDCP specifically **is
  firmware-gated in practice.**
- **OTP/secure key path:** likely VPU-only. rpi-open-firmware documents OTP codec-licence keys
  but **no** HDCP key region; no public source shows the ARM writing HDCP key RAM. The
  `set_hdcp_key_id` design (ARM ships bytes → VPU loads engine) is consistent with the VPU owning
  the key path.
- **Would firmware modification be required?** Two-sided:
  - *Maybe not a rewrite:* the closed firmware **already contains** HDCP 1.x (`VC_TV_HDCP_SET_KEY`,
    auth, SRM, Ri), and the HSM clock + core regs are ARM-reachable. In principle the stock
    firmware could drive HDCP if fed valid keys.
  - *But firmware involvement is unavoidable:* a *pure ARM/vc4 driver patch* has **no documented
    HDCP registers to program** (the ~0x7E809000 block is undocumented and unmapped) — so the
    realistic path runs **through the VPU firmware**. Whether stock firmware will accept an
    externally-supplied key without an OTP enable is **UNKNOWN/untested**. If it refuses, you'd
    need to patch/replace `start.elf` to ungate it (precedent exists: the H.264/MPEG-2
    codec-licence `start.elf` path), but **no HDCP-enable firmware patch is known publicly.**

## Silicon (corrected) — the HDCP registers ARE in ARM-mapped space

**This supersedes the earlier "engine at unmapped 0x7E809000, VPU-only" reading.** Two
independent sources give the *same* HDCP register interface, and the vc4 source confirms the
offsets are free — so the HDCP cipher registers are directly ARM-reachable, inside the 0x600
window vc4 already maps but never programs.

**Source A — GPL Broadcom STB header** `bchp_hdmi.h` (BCM7340, `jameshilliard/stblinux-2.6.18-7.1`),
base `0x001a0800`. **Source B — reverse-engineered BCM2835 map** (paulwratt
`rpi-internal-registers-online/Region_HDMI.html`), core base `0x7e902000`. They match
offset-for-offset:

| Register | STB (BCM7340) | Pi (BCM2835) | rel. offset |
|---|---|---|---|
| BKSV0 / BKSV1 | 0x1a0810 / 14 | 0x7e902010 / 14 | +0x10 / 14 |
| AN0 / AN1 | 0x1a0818 / 1c | 0x7e902018 / 1c | +0x18 / 1c |
| KSV_FIFO_0 / _1 | 0x1a0830 / 34 | 0x7e902030 / 34 | +0x30 / 34 |
| V (KSV-list SHA) | 0x1a0838 | 0x7e902038 | +0x38 |
| **HDCP_KEY_1** | 0x1a083c | 0x7e90203c | +0x3c |
| **HDCP_KEY_2** | 0x1a0840 | 0x7e902040 | +0x40 |
| **HDCP_CTL** | 0x1a0844 | 0x7e902044 | +0x44 |
| CP_STATUS | 0x1a0848 | 0x7e902048 | +0x48 |
| CP_INTEGRITY | 0x1a084c | 0x7e90204c | +0x4c |
| CP_CONFIG | 0x1a0878* | 0x7e902054* | +0x78 / +0x54 |
| CP_TST | 0x1a087c* | 0x7e902058* | — |

\*The STB has extra `CP_INTEGRITY_CHK_*` registers (0x54–0x74) that the BCM2835 map compresses,
so CP_CONFIG/CP_TST land lower on the Pi. The **key-load registers (KEY_1/KEY_2/CTL/BKSV/AN/
KSV_FIFO) are at identical relative offsets** on both parts — same HDMI-TX IP.

**Register-based key-load field definitions (from the GPL STB header — the prize):**
- `HDCP_KEY_1`: `I_KEY_NUM_5_0` [5:0] = key index 0–39; `I_KEY_23_0` [31:8] = low 24 bits.
- `HDCP_KEY_2`: `I_KEY_55_24` [31:0] = high 32 bits. (Together: one 56-bit device key per index.)
- `CP_CONFIG`: `I_ENABLE_RDB_KEY_LOAD` [10] = **load keys via the register interface ("RDB")
  instead of key RAM/OTP**; `I_KEY_BASE_ADDRESS_9_0` [9:0]; `I_ENABLE_KU_COMPUTATION` [19].
- `HDCP_CTL`: `I_AUTH_REQUEST` [0] = start auth; `I_FORCE_VCALC` [9]; `I_RESET_KU` [16].
- `CP_STATUS`: `HDCP_READY` [31]; `O_AN_READY` [0].
- `KSV_FIFO_0/1`: 40-bit KSV per push (repeater downstream list).
  Note: **no AKSV register** — the transmitter's own AKSV is derived from the loaded 40-key set.

**vc4 confirms the space is free.** The VC4 core variant defines registers at 0x00 (CORE_REV),
0x04 (SW_RESET), 0x08 (HOTPLUG_INT), 0x0c (HOTPLUG), then nothing until 0x5c (FIFO_CTL), 0x90+
(MAI/audio), 0xa0 (RAM_PACKET_CONFIG). It defines **nothing at 0x10–0x58** — the exact HDCP
range. vc4 `ioremap`s the whole 0x600 core window, so **those HDCP registers are already mapped
into kernel space and are directly readable/writable from the ARM** (via a vc4 patch, or from
userspace through `/dev/mem`); vc4 simply never touches them. (The MAI/CSC registers at HD-region
offsets 0x14–0x58 are a *different* physical block at 0x7e808000 and do not conflict.)

### Reconciling the two hardware pictures
- `0x7E809000` "hdcp mailbox" (Herman Hermitage) = the **VPU communication mailbox** — how the
  closed firmware receives the 328-byte key block from `tvservice` (`VC_TV_HDCP_SET_KEY`). It is
  *not* the cipher engine.
- The **cipher engine registers** are the low-offset ones in the HDMI core (0x7e902010–58),
  documented by two independent sources and confirmed unused by vc4.
- Therefore there are **two possible key-load paths**, not one: (1) the firmware path
  (`vc_tv_hdmi_set_hdcp_key_id` → VPU → engine), and (2) a **direct ARM-MMIO path** writing
  `HDCP_KEY_1/2` with `CP_CONFIG.I_ENABLE_RDB_KEY_LOAD` — which does *not* require the VPU to
  load keys. Path (2) is what makes a vc4 driver extension (or a userspace `/dev/mem` prototype)
  realistic.

### What is still UNKNOWN (the honest gap)
- Whether these registers are **live on stock Pi firmware** or gated: the HSM clock is
  ARM-settable (good), but the block may need a power-domain/OTP "HDCP enable" the VPU controls.
  The documented `I_ENABLE_RDB_KEY_LOAD` mode suggests register key-load is a real hardware
  facility (used for bring-up/test), but that it *works without an OTP enable on shipping Pi
  firmware* is **untested**.
- The exact **driver sequence** (order of key-load → Ku enable → auth → BKSV read → An → R0/Ri
  → repeater FIFO → Ri watchdog) is in Broadcom's closed `bhdm_hdcp.c` (Magnum/Nexus). Recovering
  that sequence (from a leaked SDK or by tracing a binary) is the remaining research item.

## DEFINITIVE register map — from Broadcom's own generated headers (rpi-open-firmware)

`rpi-open-firmware` (christinaa/librerpi) ships Broadcom's auto-generated register-database
headers under `broadcom/bcm2708_chip/`. These are the authoritative Broadcom names/offsets and
they **agree exactly** with the GPL STB header (`bchp_hdmi.h`) and the RE'd BCM2835 map
(paulwratt) — three independent sources, byte-for-byte. This settles the silicon question.

### Two cooperating blocks (both ARM-addressable MMIO)

**(1) HDCP key-RAM loader — `hdcp.h`, base `0x7E809000`** (this is the block Herman Hermitage
mislabeled "hdcp mailbox"; it is a *register* key loader, not a VPU mailbox):
```
HDCP_KEY_CTL  0x7e809000  bits: START[0], DONE[1], DISHDCP[2]
HDCP_KEY_ADR  0x7e809004  8-bit  key index/address
HDCP_KEY_KY0  0x7e809008  32-bit key data low
HDCP_KEY_KY1  0x7e80900c  24-bit key data high   -> KY0|KY1 = one 56-bit device key
```
Load procedure implied by the fields: for each key n: `KEY_ADR=n; KY0=lo32; KY1=hi24;
KEY_CTL.START=1; wait KEY_CTL.DONE`. `DISHDCP` disables. **Plaintext 56-bit keys — no OTP, no
AES blob, no VPU mailbox.** Note: this block is **not** in the vc4 device-tree `reg` list, so
Linux never maps it — but it is ordinary MMIO reachable via a new `ioremap`/`/dev/mem`.

**(2) HDCP cipher/authentication engine — `hdmicore.h`, base `0x7E902000`** (inside the 0x600
window vc4 *does* map but never touches):
```
HDMI_BKSV0/1        0x7e902010/14   receiver KSV (20/40 ones)
HDMI_AN0/1          0x7e902018/1c   session An (64-bit)
HDMI_AN_INFLUENCE_1/2 0x20/24 ;  HDMI_TST_AN0/1 0x28/2c
HDMI_KSV_FIFO_0/1   0x7e902030/34   repeater downstream KSV list
HDMI_HDCP_KEY_1/2   0x7e90203c/40   (alt key path: I_KEY_NUM_5_0 + I_KEY_23_0 / I_KEY_55_24)
HDMI_HDCP_CTL       0x7e902044      I_AUTH_REQUEST[0], I_FORCE_VCALC[9], I_RESET_KU[16]
HDMI_CP_STATUS      0x7e902048      O_AN_READY[0], HDCP_READY[31]
HDMI_CP_INTEGRITY(_CFG) 0x4c/50     Ri link-integrity
HDMI_CP_CONFIG      0x7e902054      I_KEY_BASE_ADDRESS_9_0[9:0], I_ENABLE_RDB_KEY_LOAD[10], I_ENABLE_KU_COMPUTATION[19]
HDMI_CP_TST         0x7e902058
```
`CP_CONFIG.I_KEY_BASE_ADDRESS` points into the key RAM loaded by block (1); `I_ENABLE_KU_
COMPUTATION` derives the session key from the loaded set; `HDCP_CTL.I_AUTH_REQUEST` runs
authentication; `CP_STATUS` reports An-ready / HDCP-ready; `CP_INTEGRITY` is the Ri watchdog.

### On-device confirmation (rpiz-3, measured)
- OTP `OTP_HDCP_AES_KEY_ROW` region (rows 37/41/45 and neighbours) read **all `00000000`** via
  `vcgencmd otp_dump` — **no HDCP key material is fused**. This is exactly why the *firmware*
  path (`VC_TV_HDCP_SET_KEY`, which expects an OTP-AES-decryptable encrypted key blob) reports
  "no key". It does **not** block the plaintext register loader (block 1).
- `vcgencmd measure_clock hdmi` = **163.68 MHz HSM clock live**, `display_power=1` — the clock
  the HDCP engine needs is already running; the block is not clock-starved.

### rpi-open-firmware itself
It contains the Broadcom register *headers* (the map above) but does **not** initialize HDMI or
HDCP (README: video bring-up unimplemented; project on indefinite hold). So it is valuable as
the *register reference*, not as a ready firmware that drives HDCP. Its `cprman.cc` /
`BCM2708ClockDomains` / `BCM2708PowerManagement` show how clock/power domains are driven from
open code, which is the template if a power/enable gate turns out to need ungating.

## Driver sequence — how to actually drive these registers

No public copy of Broadcom's own `bhdm_hdcp.c` (the exact Magnum/Nexus sequence) is reachable —
it lives in STB-vendor GPL tarballs, un-indexed. But the generic HDCP-1.x transmitter sequence
is CONFIRMED from two readable GPL drivers — Synopsys `dw_hdmi` (register-level key-load/auth/
encrypt) and Rockchip `rk616_hdcp` (the software workqueue state machine + repeater/retry) — plus
the public HDCP 1.4 spec (Ri every 128 frames). Mapped onto the BCM2835 registers:

1. **Load keys** (block 1): for n=0..39 → `HDCP_KEY_ADR=n; HDCP_KEY_KY0=lo32; HDCP_KEY_KY1=hi24;
   HDCP_KEY_CTL.START=1; poll DONE`. Then `CP_CONFIG.I_ENABLE_KU_COMPUTATION=1`.
2. **Start auth** (block 2): pulse `HDCP_CTL.I_RESET_KU`; HW generates An → poll
   `CP_STATUS.O_AN_READY`; read `AN0/AN1`. Over DDC (I2C 0x74) write Aksv+An to the sink, read
   BKSV(0x00)+BCAPS(0x40); verify BKSV = 20/40 ones (also in `BKSV0/1`). Set
   `HDCP_CTL.I_AUTH_REQUEST` → HW computes Km/Ks/R0 → poll `CP_STATUS.HDCP_READY`; after ≥100 ms
   read sink R0′ (DDC 0x08), compare to HW R0.
3. **Enable encryption** on R0==R0′ (encryption-enable bit in HDCP_CTL/CP_CONFIG).
4. **Ri watchdog**: every 128 frames read sink Ri′ (DDC 0x08) within the 128-pixel-clock window,
   compare to HW Ri (`CP_INTEGRITY`); persistent mismatch → drop encryption + re-auth.
5. **Repeater path** (if BCAPS.REPEATER): read downstream KSV list (DDC 0x43) into
   `KSV_FIFO_0/1`, `HDCP_CTL.I_FORCE_VCALC`, read `V`, compare to sink V′ (DDC 0x20–0x2c).
(The per-key-indexed load via the 0x7E809000 block is the one genuinely BCM-specific step;
everything else mirrors the confirmed GPL drivers.)

## FEASIBILITY VERDICT

**Producing HDCP-encrypted output from the BCM2835 is NOT fundamentally impossible — it is an
unsupported, undocumented-at-the-sequence-level, but register-reachable capability.** The
reflexive "the Pi can't do HDCP" is true only of the *shipping configuration* (no OTP key, vc4
omits HDCP, firmware disables it), not of the silicon.

**What is CONFIRMED (multi-source):**
- The BCM2835 contains a complete HDCP 1.x cipher/auth engine **and** a plaintext key-RAM loader,
  both at known MMIO addresses, documented identically by three independent sources (Broadcom RDB
  headers, GPL STB header, RE map).
- The registers are ARM-addressable; the HSM clock is live; the OTP HDCP slot is empty (measured).
- The generic transmitter driver sequence is known from GPL drivers + the public spec.
- Valid device keys that a real sink will authenticate can be generated because the HDCP master
  key is public (documented as fact; values/keygen not reproduced here).

**What is UNKNOWN / the real remaining risks:**
1. **Power/enable gating.** The HSM clock runs, but a power domain or a security/enable signal for
   the HDCP block may be VPU/OTP-controlled. If so, writes to 0x7E809000 / CP registers may be
   inert until ungated (possibly needing a `start.elf` change). *Untested.*
2. **Exact bit-level auth sequence** and the `AN_INFLUENCE`/`CP_INTEGRITY_CFG`/`CP_TST` semantics
   are not public; some iteration/tracing would be required.
3. **Key material** must be supplied (legal/licensing considerations per the key-material section).
4. vc4 vs firmware ownership: under `vc4-kms-v3d` the ARM owns HDMI (good for a driver/`/dev/mem`
   approach); the firmware `tvservice` path would instead need legacy/fkms graphics.

**Most tractable experiment (no firmware change, no vc4 patch to start):** a userspace `/dev/mem`
prototype that (a) `mmap`s `0x7E809000` and `0x7E902000`, (b) reads `HDCP_KEY_CTL`/`CP_STATUS`/
`CP_CONFIG` to check the block responds (non-garbage reads, DONE handshake behaves), (c) attempts
a key load + `I_AUTH_REQUEST` against the connected sink and watches `CP_STATUS.HDCP_READY` and
the sink's R0′. Step (b) alone answers the decisive gating question cheaply. If the block responds,
promote to a `vc4` HDCP implementation (attach the DRM Content Protection property + the auth/Ri
worker, per the driver-layer section). If the block is inert, escalate to clock/power ungating
(using rpi-open-firmware's cprman/powman as the map) or a `start.elf` patch.

**Effort estimate:** `/dev/mem` probe to answer gating: hours. Working key-load+auth against a
real sink (if ungated): days–weeks (mostly sequence/bit-field iteration + key-set generation).
Productionized vc4 Content-Protection driver: weeks. The single highest-value next step is the
cheap `/dev/mem` gating probe.
