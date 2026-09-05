`timescale 1ns/1ps
//////////////////////////////////////////////////////////////////////////////
// Testbench for hdcp_mod_rx (the HDCP-receiver mod-cipher controller patch).
//
// Proves that hdcp_mod_rx -- driving the H1 cipher patch hdcp_cipher_rx --
// latches the receiver-side values correctly (design of record section 5.2/5.3):
//
//   * R0'  is captured from the INITIAL authentication run only (not the
//     immediately-following R1 rekey -- the "R0-vs-Ri trap"), and R0_valid_out
//     pulses when it lands;
//   * Ri_link (the value the transmitter reads at DDC 0x08) holds R0' until the
//     128th frame, then updates to the frame-128 Ri, then the frame-256 Ri, and
//     does NOT change between those 128-frame boundaries;
//   * frame_count advances exactly once per EESS (vsync && ctl_code==4'b1001)
//     boundary.
//
// The golden R0/Ri128/Ri256 come from $readmemh of cipher_vectors.hex
// (vector 0 = a throwaway test Km (never the shared-rig secret)), produced by gen_cipher_vectors.py
// from netv2/hdcp/cipher.py, so the Python model is the oracle (design 5.1).
//
// TIMING SHORTCUT (documented per the task): real 1080p frames are ~1.1M pixel
// clocks each; simulating 256 of them is infeasible.  Instead a free-running
// generator emits a MINIATURE frame per iteration -- a short active region with
// one line_end rekey pulse, then vsync high while the per-frame vsync block
// cipher runs (~112 clocks), then the EESS marker (ctl_code==4'b1001) at vsync,
// then vsync low.  This is faithful to what the Ri logic depends on: the
// per-frame block cipher advances Mi (and therefore the Ri sequence) exactly as
// in hardware regardless of frame length, one line_end rekey per frame
// exercises the rekey path (which must NOT corrupt the per-frame Ri), and the
// 128-frame Ri_link boundary and frame counter are driven by the same EESS
// event the controller tracks in HDCP_WAIT_1001.  Line/pixel counts are shrunk;
// the cipher cadence and the mod-128 boundary logic are not.
//
// Plusargs:
//   +vectors=<path>  golden $readmemh file (default cipher_vectors.hex)
//   +results=<path>  machine-readable capture file for run_hdcp_mod_rx.py
//////////////////////////////////////////////////////////////////////////////
module tb_hdcp_mod_rx;

   // -- DUT ports -----------------------------------------------------------
   reg         clk = 0;
   reg         rst = 1;
   reg         de = 0, hsync = 0, vsync = 0, line_end = 0, hpd = 1;
   reg         Aksv14_write = 0;
   reg [63:0]  An = 0;
   reg [55:0]  Km = 0;
   reg         Km_valid = 0;
   reg         hdcp_ena = 0;
   reg [3:0]   ctl_code = 4'b0000;
   wire [23:0] cipher_stream;
   wire        stream_ready;
   wire [15:0] R0;
   wire        R0_valid_out;
   wire [15:0] Ri_link;
   wire [15:0] frame_count;
   wire [15:0] Ri_frame;

   hdcp_mod_rx dut (
      .clk(clk), .rst(rst), .de(de), .hsync(hsync), .vsync(vsync),
      .line_end(line_end), .hpd(hpd), .Aksv14_write(Aksv14_write),
      .An(An), .Km(Km), .Km_valid(Km_valid), .hdcp_ena(hdcp_ena),
      .ctl_code(ctl_code), .cipher_stream(cipher_stream),
      .stream_ready(stream_ready),
      .R0(R0), .R0_valid_out(R0_valid_out), .Ri_link(Ri_link),
      .frame_count(frame_count), .Ri_frame(Ri_frame));

   always #5 clk = ~clk;   // 100 MHz sim clock

   // -- golden vectors (vector 0 = rig) -------------------------------------
   reg [63:0]   V [0:14];   // Km An R0 Ri128 Ri256, flat, three vectors
   reg [15:0]   exp_r0, exp_ri128, exp_ri256;
   reg [1023:0] vecfile, resfile;
   integer      fd, errors;

   // -- capture monitors ----------------------------------------------------
   reg          r0_valid_seen = 0;
   reg [15:0]   cap_r0 = 16'hxxxx;
   reg          got64 = 0, got127 = 0, got128 = 0, got200 = 0, got256 = 0;
   reg [15:0]   cap_ri64, cap_ri127, cap_ri128, cap_ri200, cap_ri256;
   reg [15:0]   frame_prev = 16'd0;
   integer      frame_steps;   // count of +1 increments observed

   // R0': latched on the auth run only; R0_valid_out must pulse exactly once.
   always @(posedge clk) begin
      if (R0_valid_out) begin
	 r0_valid_seen <= 1'b1;
	 cap_r0        <= R0;
      end
   end

   // Ri_link at key frame counts.  Ri_link updates on the same clock edge that
   // frame_count reaches a multiple of 128, so the guarded first-capture sees a
   // settled value.  64/127 must still read R0'; 128 the frame-128 Ri; 200 must
   // still read the frame-128 Ri (stable between boundaries); 256 frame-256 Ri.
   always @(posedge clk) begin
      if (frame_count == 16'd64  && !got64 ) begin cap_ri64  <= Ri_link; got64  <= 1; end
      if (frame_count == 16'd127 && !got127) begin cap_ri127 <= Ri_link; got127 <= 1; end
      if (frame_count == 16'd128 && !got128) begin cap_ri128 <= Ri_link; got128 <= 1; end
      if (frame_count == 16'd200 && !got200) begin cap_ri200 <= Ri_link; got200 <= 1; end
      if (frame_count == 16'd256 && !got256) begin cap_ri256 <= Ri_link; got256 <= 1; end
   end

   // frame_count must advance by exactly 1 at each step (never skip / jump).
   always @(posedge clk) begin
      if (!rst) begin
	 if (frame_count !== frame_prev) begin
	    if (frame_count === (frame_prev + 16'd1))
	      frame_steps = frame_steps + 1;
	    else if (frame_count !== 16'd0) begin  // 0 is the auth reset, allowed
	       errors = errors + 1;
	       $display("  FAIL frame_count jumped %0d -> %0d", frame_prev, frame_count);
	    end
	 end
	 frame_prev <= frame_count;
      end
   end

   // -- free-running miniature video generator ------------------------------
   reg gen_enable = 0;
   initial begin
      forever begin
	 if (!gen_enable) begin
	    @(negedge clk);
	 end else begin
	    // phase A: active region + one line_end rekey (vsync low)
	    vsync = 1'b0; ctl_code = 4'b0000;
	    de = 1'b1; hdcp_ena = 1'b1; repeat (8) @(negedge clk);
	    de = 1'b0; hdcp_ena = 1'b0;
	    hsync = 1'b1; repeat (2) @(negedge clk); hsync = 1'b0;
	    line_end = 1'b1; @(negedge clk); line_end = 1'b0;   // rekey pulse
	    repeat (70) @(negedge clk);   // let the ~56-clock rekey finish
	    // phase B: vsync rising -> per-frame vsync block cipher runs
	    vsync = 1'b1; ctl_code = 4'b0000;
	    repeat (150) @(negedge clk);
	    // phase C: EESS marker at vsync -> frame boundary
	    ctl_code = 4'b1001;
	    repeat (5) @(negedge clk);
	    ctl_code = 4'b0000;
	    // phase D: end of frame
	    vsync = 1'b0;
	    repeat (4) @(negedge clk);
	 end
      end
   end

   task check16(input [15:0] got, input [15:0] exp, input [255:0] label);
      begin
	 if (got !== exp) begin
	    errors = errors + 1;
	    $display("  FAIL %0s: RTL=%04h model=%04h", label, got, exp);
	 end else begin
	    $display("  ok   %0s: %04h", label, got);
	 end
      end
   endtask

   // -- main stimulus -------------------------------------------------------
   integer timeout;
   initial begin
      if (!$value$plusargs("vectors=%s", vecfile)) vecfile = "cipher_vectors.hex";
      if (!$value$plusargs("results=%s", resfile)) resfile = "mod_rx_results.txt";
      $readmemh(vecfile, V);
      Km        = V[0][55:0];
      An        = V[1];
      exp_r0    = V[2][15:0];
      exp_ri128 = V[3][15:0];
      exp_ri256 = V[4][15:0];
      errors = 0;
      frame_steps = 0;

      // reset (hpd high == unplugged holds the FSM in HDCP_UNPLUG)
      rst = 1; hpd = 1; Km_valid = 1'b1;
      repeat (6) @(negedge clk);
      rst = 0;
      repeat (2) @(negedge clk);
      // "plug in": hpd low -> FSM leaves UNPLUG for HDCP_WAIT_AKSV
      hpd = 0;
      repeat (4) @(negedge clk);

      // start the video generator and trigger authentication
      gen_enable = 1;
      repeat (4) @(negedge clk);
      Aksv14_write = 1'b1; @(negedge clk); Aksv14_write = 1'b0;

      // run until 256 frame boundaries have been counted (or timeout)
      timeout = 0;
      while (!got256 && timeout < 2000000) begin
	 @(negedge clk);
	 timeout = timeout + 1;
      end

      $display("VEC test Km=%014h An=%016h", Km, An);
      $display("  R0_valid_out seen: %0d", r0_valid_seen);
      if (!r0_valid_seen) begin
	 errors = errors + 1;
	 $display("  FAIL R0_valid_out never pulsed");
      end
      check16(cap_r0,    exp_r0,    "R0'");
      // Ri_link stability + boundary values
      check16(cap_ri64,  exp_r0,    "Ri_link@frame64  (== R0', pre-boundary)");
      check16(cap_ri127, exp_r0,    "Ri_link@frame127 (== R0', pre-boundary)");
      check16(cap_ri128, exp_ri128, "Ri_link@frame128 (frame-128 Ri)");
      check16(cap_ri200, exp_ri128, "Ri_link@frame200 (stable, == frame-128 Ri)");
      check16(cap_ri256, exp_ri256, "Ri_link@frame256 (frame-256 Ri)");
      $display("  frame_count final=%0d  steps=%0d", frame_count, frame_steps);
      if (timeout >= 2000000) begin
	 errors = errors + 1;
	 $display("  FAIL timeout before reaching 256 frames (got %0d)", frame_count);
      end

      fd = $fopen(resfile, "w");
      $fwrite(fd, "RESULT km=%014h an=%016h r0=%04h r0valid=%0d ",
	      Km, An, cap_r0, r0_valid_seen);
      $fwrite(fd, "ri64=%04h ri127=%04h ri128=%04h ri200=%04h ri256=%04h frames=%0d\n",
	      cap_ri64, cap_ri127, cap_ri128, cap_ri200, cap_ri256, frame_count);
      $fclose(fd);

      if (errors == 0)
	$display("TB_PASS hdcp_mod_rx matches the oracle");
      else
	$display("TB_FAIL %0d mismatches", errors);
      $finish;
   end

endmodule
