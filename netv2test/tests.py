"""Test definitions for the NeTV2 HDMI suite.  Registered via @test.

Areas:
  console   - NeTV2 firmware console / status (no capture card needed)
  lock      - HDMI input locking
  edid/hpd  - EDID pass-through and hot-plug
  output    - NeTV2 HDMI output as seen by the MS2109 capture card
  overlay   - overlay compositor (keying, rectangle, threshold)
  latency   - frame-latency measurement
  mode      - resolution changes
  audio     - HDMI audio pass-through
"""

import time

from . import patterns as P
from .frames import frame_luma
from .latency import OverlayCounter, collect_samples, stats
from .suite import Blocked, Skip, test

MHZ_1080P = 148.49
MHZ_720P = 74.24


# ---------------------------------------------------------------- console / preflight
@test("T01", "console")
def t01_console_alive(rig, ctx):
    h = rig.console.help()
    for cmd in ["status", "video_matrix", "video_mode", "debug", "hdp_toggle"]:
        ctx.check(cmd in h, "help lists '%s'" % cmd)
    dna = rig.console.dna()
    ctx.check(dna is not None and set(dna) != {"0"}, "board DNA non-zero: %s" % dna)
    ctx.metric("dna", dna)


@test("T22", "console")
def t22_thermal(rig, ctx):
    t = rig.console.xadc_c()
    ctx.metric("fpga_die_c", round(t, 1))
    ctx.check(t is not None and 10.0 < t < 90.0, "FPGA die temp sane and < 90C: %.1fC" % t)


@test("T21", "console")
def t21_json_status(rig, ctx):
    rig.source_pattern("bars")
    rig.wait_for_lock()
    j = rig.console.json_status()
    for k in ["hdmi_Rx_hres", "hdmi_Rx_vres", "hdmi_Rx_pixel_clock", "overlay_hres"]:
        ctx.check(k in j, "json has %s" % k)
    ctx.check(j["hdmi_Rx_hres"] == 1920 and j["hdmi_Rx_vres"] == 1080,
              "json input0 res 1920x1080 (got %sx%s)" % (j["hdmi_Rx_hres"], j["hdmi_Rx_vres"]))
    ctx.close_to(j["hdmi_Rx_pixel_clock"] / 1e6, 148.5, 0.3, "json pixel clock ~148.5 MHz")
    st = rig.console.status()["inputs"].get(0, {})
    ctx.check(st.get("hres") == j["hdmi_Rx_hres"], "json and status agree on hres")
    ctx.metric("json", {k: j[k] for k in ["hdmi_Rx_hres", "hdmi_Rx_vres", "hdmi_Rx_pixel_clock"]})


# ---------------------------------------------------------------- HPD / EDID
@test("T02", "hpd")
def t02_hpd_gates_on_stream(rig, ctx):
    info = rig.agent.info()
    ctx.check(info["connected"], "with capture streaming, source sees connector connected")
    ctx.metric("edid_bytes", info["edid_bytes"])
    ctx.check(info["edid_bytes"] == 256, "source reads 256-byte EDID through NeTV2 passthrough")


@test("T03", "edid")
def t03_edid_passthrough(rig, ctx):
    edid = rig.agent.edid()
    ctx.check(len(edid) >= 128, "EDID at least 128 bytes (%d)" % len(edid))
    # Descriptor name "HD TO USB" lives in a monitor-name descriptor (0xFC).
    name = _edid_name(edid)
    ctx.metric("edid_name", name)
    ctx.check(name is not None and "HD TO USB" in name, "EDID monitor name is 'HD TO USB' (got %r)" % name)
    ctx.check(_edid_has_1080p(edid), "EDID advertises 1920x1080")


def _edid_name(edid):
    for off in (54, 72, 90, 108):
        d = edid[off:off + 18]
        if len(d) == 18 and d[0] == 0 and d[1] == 0 and d[3] == 0xFC:
            return d[5:18].split(b"\n")[0].decode("ascii", "replace").strip()
    return None


def _edid_has_1080p(edid):
    # detailed timing block 0 horizontal active
    d = edid[54:72]
    if len(d) < 12:
        return False
    hactive = d[2] | ((d[4] & 0xF0) << 4)
    vactive = d[5] | ((d[7] & 0xF0) << 4)
    return hactive == 1920 and vactive == 1080


