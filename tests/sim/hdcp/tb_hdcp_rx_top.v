`timescale 1ns/1ps
//////////////////////////////////////////////////////////////////////////////
// FULL HDCP-receiver integration testbench (task H6, spec sections 2-6, 10.2).
//
// Wires the three verified receiver Verilog modules together the way the bridge
// (legacy/netv2mvp_hdcprx.py) does and drives a complete HDCP source-side
// authentication handshake against them with a task-based Verilog I2C *master*
// model on the DDC, checking every result against the Python oracle
// (netv2/hdcp/cipher.py + keys.py) via run_hdcp_rx_top.py:
//
//   hdcp_rx    (eth domain): DDC I2C slave @0x3A + 40x56 sink-key store + Km
//              accumulator; outputs Km_hw / Km_valid_hw / An / Aksv.
//   hdcp_mod_rx(pix domain): the mod-cipher controller, which itself
//              instantiates hdcp_cipher_rx (the H1 cipher patch).  One cipher
//              serves keystream, R0 and Ri (spec section 0 / 5.2), so there is
//              no separate cipher instance here -- cipher_stream and R0/Ri come
//              out of hdcp_mod_rx.
//
// CLOCKING CHOICE (documented per the task): two clocks -- eth 50 MHz (I2C, Km,
// key RAM) and pix_o 148.5 MHz (cipher, R0/Ri, frames) -- crossed with SIMPLE
// synchronisers in the tb (a 3-FF toggle pulse synchroniser for the auth start,
// 2-FF level syncs for Km_valid and for Ri_link/frame_count coming back).  This
// is faithful to how the bridge partitions the modules and exercises that the
// data survives the crossing, while the *CDC timing itself* is unit-tested in
// H4 -- so every value checked here (Km, R0', Ri', keystream) is quasi-static
// or stable across the crossing and the checks are deterministic.  The buses
// Km_hw/An are held constant for the life of a run and wired straight across
// (they never change while the cipher reads them), exactly as spec section 7
// crossing #4 requires ("held stable >= 8 cycles before the strobe").
//
// The handshake sequence (spec section 10.2 / task):
//   1. load the 40 sink keys via the key-load port; set Bksv; arm rx_enable.
//   2. I2C master reads Bksv (LE), Bcaps (0x80), Bstatus (0x1000).
//   3. I2C master writes An then Aksv (KSV_source) -> aksv_done -> Km
//      accumulator (Km_hw) -> auth_start -> the cipher authenticates.
//   4. drive miniature video frames so the cipher authenticates and counts
//      frames; I2C-read Ri' at 0x08 == R0' after auth and == frame-128 Ri
//      after 128 frames; internal monitors prove Ri_link stability between the
//      mod-128 boundaries.
//   5. encrypt->decrypt round trip: capture the receiver keystream, XOR a block
//      of plaintext to ciphertext, XOR the same keystream back, recover it.
//   6. negative case: a wrong Km (one flipped sink key) yields a different
//      keystream, so decrypting the same ciphertext does NOT recover it.
//   +. (coordination) the receiver accepts ANY Aksv as-is: an all-zero (blank
//      OTP) Aksv still authenticates with Km==0, and a non-balanced Aksv gives
//      the oracle Km and is logged verbatim for the Pi to read back.
//
// Prints TB_PASS / TB_FAIL and a machine-readable KEY=VALUE results file for
// run_hdcp_rx_top.py.
//////////////////////////////////////////////////////////////////////////////
module tb_hdcp_rx_top;

   localparam integer MAXKS = 256;

   // ---- generated vectors (work/, gitignored, no key material committed) ----
   reg [55:0] keys_good_mem [0:39];
   reg [55:0] keys_bad_mem  [0:39];
   reg [63:0] scal          [0:15];

   reg [39:0] AKSV_SRC;
   reg [55:0] KM_GOOD;
   reg [63:0] AN_VAL;
   reg [15:0] EXP_R0, EXP_RI128, EXP_RI256;
   reg [39:0] BKSV_VAL;
   reg [55:0] KM_BAD, KM_ZERO, KM_FF;
   integer    nks;

   // The two extra Aksv acceptance cases the RPi side asked for.
   localparam [39:0] AKSV_ALLZERO = 40'h0000000000;   // blank OTP
   localparam [39:0] AKSV_NONBAL  = 40'h00000000ff;   // 8 ones, not balanced

   // ---- clocks / resets ----
   reg eth_clk = 0;
   reg pix_clk = 0;
   always #10     eth_clk = ~eth_clk;   // 50 MHz
   always #3.367  pix_clk = ~pix_clk;   // 148.5 MHz

   reg reset = 1;   // resets hdcp_rx (eth), hdcp_mod_rx (pix) and tb sync FFs
   reg hpd   = 1;   // high == unplugged: holds hdcp_mod_rx in HDCP_UNPLUG

   // ---- I2C master drive (open-drain via a modelled pull-up) ----
   localparam integer TQ = 1000;        // quarter bit (ns); >>160 ns deglitch
   reg rx_enable   = 0;
   reg scl_drv     = 1'b1;               // 1 = release SCL high; 0 = drive low
   reg mst_sda_low = 1'b0;               // 1 = master pulls SDA low
   wire        sda_drive_low;
   wire SCL_line = scl_drv;              // only the master drives SCL
   wire SDA_line = (mst_sda_low || sda_drive_low) ? 1'b0 : 1'b1;

   // ---- key-load port (eth / sys) ----
   reg [5:0]  key_index = 6'd0;
   reg [31:0] key_lo    = 32'd0;
   reg [23:0] key_hi    = 24'd0;
   reg        key_we    = 1'b0;
   reg        keys_clear = 1'b0;

   // ---- hdcp_rx (eth) ----
   wire [63:0] rx_An;
   wire [39:0] rx_Aksv;
   wire [7:0]  rx_Ainfo;
   wire        rx_aksv_done;
   wire [6:0]  keys_loaded;
   wire [55:0] Km_hw;
   wire        Km_valid_hw;
   reg  [15:0] ri_eth;                   // Ri_link synced back into eth

   hdcp_rx rx (
        .SCL(SCL_line), .SDA(SDA_line),
        .clk(eth_clk), .reset(reset), .rx_enable(rx_enable),
        .sda_drive_low(sda_drive_low),
        .An(rx_An), .Aksv(rx_Aksv), .Ainfo(rx_Ainfo), .aksv_done(rx_aksv_done),
        .Bksv(BKSV_VAL), .Ri(ri_eth), .Pj(8'h00),
        .key_index(key_index), .key_lo(key_lo), .key_hi(key_hi),
        .key_we(key_we), .keys_clear(keys_clear),
        .keys_loaded(keys_loaded), .Km_hw(Km_hw), .Km_valid_hw(Km_valid_hw)
   );

   //====================================================================
   // CDC  eth -> pix  (spec section 7 crossings #4, #5, #5b)
   //====================================================================
   // Km_valid level, 2-FF into pix.
   reg kmv_p1, kmv_p2;
   always @(posedge pix_clk) begin kmv_p1 <= Km_valid_hw; kmv_p2 <= kmv_p1; end

   // auth_start: eth detects Km_valid_hw rising -> toggle; pix syncs the toggle
   // and edge-detects a one-cycle pulse (a classic toggle pulse synchroniser).
   reg kmv_eth_d = 0;
   reg auth_tgl  = 0;
   always @(posedge eth_clk or posedge reset)
     if (reset) begin kmv_eth_d <= 0; auth_tgl <= 0; end
     else begin
        kmv_eth_d <= Km_valid_hw;
        if (Km_valid_hw & ~kmv_eth_d) auth_tgl <= ~auth_tgl;
     end
   reg at1, at2, at3;
   always @(posedge pix_clk or posedge reset)
     if (reset) begin at1 <= 0; at2 <= 0; at3 <= 0; end
     else begin at1 <= auth_tgl; at2 <= at1; at3 <= at2; end
   wire auth_start_pix = at2 ^ at3;

   // Km_hw / An buses are quasi-static for the life of a run (they never change
   // while the cipher reads them) so they are wired straight across.

   // ---- video-timing stimulus into hdcp_mod_rx (pix domain) ----
   reg de = 0, hsync = 0, vsync = 0, line_end = 0, hdcp_ena = 0;
   reg [3:0] ctl_code = 4'b0000;

   wire [23:0] cipher_stream;
   wire        stream_ready;
   wire [15:0] R0_w;
   wire        R0_valid_out;
   wire [15:0] Ri_link;
   wire [15:0] frame_count;
   wire [15:0] Ri_frame;

   hdcp_mod_rx md (
        .clk(pix_clk), .rst(reset), .de(de), .hsync(hsync), .vsync(vsync),
        .line_end(line_end), .hpd(hpd), .Aksv14_write(auth_start_pix),
        .An(rx_An), .Km(Km_hw), .Km_valid(kmv_p2), .hdcp_ena(hdcp_ena),
        .ctl_code(ctl_code), .cipher_stream(cipher_stream),
        .stream_ready(stream_ready),
        .R0(R0_w), .R0_valid_out(R0_valid_out), .Ri_link(Ri_link),
        .frame_count(frame_count), .Ri_frame(Ri_frame)
   );

   //====================================================================
   // CDC  pix -> eth : Ri_link back to the DDC slave (spec section 6).  A
   // simple 2-FF sync; Ri_link is stable when we read it (video is paused),
   // so no read tearing -- the transaction-boundary latching of spec 5.4 is
   // the hardware's job and is exercised by H4, not needed for this data check.
   //====================================================================
   reg [15:0] ri_eth1;
   reg [15:0] fc_eth1, fc_eth;
   always @(posedge eth_clk) begin
      ri_eth1 <= Ri_link;   ri_eth <= ri_eth1;
      fc_eth1 <= frame_count; fc_eth <= fc_eth1;
   end

   //====================================================================
   // monitors
   //====================================================================
   integer errors = 0;
   reg run1_active = 0;

   // R0' capture (run 1 only).
   reg        r0_valid_seen = 0;
   reg [15:0] cap_r0 = 16'hxxxx;
   always @(posedge pix_clk)
     if (run1_active && R0_valid_out) begin
        r0_valid_seen <= 1'b1;
        cap_r0        <= R0_w;
     end

   // Ri_link at key frame counts (run 1 only), same cadence as tb_hdcp_mod_rx.
   reg        got64=0, got127=0, got128=0, got200=0, got256=0;
   reg [15:0] cap_ri64, cap_ri127, cap_ri128, cap_ri200, cap_ri256;
   always @(posedge pix_clk) if (run1_active) begin
      if (frame_count == 16'd64  && !got64 ) begin cap_ri64  <= Ri_link; got64  <= 1; end
      if (frame_count == 16'd127 && !got127) begin cap_ri127 <= Ri_link; got127 <= 1; end
      if (frame_count == 16'd128 && !got128) begin cap_ri128 <= Ri_link; got128 <= 1; end
      if (frame_count == 16'd200 && !got200) begin cap_ri200 <= Ri_link; got200 <= 1; end
      if (frame_count == 16'd256 && !got256) begin cap_ri256 <= Ri_link; got256 <= 1; end
   end

   // frame_count must advance by exactly one at each step (run 1).
   reg [15:0] frame_prev = 16'd0;
   integer    frame_steps = 0;
   always @(posedge pix_clk) if (run1_active && !reset) begin
      if (frame_count !== frame_prev) begin
         if (frame_count === (frame_prev + 16'd1))
           frame_steps = frame_steps + 1;
         else if (frame_count !== 16'd0) begin
            errors = errors + 1;
            $display("  FAIL frame_count jumped %0d -> %0d", frame_prev, frame_count);
         end
      end
      frame_prev <= frame_count;
   end

   // keystream capture (into the selected buffer) while streaming in HDCP_READY.
   reg [23:0] ks_good [0:MAXKS-1];
   reg [23:0] ks_bad  [0:MAXKS-1];
   reg        capturing  = 0;
   reg        capture_sel = 0;   // 0 = good buffer, 1 = bad buffer
   integer    ks_n = 0;
   reg [23:0] ks_or = 24'd0;     // OR of captured words (non-zero check)
   always @(posedge pix_clk)
     if (capturing && (md.HDCP_cstate == md.HDCP_READY) && hdcp_ena && (ks_n < nks)) begin
        if (capture_sel == 1'b0) ks_good[ks_n] <= cipher_stream;
        else                     ks_bad[ks_n]  <= cipher_stream;
        ks_or <= ks_or | cipher_stream;
        ks_n  <= ks_n + 1;
     end

   //====================================================================
   // low-level timing helpers
   //====================================================================
   task px(input integer n);
      integer i;
      begin for (i = 0; i < n; i = i + 1) @(negedge pix_clk); end
   endtask

   //====================================================================
   // I2C master model (from tb_hdcp_rx_i2c.v)
   //====================================================================
   task i2c_start;
      begin
         scl_drv = 1; mst_sda_low = 0; #(2*TQ);
         mst_sda_low = 1;             #(2*TQ);
         scl_drv = 0;                 #(TQ);
      end
   endtask

   task i2c_stop;
      begin
         scl_drv = 0; mst_sda_low = 1; #(TQ);
         scl_drv = 1;                  #(2*TQ);
         mst_sda_low = 0;              #(2*TQ);
      end
   endtask

   task wr_bit(input b);
      begin
         mst_sda_low = ~b; #(TQ);
         scl_drv = 1;      #(2*TQ);
         scl_drv = 0;      #(TQ);
      end
   endtask

   task wr_byte(input [7:0] d, output ack);
      integer i;
      begin
         for (i = 7; i >= 0; i = i - 1) wr_bit(d[i]);
         mst_sda_low = 0; #(TQ);
         scl_drv = 1;     #(TQ);
         ack = ~SDA_line;
         #(TQ);
         scl_drv = 0;     #(TQ);
      end
   endtask

   task rd_bit(output b);
      begin
         mst_sda_low = 0; #(TQ);
         scl_drv = 1;     #(TQ);
         b = SDA_line;
         #(TQ);
         scl_drv = 0;     #(TQ);
      end
   endtask

   task rd_byte(input last, output [7:0] d);
      integer i;
      reg rbit;
      begin
         d = 8'h00;
         for (i = 7; i >= 0; i = i - 1) begin rd_bit(rbit); d[i] = rbit; end
         mst_sda_low = last ? 1'b0 : 1'b1;
         #(TQ);
         scl_drv = 1; #(2*TQ);
         scl_drv = 0; mst_sda_low = 0; #(TQ);
      end
   endtask

   // Write Aksv (5 bytes @0x10, little-endian) through the real DDC slave, so
   // the DUT's own aksv_done strobe drives the Km accumulator.
   task write_aksv(input [39:0] a);
      reg ack;
      begin
         i2c_start;
         wr_byte(8'h74, ack);
         wr_byte(8'h10, ack);
         wr_byte(a[7:0],   ack);
         wr_byte(a[15:8],  ack);
         wr_byte(a[23:16], ack);
         wr_byte(a[31:24], ack);
         wr_byte(a[39:32], ack);   // 0x14 -> aksv_done
         i2c_stop;
      end
   endtask

   // Write An (8 bytes @0x18, little-endian).
   task write_an(input [63:0] a);
      reg ack;
      begin
         i2c_start;
         wr_byte(8'h74, ack);
         wr_byte(8'h18, ack);
         wr_byte(a[7:0],   ack);
         wr_byte(a[15:8],  ack);
         wr_byte(a[23:16], ack);
         wr_byte(a[31:24], ack);
         wr_byte(a[39:32], ack);
         wr_byte(a[47:40], ack);
         wr_byte(a[55:48], ack);
         wr_byte(a[63:56], ack);
         i2c_stop;
      end
   endtask

   // Combined write-pointer, repeated start, read of nbytes.  Returns the bytes
   // in rb[0..nbytes-1] (rb[0] is the byte at the pointer, i.e. little-endian).
   reg [7:0] rb [0:7];
   task read_reg(input [7:0] ptr, input integer nbytes);
      reg ack;
      integer i;
      begin
         i2c_start;
         wr_byte(8'h74, ack);
         wr_byte(ptr, ack);
         i2c_start;                 // repeated start
         wr_byte(8'h75, ack);
         for (i = 0; i < nbytes; i = i + 1)
           rd_byte((i == nbytes-1) ? 1'b1 : 1'b0, rb[i]);
         i2c_stop;
      end
   endtask

   //====================================================================
   // higher-level helpers
   //====================================================================
   task full_reset;
      begin
         reset = 1; hpd = 1; rx_enable = 0; key_we = 0; keys_clear = 0;
         scl_drv = 1; mst_sda_low = 0;
         de = 0; hsync = 0; vsync = 0; line_end = 0; hdcp_ena = 0; ctl_code = 0;
         capturing = 0;
         repeat (8) @(posedge eth_clk);
         px(8);
         reset = 0;
         repeat (8) @(posedge eth_clk);
      end
   endtask

   task load_keys(input use_bad);
      integer i;
      reg [55:0] k;
      begin
         @(negedge eth_clk); keys_clear = 1; @(negedge eth_clk); keys_clear = 0;
         for (i = 0; i < 40; i = i + 1) begin
            @(negedge eth_clk);
            k = use_bad ? keys_bad_mem[i] : keys_good_mem[i];
            key_index = i[5:0]; key_lo = k[31:0]; key_hi = k[55:32]; key_we = 1'b1;
            @(negedge eth_clk); key_we = 1'b0;
         end
         @(negedge eth_clk);
      end
   endtask

   task wait_km(output ok);
      integer g;
      begin
         g = 0;
         while ((Km_valid_hw !== 1'b1) && (g < 4000)) begin @(posedge eth_clk); g = g + 1; end
         ok = (Km_valid_hw === 1'b1);
      end
   endtask

   task wait_cstate(input [17:0] target);
      integer g;
      begin
         g = 0;
         while ((md.HDCP_cstate !== target) && (g < 400000)) begin @(negedge pix_clk); g = g + 1; end
         if (g >= 400000) begin
            errors = errors + 1;
            $display("  FAIL timeout waiting for HDCP_cstate %018b (now %018b)",
                     target, md.HDCP_cstate);
         end
      end
   endtask

   // A full HDCP setup: reset, load keys, arm, write An + Aksv, wait for Km.
   task setup_and_auth(input use_bad, input [39:0] aksv, output km_ok);
      begin
         full_reset;
         load_keys(use_bad);
         // BKSV_VAL persists across full_reset (set once by main).
         rx_enable = 1;
         repeat (6) @(posedge eth_clk);
         hpd = 0;               // plug in: hdcp_mod_rx -> HDCP_WAIT_AKSV
         px(6);
         write_an(AN_VAL);
         write_aksv(aksv);      // 0x14 -> aksv_done -> Km -> auth_start -> cipher
         wait_km(km_ok);
      end
   endtask

   // Reach HDCP_READY with the cipher state == authenticate + one vertical-blank
   // rekey (the FSM's automatic HDCP_AUTH_VSYNC == rekey_frame #1) and NO line
   // rekey, so the first streamed keystream matches the oracle exactly.
   task reach_ready_clean;
      begin
         wait_cstate(md.HDCP_WAIT_1001);
         de = 0; hdcp_ena = 0; line_end = 0; hsync = 0;
         vsync = 1; ctl_code = 4'b1001; px(4);        // EESS boundary
         ctl_code = 4'b0000; vsync = 0; px(2);
         wait_cstate(md.HDCP_READY);                  // frame_count is now 1
      end
   endtask

   // Capture nks keystream words in a clean HDCP_READY streaming window.
   task capture_keystream(input sel);
      integer g;
      begin
         capture_sel = sel; ks_n = 0; ks_or = 24'd0;
         capturing = 1;
         vsync = 0; line_end = 0; ctl_code = 0; de = 1; hdcp_ena = 1;
         g = 0;
         while ((ks_n < nks) && (g < 20000)) begin @(negedge pix_clk); g = g + 1; end
         capturing = 0;
         de = 0; hdcp_ena = 0;
         if (ks_n < nks) begin
            errors = errors + 1;
            $display("  FAIL keystream capture got only %0d / %0d words", ks_n, nks);
         end
      end
   endtask

   // One miniature video frame: an active region (streaming) + a line rekey + a
   // vertical-blank rekey_frame + the EESS marker that increments the counter.
   // Identical cadence to tb_hdcp_mod_rx (the cipher advance rate is faithful;
   // only line/pixel counts are shrunk).
   task mini_frame;
      begin
         vsync = 1'b0; ctl_code = 4'b0000;
         de = 1'b1; hdcp_ena = 1'b1; px(8);
         de = 1'b0; hdcp_ena = 1'b0;
         hsync = 1'b1; px(2); hsync = 1'b0;
         line_end = 1'b1; px(1); line_end = 1'b0;
         px(70);
         vsync = 1'b1; ctl_code = 4'b0000; px(150);
         ctl_code = 4'b1001; px(5); ctl_code = 4'b0000;
         vsync = 1'b0; px(4);
      end
   endtask

   //====================================================================
   // checks / results
   //====================================================================
   task chk16(input [15:0] got, input [15:0] exp, input [255:0] label);
      begin
         if (got !== exp) begin
            errors = errors + 1;
            $display("  FAIL %0s: RTL=%04h oracle=%04h", label, got, exp);
         end else
           $display("  ok   %0s: %04h", label, got);
      end
   endtask

   task chk56(input [55:0] got, input [55:0] exp, input [255:0] label);
      begin
         if (got !== exp) begin
            errors = errors + 1;
            $display("  FAIL %0s: RTL=%014h oracle=%014h", label, got, exp);
         end else
           $display("  ok   %0s: %014h", label, got);
      end
   endtask

   // reconstruct a little-endian value from rb[0..n-1]
   function [63:0] le_value(input integer n);
      integer i;
      begin
         le_value = 64'd0;
         for (i = 0; i < n; i = i + 1) le_value = le_value | (rb[i] << (8*i));
      end
   endfunction

   //====================================================================
   // main stimulus
   //====================================================================
   reg [1023:0] resfile;
   integer      fd, i;
   reg          km_ok;
   reg [55:0]   km_run1, km_zero_run, km_ff_run;
   reg [39:0]   aksv_ff_rb_v;
   reg [15:0]   ri_i2c_auth, ri_i2c_128;
   reg [39:0]   bksv_i2c;
   reg [7:0]    bcaps_i2c;
   reg [15:0]   bstatus_i2c;
   reg [15:0]   frames_final;
   reg [23:0]   pt, ct, rtg, rtb;
   reg          roundtrip_ok, neg_fail;
   reg          ks_zero_nz;
   reg          kmv_zero, kmv_ff;

   initial begin
      if (!$value$plusargs("results=%s", resfile)) resfile = "top_results.txt";

      $readmemh("top_keys_good.mem", keys_good_mem);
      $readmemh("top_keys_bad.mem",  keys_bad_mem);
      $readmemh("top_scalars.mem",   scal);

      AKSV_SRC  = scal[0][39:0];
      KM_GOOD   = scal[1][55:0];
      AN_VAL    = scal[2];
      EXP_R0    = scal[3][15:0];
      EXP_RI128 = scal[4][15:0];
      EXP_RI256 = scal[5][15:0];
      BKSV_VAL  = scal[6][39:0];
      KM_BAD    = scal[7][55:0];
      KM_ZERO   = scal[8][55:0];
      KM_FF     = scal[9][55:0];
      nks       = scal[10][31:0];
      if (nks > MAXKS) nks = MAXKS;

      $display("== H6 full-handshake integration test ==");
      $display("   Aksv=%010h  An=%016h  oracle Km=%014h R0=%04h",
               AKSV_SRC, AN_VAL, KM_GOOD, EXP_R0);

      //================================================================
      // RUN 1: the balanced KSV_source handshake, full frame counting +
      // keystream capture for the round trip.
      //================================================================
      $display("== run 1: balanced KSV_source authentication ==");
      // set Bksv before any reset-driven read; setup_and_auth loads keys etc.
      full_reset;
      load_keys(1'b0);
      if (keys_loaded !== 7'd40) begin
         errors = errors + 1;
         $display("  FAIL keys_loaded = %0d (expected 40)", keys_loaded);
      end else
        $display("  ok   keys_loaded = 40");
      rx_enable = 1;
      repeat (6) @(posedge eth_clk);

      // 2) capability / identity reads over the DDC (little-endian).
      read_reg(8'h00, 5); bksv_i2c    = le_value(5);
      read_reg(8'h40, 1); bcaps_i2c   = rb[0];
      read_reg(8'h41, 2); bstatus_i2c = le_value(2);
      if (bksv_i2c !== BKSV_VAL) begin errors=errors+1;
         $display("  FAIL Bksv I2C = %010h (expected %010h)", bksv_i2c, BKSV_VAL); end
      else $display("  ok   Bksv I2C = %010h", bksv_i2c);
      if (bcaps_i2c !== 8'h80) begin errors=errors+1;
         $display("  FAIL Bcaps I2C = %02h (expected 80)", bcaps_i2c); end
      else $display("  ok   Bcaps I2C = %02h", bcaps_i2c);
      if (bstatus_i2c !== 16'h1000) begin errors=errors+1;
         $display("  FAIL Bstatus I2C = %04h (expected 1000)", bstatus_i2c); end
      else $display("  ok   Bstatus I2C = %04h", bstatus_i2c);

      // 3) write An + Aksv over the DDC -> Km -> auth_start.
      hpd = 0;                       // plug in: hdcp_mod_rx -> HDCP_WAIT_AKSV
      px(6);
      run1_active = 1;
      write_an(AN_VAL);
      write_aksv(AKSV_SRC);
      wait_km(km_ok);
      km_run1 = Km_hw;
      if (!km_ok) begin errors=errors+1; $display("  FAIL Km_valid never rose (run 1)"); end
      else $display("  ok   Km_valid_hw rose");
      chk56(km_run1, KM_GOOD, "Km_hw (balanced KSV_source)");
      if (rx_Aksv !== AKSV_SRC) begin errors=errors+1;
         $display("  FAIL Aksv readback = %010h (expected %010h)", rx_Aksv, AKSV_SRC); end

      // 4a) authenticate the cipher and reach a clean HDCP_READY.
      reach_ready_clean;

      // 5a) capture the receiver keystream for the round trip.  The cipher's
      //     stream output has a fixed short startup latency (a couple of held
      //     words before the sequence advances), so the run script aligns the
      //     dumped capture (top_ks_capture.mem) against the oracle stream and
      //     asserts the full sequence matches -- see run_hdcp_rx_top.py.  The
      //     symmetric round trip below is unaffected by that offset (it XORs
      //     the receiver's own keystream, at one phase, with itself).
      capture_keystream(1'b0);
      $display("  ok   captured %0d keystream words (oracle-aligned in the driver)", nks);

      // 4b) Ri' via the DDC right after auth: frame_count is 1, so Ri_link
      //     still holds R0'.
      repeat (4) @(posedge eth_clk);   // let ri_eth settle
      read_reg(8'h08, 2); ri_i2c_auth = le_value(2);
      chk16(ri_i2c_auth, EXP_R0, "Ri' via I2C @0x08 after auth (== R0')");

      // 4c) drive frames up to the 128-frame boundary, then read Ri' again.
      for (i = 0; i < 127; i = i + 1) mini_frame;   // frame_count -> 128
      repeat (4) @(posedge eth_clk);
      read_reg(8'h08, 2); ri_i2c_128 = le_value(2);
      chk16(ri_i2c_128, EXP_RI128, "Ri' via I2C @0x08 after 128 frames (== Ri128)");

      // 4d) continue to the 256-frame boundary for the monitor captures.
      for (i = 0; i < 128; i = i + 1) mini_frame;   // frame_count -> 256
      frames_final = frame_count;

      run1_active = 0;

      // debug: dump the captured run-1 keystream for offline alignment analysis
      fd = $fopen("top_ks_capture.mem", "w");
      for (i = 0; i < nks; i = i + 1) $fwrite(fd, "%06h\n", ks_good[i]);
      $fclose(fd);

      // R0' / Ri_link boundary + stability checks.
      if (!r0_valid_seen) begin errors=errors+1; $display("  FAIL R0_valid_out never pulsed"); end
      else $display("  ok   R0_valid_out pulsed");
      chk16(cap_r0,    EXP_R0,    "R0' (auth run)");
      chk16(cap_ri64,  EXP_R0,    "Ri_link@64  (== R0')");
      chk16(cap_ri127, EXP_R0,    "Ri_link@127 (== R0')");
      chk16(cap_ri128, EXP_RI128, "Ri_link@128 (frame-128 Ri)");
      chk16(cap_ri200, EXP_RI128, "Ri_link@200 (stable == Ri128)");
      chk16(cap_ri256, EXP_RI256, "Ri_link@256 (frame-256 Ri)");
      $display("  frame_count final = %0d  steps = %0d", frame_count, frame_steps);

      //================================================================
      // RUN 2 (negative): a wrong Km (one flipped sink key) -> a different
      // keystream -> the same ciphertext does NOT decrypt.
      //================================================================
      $display("== run 2: wrong-Km negative case ==");
      setup_and_auth(1'b1, AKSV_SRC, km_ok);
      if (!km_ok) begin errors=errors+1; $display("  FAIL Km_valid never rose (bad keys)"); end
      chk56(Km_hw, KM_BAD, "Km_hw (one flipped sink key)");
      reach_ready_clean;
      capture_keystream(1'b1);       // -> ks_bad

      //================================================================
      // RUN 3: all-zero Aksv (blank OTP) must still authenticate, Km == 0.
      //================================================================
      $display("== run 3: all-zero Aksv (blank OTP) ==");
      setup_and_auth(1'b0, AKSV_ALLZERO, km_ok);
      kmv_zero  = km_ok;
      km_zero_run = Km_hw;
      if (!km_ok) begin errors=errors+1; $display("  FAIL Km_valid never rose (Aksv=0)"); end
      else $display("  ok   Km_valid_hw rose for all-zero Aksv");
      chk56(km_zero_run, KM_ZERO, "Km_hw (all-zero Aksv)");
      reach_ready_clean;
      capture_keystream(1'b0);       // reuse good buffer; only the OR matters
      ks_zero_nz = (ks_or !== 24'd0);
      if (!ks_zero_nz) begin errors=errors+1;
         $display("  FAIL all-zero-Aksv cipher produced an all-zero keystream"); end
      else $display("  ok   all-zero-Aksv cipher still produced a keystream (OR=%06h)", ks_or);

      //================================================================
      // RUN 4: a non-balanced Aksv is accepted as-is; Km == oracle and the
      // received Aksv is logged verbatim for the Pi to read back.
      //================================================================
      $display("== run 4: non-balanced Aksv 0x%010h ==", AKSV_NONBAL);
      setup_and_auth(1'b0, AKSV_NONBAL, km_ok);
      kmv_ff    = km_ok;
      km_ff_run = Km_hw;
      aksv_ff_rb_v = rx_Aksv;
      if (!km_ok) begin errors=errors+1; $display("  FAIL Km_valid never rose (Aksv=0xff)"); end
      else $display("  ok   Km_valid_hw rose for non-balanced Aksv");
      chk56(km_ff_run, KM_FF, "Km_hw (non-balanced Aksv 0xff)");
      if (aksv_ff_rb_v !== AKSV_NONBAL) begin errors=errors+1;
         $display("  FAIL Aksv readback = %010h (expected %010h)", aksv_ff_rb_v, AKSV_NONBAL); end
      else $display("  ok   Aksv readback = %010h (verbatim)", aksv_ff_rb_v);

      //================================================================
      // encrypt -> decrypt round trip (step 5) + negative (step 6).
      //================================================================
      roundtrip_ok = 1'b1;
      neg_fail     = 1'b0;
      for (i = 0; i < nks; i = i + 1) begin
         pt  = {i[7:0] ^ 8'h5a, i[7:0] ^ 8'ha5, i[7:0] ^ 8'h3c};  // plaintext block
         ct  = pt ^ ks_good[i];                                   // encrypt (rx keystream)
         rtg = ct ^ ks_good[i];                                   // decrypt, same keystream
         if (rtg !== pt) roundtrip_ok = 1'b0;
         rtb = ct ^ ks_bad[i];                                    // decrypt, wrong-Km keystream
         if (rtb !== pt) neg_fail = 1'b1;                         // >=1 pixel fails to recover
      end
      if (roundtrip_ok) $display("  ok   encrypt->decrypt round trip recovered the plaintext");
      else begin errors=errors+1; $display("  FAIL round trip did not recover the plaintext"); end
      if (neg_fail) $display("  ok   wrong-Km keystream did NOT recover the plaintext (negative)");
      else begin errors=errors+1; $display("  FAIL wrong-Km keystream still recovered the plaintext"); end

      //================================================================
      // machine-readable results
      //================================================================
      fd = $fopen(resfile, "w");
      $fwrite(fd, "RESULT bksv=%010h bcaps=%02h bstatus=%04h km=%014h ",
              bksv_i2c, bcaps_i2c, bstatus_i2c, km_run1);
      $fwrite(fd, "r0=%04h r0valid=%0d ri_i2c_auth=%04h ri_i2c_128=%04h ",
              cap_r0, r0_valid_seen, ri_i2c_auth, ri_i2c_128);
      $fwrite(fd, "ri64=%04h ri127=%04h ri128=%04h ri200=%04h ri256=%04h frames=%0d ",
              cap_ri64, cap_ri127, cap_ri128, cap_ri200, cap_ri256, frames_final);
      $fwrite(fd, "ks0=%06h roundtrip=%0d neg_fail=%0d ",
              ks_good[0], roundtrip_ok, neg_fail);
      $fwrite(fd, "km_zero=%014h kmv_zero=%0d ks_zero_nz=%0d ",
              km_zero_run, kmv_zero, ks_zero_nz);
      $fwrite(fd, "km_ff=%014h kmv_ff=%0d aksv_ff_rb=%010h errors=%0d\n",
              km_ff_run, kmv_ff, aksv_ff_rb_v, errors);
      $fclose(fd);

      if (errors == 0)
        $display("TB_PASS full HDCP receiver handshake matches the oracle");
      else
        $display("TB_FAIL %0d error(s)", errors);
      $finish;
   end

   // safety timeout
   initial begin
      #(200_000_000);   // 200 ms
      $display("TB_FAIL global timeout");
      $finish;
   end

endmodule
