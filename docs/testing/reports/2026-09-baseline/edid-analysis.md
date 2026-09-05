# EDID analysis: capture-card EDID as seen by rpiz-3

Source file: `tests/hdmi-suite/evidence/capture-card-edid-as-seen-by-rpiz-3.bin` (256 bytes,
captured downstream of the NeTV2 passthrough — i.e. this is the MS2109 capture card's own
EDID, forwarded unmodified by the NeTV2 to `rpiz-3` on input0).

Parsed with `scripts/parse_edid.py`:

```
tests/hdmi-suite/evidence/capture-card-edid-as-seen-by-rpiz-3.bin: 256 bytes, 2 blocks
CTA block 0: basic_audio=True
  audio: {'format': 'LPCM', 'channels': 2, 'rates_khz': [32, 44.1, 48], 'byte2': 7}
```

## Interpretation

The 256-byte EDID is a base block plus one CTA-861 extension block. That extension block sets
the basic-audio flag (byte 3, bit 6) and carries one Audio Data Block advertising LPCM, 2
channels, at 32/44.1/48 kHz (byte2 = 0x07, i.e. bit depths 16/20/24-bit all supported — the
descriptor bytes match the fixture built into `tests/unit/test_parse_edid.py`).

This is the EDID the MS2109 capture card presents, and — because the NeTV2 passes EDID through
from the sink to the source untouched — it is also the EDID that `rpiz-3`'s HDMI output
(vc4/vc4-hdmi) reads. **The sink advertises basic audio and a valid LPCM descriptor**, so
`rpiz-3`'s driver has everything it needs to decide the sink is audio-capable and to attempt to
create an HDMI audio stream (ALSA card, ELD populated with `sad_count >= 1`).

Given that, **EDID content does not explain the T23 silence.** The sink-side EDID is not the
leading suspect. Phase 7a should instead look at:

- **Does `rpiz-3` actually see/use this ELD and play audio?** (`/proc/asound/card*/eld*`,
  `sad_count`, `eld_valid`, `monitor_present`, and whether a PCM substream is open/running —
  see `docs/testing/reports/2026-09-baseline/t4d.txt`, section `=== rpiz-3 /proc/asound`.)
- **Do HDMI data islands (which carry audio samples via TERC4-coded packets) actually arrive at
  the NeTV2's input0, and does the firmware/gateware forward them out through output0 to the
  capture card?** This is what `debug t4d`'s five BCH capture words on input0 test — see the
  same report, section `=== notes`.

If instead the EDID had NOT advertised basic audio (no CTA extension block, or the flag clear),
that would have been the leading explanation for T23 silence, since a source can be expected not
to emit audio to a sink that never claimed to support it. That is **not** the case here.