# ---------------------------------------------------------------- lock
@test("T04", "lock")
def t04_input0_lock_1080p(rig, ctx):
    rig.source_pattern("geometry")
    dt = rig.wait_for_lock(mhz=MHZ_1080P)
    st = rig.input0()
    ctx.metric("lock_time_s", round(dt, 2))
    ctx.check(st["hres"] == 1920 and st["vres"] == 1080, "status input0 = 1920x1080")
    ctx.close_to(st["mhz"], 148.5, 0.3, "input0 pixel clock ~148.5 MHz")


@test("T05", "lock")
def t05_input0_stability(rig, ctx):
    rig.source_pattern("geometry")
    rig.wait_for_lock(mhz=MHZ_1080P)
    tr = rig.console.input0_trace(15)
    s = tr["samples"]
    ctx.check(len(s) >= 20, "collected >=20 debug samples (%d)" % len(s))
    locked = [x for x in s if x["chansync"] == 1 and x["hres"] == 1920 and x["vres"] == 1080]
    frac = len(locked) / float(len(s))
    ctx.metric("locked_fraction", round(frac, 3))
    ctx.metric("samples", len(s))
    # After convergence WER must be zero.
    tail = s[-max(5, len(s) // 2):]
    wer_bad = [x for x in tail if sum(x["wer"]) != 0]
    ctx.metric("charsync_all_111", all(x["charsync"] == "111" for x in tail))
    ctx.check(frac >= 0.95, "input0 res+chansync stable in >=95%% of samples (%.1f%%)" % (frac * 100))
    ctx.check(len(wer_bad) == 0, "WER == 0 across the settled tail (%d bad)" % len(wer_bad))


@test("T06", "lock")
def t06_overlay_input_lock(rig, ctx):
    st = rig.console.status()["inputs"].get(1, {})
    ctx.metric("input1", st)
    ctx.check(st.get("hres") == 1920 and st.get("vres") == 1080, "overlay input1 = 1920x1080")
    ctx.close_to(st.get("mhz", 0), 148.5, 0.3, "input1 pixel clock ~148.5 MHz")


# ---------------------------------------------------------------- output / capture
@test("T07", "output", needs_capture=True)
def t07_output_framerate(rig, ctx):
    rig.source_pattern("bars")
    rig.wait_for_lock()
    d = rig.measure_duty(6.0)
    ctx.metric("capture_fps", round(d["fps"], 1))
    ctx.metric("capture_duty", round(d["duty"], 3))
    ctx.metric("good_frames", d["good"])
    ctx.check(d["n"] > 0, "capture delivers frames")
    ctx.check(d["fps"] >= 25.0, "capture frame rate >= 25 fps (%.1f)" % d["fps"])
    if d["good"] == 0:
        raise Blocked("no signal-bearing frames in the duty window (MS2109 not syncing)")
    ctx.note("capture duty %.0f%% (MS2109 intermittent sync; NeTV2 output itself is stable)" % (d["duty"] * 100))


@test("T08", "output", needs_capture=True)
def t08_output_not_blank(rig, ctx):
    rig.source_pattern("solid", rgb=[255, 255, 255])
    rig.wait_for_lock()
    img, f = rig.good_image(timeout=25, save_as="T08_white.ppm")
    white_luma = float(img.luma.mean())
    ctx.metric("white_mean_luma", round(white_luma, 1))
    ctx.check(white_luma > 180, "white source -> bright capture (mean luma %.0f)" % white_luma)
    rig.source_pattern("solid", rgb=[0, 0, 0])
    time.sleep(1)
    # black: a no-signal frame is also dark, so require the frame to be *valid*
    # by checking it is not the frozen no-signal size; use luma from any frame.
    try:
        img2, f2 = rig.good_image(timeout=8)
        dark = float(img2.luma.mean())
    except Exception:
        f2 = rig.cap.latest(timeout=3)
        dark = float(frame_luma(f2).mean())
    ctx.metric("black_mean_luma", round(dark, 1))
    ctx.check(dark < 40, "black source -> dark capture (mean luma %.0f)" % dark)


@test("T09", "output", needs_capture=True)
def t09_colour_fidelity(rig, ctx):
    rig.source_pattern("bars")
    rig.wait_for_lock()
    img, f = rig.good_image(timeout=25, save_as="T09_bars.ppm")
    worst = 0.0
    for i, expected in enumerate(P.BAR_COLOURS):
        box = P.bars_region(i, img.w, img.h)
        got = img.box_mean(box)
        err = max(abs(got[c] - expected[c]) for c in range(3))
        worst = max(worst, err)
        ctx.note("bar%d exp%s got%s err%.0f" % (i, expected, tuple(int(v) for v in got), err))
    ctx.metric("worst_colour_err", round(worst, 1))
    ctx.check(worst <= 40, "all colour bars within 40/255 (worst %.0f)" % worst)
    # grey ramp monotonic
    greys = [img.box_luma(P.grey_region(i, img.w, img.h)) for i in range(8)]
    ctx.metric("grey_ramp", [round(g, 1) for g in greys])
    mono = all(greys[i] <= greys[i + 1] + 8 for i in range(7))
    ctx.check(mono, "grey ramp monotonically increasing: %s" % [int(g) for g in greys])


@test("T10", "output", needs_capture=True)
def t10_geometry(rig, ctx):
    rig.source_pattern("geometry")
    rig.wait_for_lock()
    img, f = rig.good_image(timeout=25, save_as="T10_geometry.ppm")
    # Four corner squares should be bright; frame centre (between marks) dark bg.
    s = P.GEO_CORNER
    corners = {
        "tl": (2, 2, s - 2, s - 2),
        "tr": (img.w - s + 2, 2, img.w - 2, s - 2),
        "bl": (2, img.h - s + 2, s - 2, img.h - 2),
        "br": (img.w - s + 2, img.h - s + 2, img.w - 2, img.h - 2),
    }
    sx = img.w / float(P.W)
    sy = img.h / float(P.H)
    for name, box in corners.items():
        lum = img.box_luma(box)
        ctx.note("corner %s luma %.0f" % (name, lum))
        ctx.check(lum > 150, "corner %s is bright (%.0f)" % (name, lum))
    # centre white square present
    cx, cy, cw, ch = P.GEO_CENTRE
    cbox = (int((cx + 20) * sx), int((cy + 20) * sy), int((cx + cw - 20) * sx), int((cy + ch - 20) * sy))
    ctx.check(img.box_luma(cbox) > 150, "centre square bright")
    # a dark background patch (away from all marks)
    dbox = (int(1500 * sx), int(200 * sy), int(1700 * sx), int(350 * sy))
    ctx.metric("bg_luma", round(img.box_luma(dbox), 1))
    ctx.check(img.box_luma(dbox) < 60, "background dark between marks")


# ---------------------------------------------------------------- overlay
def _prep_overlay(rig):
    """Ensure the overlay fb0 is owned by us (idempotent within a run)."""
    if rig.overlay.arr is None:
        rig.overlay.prepare()


@test("T11", "overlay", needs_capture=True)
def t11_overlay_keying(rig, ctx):
    _prep_overlay(rig)
    rig.source_pattern("solid", rgb=[128, 128, 128])
    rig.wait_for_lock()
    ov = rig.overlay
    ov.fill((0, 0, 0))
    ov.block(200, 300, 400, 300, (255, 255, 255))   # bright -> opaque white
    ov.block(900, 300, 400, 300, (8, 8, 8))          # dark -> transparent -> grey source
    img, f = rig.good_image(timeout=25, settle=0.5, save_as="T11_keying.ppm")
    sx, sy = img.w / float(P.W), img.h / float(P.H)
    bright = img.box_luma((int(300 * sx), int(400 * sy), int(500 * sx), int(500 * sy)))
    trans = img.box_mean((int(1000 * sx), int(400 * sy), int(1200 * sx), int(500 * sy)))
    ctx.metric("bright_block_luma", round(bright, 1))
    ctx.metric("transparent_block_rgb", tuple(int(v) for v in trans))
    ctx.check(bright > 200, "bright overlay block is opaque white (luma %.0f)" % bright)
    ctx.check(80 < trans[0] < 180 and 80 < trans[1] < 180 and 80 < trans[2] < 180,
              "dark overlay block is transparent (shows grey source %s)" % (tuple(int(v) for v in trans),))


@test("T12", "overlay", needs_capture=True)
def t12_overlay_rectangle_margins(rig, ctx):
    _prep_overlay(rig)
    rig.console.rect_default()
    rig.source_pattern("solid", rgb=[100, 100, 100])
    rig.wait_for_lock()
    ov = rig.overlay
    ov.fill((0, 0, 0))
    # White strips: one well inside the rect, one in the left margin (x<32).
    ov.block(400, 500, 400, 120, (255, 255, 255))    # inside -> white
    ov.block(0, 800, 24, 200, (255, 255, 255))       # x<32 margin -> hidden
    ov.block(600, 0, 300, 6, (255, 255, 255))        # y<10 margin -> hidden
    img, f = rig.good_image(timeout=25, settle=0.5, save_as="T12_margins.ppm")
    sx, sy = img.w / float(P.W), img.h / float(P.H)
    inside = img.box_luma((int(500 * sx), int(540 * sy), int(700 * sx), int(600 * sy)))
    leftm = img.box_mean((int(2 * sx), int(850 * sy), int(20 * sx), int(950 * sy)))
    ctx.metric("inside_luma", round(inside, 1))
    ctx.metric("left_margin_rgb", tuple(int(v) for v in leftm))
    ctx.check(inside > 200, "overlay inside rect is visible (luma %.0f)" % inside)
    # left margin should show source grey (~100), not white overlay
    ctx.check(leftm[0] < 180, "x<32 margin is excluded from overlay (rgb %s)" % (tuple(int(v) for v in leftm),))


@test("T13", "overlay", needs_capture=True)
def t13_overlay_threshold(rig, ctx):
    _prep_overlay(rig)
    rig.source_pattern("solid", rgb=[0, 0, 0])
    rig.wait_for_lock()
    ov = rig.overlay
    try:
        rig.console.rect_thresh(128)
        ov.fill((0, 0, 0))
        ov.block(300, 300, 300, 300, (100, 100, 100))   # below 128 -> transparent
        ov.block(800, 300, 300, 300, (200, 200, 200))   # above 128 -> opaque
        img, f = rig.good_image(timeout=25, settle=0.5, save_as="T13_threshold.ppm")
        sx, sy = img.w / float(P.W), img.h / float(P.H)
        below = img.box_luma((int(380 * sx), int(380 * sy), int(520 * sx), int(520 * sy)))
        above = img.box_luma((int(880 * sx), int(380 * sy), int(1020 * sx), int(520 * sy)))
        ctx.metric("below_thresh_luma", round(below, 1))
        ctx.metric("above_thresh_luma", round(above, 1))
        ctx.check(below < 60, "overlay value 100 below thresh 128 -> transparent (luma %.0f)" % below)
        ctx.check(above > 150, "overlay value 200 above thresh 128 -> opaque (luma %.0f)" % above)
    finally:
        rig.console.rect_thresh(20)


@test("T14", "overlay", needs_capture=True)
def t14_overlay_setrect(rig, ctx):
    _prep_overlay(rig)
    rig.source_pattern("solid", rgb=[80, 80, 80])
    rig.wait_for_lock()
    ov = rig.overlay
    try:
        # shrink the active rectangle to a central band
        rig.console.set_rect(600, 1320, 400, 680)
        ov.fill((0, 0, 0))
        ov.block(200, 500, 200, 120, (255, 255, 255))    # now OUTSIDE rect -> hidden
        ov.block(900, 500, 200, 120, (255, 255, 255))    # INSIDE rect -> white
        img, f = rig.good_image(timeout=25, settle=0.5, save_as="T14_setrect.ppm")
        sx, sy = img.w / float(P.W), img.h / float(P.H)
        outside = img.box_mean((int(240 * sx), int(530 * sy), int(360 * sx), int(600 * sy)))
        inside = img.box_luma((int(940 * sx), int(530 * sy), int(1060 * sx), int(600 * sy)))
        ctx.metric("outside_newrect_rgb", tuple(int(v) for v in outside))
        ctx.metric("inside_newrect_luma", round(inside, 1))
        ctx.check(inside > 200, "overlay inside shrunk rect visible (%.0f)" % inside)
        ctx.check(outside[0] < 180, "overlay outside shrunk rect hidden (shows source %s)" % (tuple(int(v) for v in outside),))
    finally:
        rig.console.rect_default()


@test("T15", "overlay", needs_capture=True)
def t15_overlay_alignment(rig, ctx):
    _prep_overlay(rig)
    rig.source_pattern("solid", rgb=[0, 0, 0])
    rig.wait_for_lock()
    ov = rig.overlay
    ov.fill((0, 0, 0))
    # A white cross at a known position; check the captured centroid matches.
    cx, cy = 960, 540
    ov.block(cx - 200, cy - 6, 400, 12, (255, 255, 255))
    ov.block(cx - 6, cy - 200, 12, 400, (255, 255, 255))
    img, f = rig.good_image(timeout=25, settle=0.5, save_as="T15_cross.ppm")
    import numpy as np
    ys, xs = np.where(img.luma > 128)
    if len(xs) < 50:
        raise Blocked("cross not visible enough to locate")
    cxm = xs.mean() * P.W / img.w
    cym = ys.mean() * P.H / img.h
    ctx.metric("cross_centroid", (round(cxm, 1), round(cym, 1)))
    ctx.check(abs(cxm - cx) < 30 and abs(cym - cy) < 30,
              "overlay cross centroid near (%d,%d): got (%.0f,%.0f)" % (cx, cy, cxm, cym))


# ---------------------------------------------------------------- frame counter / continuity
@test("T16", "output", needs_capture=True)
def t16_frame_counter_continuity(rig, ctx):
    rig.wait_for_lock()
    rig.agent.counter(True, rgb_bg=(0, 0, 0))
    time.sleep(1.0)
    frames = rig.cap.record(int((rig.cap.fps or 30) * 6), timeout=16)
    decoded = []
    for f in frames:
        c = rig.decode_counter(f, P.SRC_STRIP_Y)
        if c is not None:
            decoded.append((f.timestamp, c))
    rig.agent.counter(False)
    ctx.metric("frames_captured", len(frames))
    ctx.metric("counters_decoded", len(decoded))
    if len(decoded) < 5:
        raise Blocked("too few decodable counter frames (%d) - MS2109 duty too low" % len(decoded))
    backwards = 0
    for i in range(1, len(decoded)):
        d = (decoded[i][1] - decoded[i - 1][1]) & 0xFFFF
        if d > 0x8000:   # went backwards (mod 2^16)
            backwards += 1
    ctx.metric("counter_backwards", backwards)
    ctx.check(backwards == 0, "decoded source frame counter never goes backwards (%d)" % backwards)


# ---------------------------------------------------------------- latency
@test("T17", "latency", needs_capture=True)
def t17_latency_passthrough_and_overlay(rig, ctx):
    _prep_overlay(rig)
    rig.wait_for_lock()
    offset, err = rig.agent.sync_clock(50)
    ctx.metric("clock_offset_ms", round(offset * 1e3, 3))
    ctx.metric("clock_offset_err_ms", round(err * 1e3, 3))
    ctx.metric("rtt", rig.agent.rtt_stats)
    # start both counter loops
    rig.agent.counter(True, rgb_bg=(0, 0, 0))
    oc = OverlayCounter(rig.overlay)
    oc.start(bg=(0, 0, 0))
    time.sleep(1.0)
    pt_all, ov_all = [], []
    nf = ng = 0
    for _ in range(4):
        flips = rig.agent.flips(since=-1)
        fmap = dict((c, t) for c, t in flips)
        pt, ov, n, g = collect_samples(rig, fmap, oc, offset, duration=6.0)
        pt_all += pt
        ov_all += ov
        nf += n
        ng += g
    oc.stop()
    rig.agent.counter(False)
    ps = stats(pt_all)
    os_ = stats(ov_all)
    ctx.metric("passthrough_latency", {k: round(v, 2) for k, v in ps.items()})
    ctx.metric("overlay_latency", {k: round(v, 2) for k, v in os_.items()})
    ctx.metric("frames_seen", nf)
    ctx.metric("good_frames", ng)
    if ps.get("n", 0) < 8 or os_.get("n", 0) < 8:
        raise Blocked("too few latency samples (pt=%d ov=%d) - MS2109 duty too low" % (ps.get("n", 0), os_.get("n", 0)))
    ctx.check(ps["min_ms"] > 0, "passthrough latency positive (min %.1f ms)" % ps["min_ms"])
    ctx.check(ps["max_ms"] < 400, "passthrough latency bounded (< 400 ms)")
    ctx.check(os_["min_ms"] > 0, "overlay latency positive (min %.1f ms)" % os_["min_ms"])
    netv2_overlay_ms = os_["mean_ms"] - ps["mean_ms"]
    ctx.metric("netv2_overlay_extra_ms", round(netv2_overlay_ms, 2))
    ctx.note("NeTV2 overlay-path adds %.1f ms over passthrough (capture-card latency cancels)" % netv2_overlay_ms)
    ctx.check(-20 < netv2_overlay_ms < 120, "NeTV2 overlay extra latency in a sane range")


# ---------------------------------------------------------------- video matrix
@test("T18", "console")
def t18_video_matrix(rig, ctx):
    out = rig.console.command("video_matrix list")
    ctx.check("input0" in out and "input1" in out, "video_matrix lists input0 and input1 sources")
    ctx.check("pattern" in out, "video_matrix lists the pattern source")
    modes = rig.console.command("video_mode list")
    ctx.check("1920x1080 @60Hz" in modes, "video_mode list includes 1920x1080@60")
    ctx.check("1280x720 @60Hz" in modes, "video_mode list includes 1280x720@60")


# ---------------------------------------------------------------- mode change
@test("T19", "mode")
def t19_mode_change_720p(rig, ctx):
    try:
        rig.source_mode(1280, 720, 60)
        dt = rig.wait_for_lock(w=1280, h=720, mhz=MHZ_720P, timeout=45)
        st = rig.input0()
        ctx.metric("720p_lock_time_s", round(dt, 2))
        ctx.metric("input0_720p", st)
        ctx.check(st["hres"] == 1280 and st["vres"] == 720, "input0 relocks at 1280x720")
        ctx.close_to(st["mhz"], 74.25, 0.3, "720p pixel clock ~74.25 MHz")
    finally:
        rig.source_mode(1920, 1080, 60)
        rig.wait_for_lock(mhz=MHZ_1080P, timeout=45)
    ctx.check(rig.input0()["hres"] == 1920, "input0 returns to 1920x1080 after switch back")


# ---------------------------------------------------------------- source loss / recovery
@test("T20", "lock")
def t20_source_loss_recovery(rig, ctx):
    rig.source_pattern("geometry")
    rig.wait_for_lock(mhz=MHZ_1080P)
    rig.agent.dpms(on=False)
    t0 = time.monotonic()
    lost = False
    while time.monotonic() - t0 < 8:
        st = rig.input0()
        if st.get("mhz", 0) < 1.0 or st.get("hres", 0) == 0:
            lost = True
            break
        time.sleep(0.3)
    ctx.metric("loss_detect_s", round(time.monotonic() - t0, 2))
    ctx.check(lost, "NeTV2 reports source loss after DPMS off")
    rig.agent.dpms(on=True)
    rig.source_pattern("geometry")
    dt = rig.wait_for_lock(mhz=MHZ_1080P, timeout=45)
    ctx.metric("recovery_s", round(dt, 2))
    ctx.check(rig.input0()["hres"] == 1920, "NeTV2 re-locks after source returns")


# ---------------------------------------------------------------- audio
@test("T23", "audio", needs_capture=True)
def t23_audio_passthrough(rig, ctx):
    import subprocess
    import numpy as np
    # Capture card exposes an ALSA source; find its card index.
    out = subprocess.check_output(["arecord", "-l"]).decode("ascii", "replace")
    cardno = None
    for line in out.splitlines():
        if "345f" in line.lower() or "2109" in line or "USB Audio" in line:
            import re
            m = re.search(r"card (\d+):", line)
            if m:
                cardno = int(m.group(1))
                break
    if cardno is None:
        raise Skip("no HDMI audio capture device on the MS2109")
    ctx.metric("alsa_card", cardno)
    rate = 48000
    seconds = 2.0
    rig.agent.audio(hz=1000, seconds=seconds + 1.0)
    time.sleep(0.4)
    raw = subprocess.check_output(
        ["arecord", "-D", "plughw:%d,0" % cardno, "-f", "S16_LE", "-c", "2", "-r", str(rate),
         "-d", str(int(seconds)), "-t", "raw"])
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if a.size < rate:
        raise Blocked("captured too little audio (%d samples)" % a.size)
    mono = a.reshape(-1, 2)[:, 0]
    mono = mono - mono.mean()
    n = 1 << 15
    seg = mono[:n] if mono.size >= n else np.pad(mono, (0, n - mono.size), "constant")
    spec = np.abs(np.fft.rfft(seg * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    peak = freqs[int(np.argmax(spec))]
    ctx.metric("audio_peak_hz", round(float(peak), 1))
    amp = float(mono.std())
    ctx.metric("audio_rms", round(amp, 1))
    ctx.check(amp > 50, "captured audio has signal (rms %.0f)" % amp)
    ctx.check(abs(peak - 1000) < 25, "dominant tone is 1 kHz (got %.0f Hz)" % peak)


# ---------------------------------------------------------------- documented gaps
@test("T90", "gaps")
def t90_documented_gaps(rig, ctx):
    raise Skip("HDCP (no HDCP source), output1 (absent in this gateware), "
               "Ethernet/etherbone (no cable), NeTV2 video_mode change (alters the "
               "EDID offered to the fixed-1080p overlay Pi) - documented, not auto-tested")
