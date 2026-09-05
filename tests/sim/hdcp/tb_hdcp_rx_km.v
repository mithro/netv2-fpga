`timescale 1ns/1ps
//////////////////////////////////////////////////////////////////////////////
// Testbench for hdcp_rx (task H3): the Km accumulator + 40x56 sink-key store.
//
// Spec section 4 of docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md,
// verification cases 10.2 items 3, 5, 6.
//
// The sink keys, the source KSV (Aksv) and the expected Km are all generated
// from ~/netv2-hdcp-handoff/keys/sink_keys.bin by run_hdcp_rx_km.py into
// work/km_vectors.mem (42 lines of 56-bit hex: 40 keys, then Aksv, then the
// oracle Km computed by netv2/hdcp/keys.km_from_keys) and $readmemh'd here.  No
// key material is ever committed -- the .mem lives only under work/ (gitignored)
// and is regenerated at run time.
//
// Keys are loaded through the direct CSR-style load port (key_index/lo/hi/we,
// the sys->eth synced write path).  Aksv is written through the same task-based
// I2C *master* model used by tb_hdcp_rx_i2c.v, so the real aksv_done strobe out
// of the protocol FSM drives the accumulator (cases 1 and 2).  For the mid-walk
// restart (case 3) two aksv_done pulses must land < 40 cycles apart -- physically
// impossible over a 100 kHz DDC bus -- so that one case force-injects aksv_done.
//
// Cases:
//   1) full 40-key store, Aksv = KSV_source: Km_valid_hw rises and
//      Km_hw == the oracle Km;
//   2) only 20 keys loaded: Km_valid_hw never asserts;
//   3) a second aksv_done mid-walk restarts the accumulator cleanly -- the final
//      Km_hw still equals the oracle (not a doubled / partial sum).
//
// Prints TB_PASS / TB_FAIL for run_hdcp_rx_km.py to grep.
//////////////////////////////////////////////////////////////////////////////
module tb_hdcp_rx_km;

   localparam [39:0] BKSV_SINK = 40'h59cabe3384;
   localparam [15:0] RI_CONST  = 16'h57a9;

   // ---- generated vectors (work/km_vectors.mem) ----
   //  [0:39] = 40 sink keys, [40] = Aksv (low 40 bits), [41] = expected Km.
   reg [55:0] vec [0:41];
   reg [39:0] AKSV_SRC;
   reg [55:0] KM_EXP;

   // ---- master timing (ns).  clk = 50 MHz (20 ns); deglitch fires after
   //      >8 clks (~180 ns), so a >=1 us bus phase has huge margin. ----
   localparam integer TQ = 1000;  // quarter bit

   reg clk = 0;
   reg reset = 1;
   reg rx_enable = 0;

   // key-load port
   reg [5:0]  key_index = 6'd0;
   reg [31:0] key_lo    = 32'd0;
   reg [23:0] key_hi    = 24'd0;
   reg        key_we    = 1'b0;
   reg        keys_clear = 1'b0;

   // master drive controls (open-drain semantics via pull-ups)
   reg scl_drv     = 1'b1;
   reg mst_sda_low = 1'b0;

   wire        sda_drive_low;
   wire [63:0] An;
   wire [39:0] Aksv;
   wire [7:0]  Ainfo;
   wire        aksv_done;
   wire [6:0]  keys_loaded;
   wire [55:0] Km_hw;
   wire        Km_valid_hw;

   wire SCL_line = scl_drv;
   wire SDA_line = (mst_sda_low || sda_drive_low) ? 1'b0 : 1'b1;

   hdcp_rx dut (
	.SCL(SCL_line), .SDA(SDA_line),
	.clk(clk), .reset(reset), .rx_enable(rx_enable),
	.sda_drive_low(sda_drive_low),
	.An(An), .Aksv(Aksv), .Ainfo(Ainfo), .aksv_done(aksv_done),
	.Bksv(BKSV_SINK), .Ri(RI_CONST), .Pj(8'h00),
	.key_index(key_index), .key_lo(key_lo), .key_hi(key_hi),
	.key_we(key_we), .keys_clear(keys_clear),
	.keys_loaded(keys_loaded), .Km_hw(Km_hw), .Km_valid_hw(Km_valid_hw)
   );

   always #10 clk = ~clk;   // 50 MHz

   integer errors = 0;

   // Km_valid rising-edge monitor (armed only when we expect no Km).
   reg mon_no_km  = 0;
   reg km_seen    = 0;
   always @(posedge clk) if (mon_no_km && Km_valid_hw) km_seen = 1;

   //====================================================================
   // I2C master model (reused from tb_hdcp_rx_i2c.v)
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
	 mst_sda_low = ~b;
	 #(TQ);
	 scl_drv = 1; #(2*TQ);
	 scl_drv = 0; #(TQ);
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

   // write Aksv (5 bytes little-endian @0x10) via the real DDC slave, so the
   // DUT's own aksv_done strobe drives the accumulator.
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

   //====================================================================
   // helpers
   //====================================================================
   // Load n keys (indices 0..n-1, in order) through the CSR-style load port.
   task load_keys(input integer n);
      integer i;
      begin
	 for (i = 0; i < n; i = i + 1) begin
	    @(negedge clk);
	    key_index = i[5:0];
	    key_lo    = vec[i][31:0];
	    key_hi    = vec[i][55:32];
	    key_we    = 1'b1;
	    @(negedge clk);
	    key_we    = 1'b0;
	 end
	 @(negedge clk);
      end
   endtask

   // Pulse the DUT's aksv_done for exactly one clk (case 3 only).  Forced
   // because two triggers < 40 cycles apart cannot occur over real I2C.
   task force_aksv_done;
      begin
	 @(negedge clk); force dut.aksv_done = 1'b1;
	 @(negedge clk); force dut.aksv_done = 1'b0;
      end
   endtask

   task do_reset;
      begin
	 reset = 1; rx_enable = 0; key_we = 0; keys_clear = 0;
	 scl_drv = 1; mst_sda_low = 0;
	 repeat (6) @(posedge clk);
	 reset = 0;
	 repeat (6) @(posedge clk);
      end
   endtask

   task check_km(input [55:0] got, input [255:0] label);
      begin
	 if (got !== KM_EXP) begin
	    errors = errors + 1;
	    $display("  FAIL %0s: Km_hw = %014h (expected %014h)", label, got, KM_EXP);
	 end else
	   $display("  ok   %0s: Km_hw = %014h", label, got);
      end
   endtask

   //====================================================================
   // stimulus
   //====================================================================
   integer w;

   initial begin
      $readmemh("km_vectors.mem", vec);
      AKSV_SRC = vec[40][39:0];
      KM_EXP   = vec[41];
      $display("== loaded vectors: Aksv=%010h expected Km=%014h ==", AKSV_SRC, KM_EXP);

      //--------------------------------------------------------------
      // Case 1: full 40-key store, Aksv = KSV_source -> Km == oracle
      //--------------------------------------------------------------
      $display("== case 1: full 40 keys, expect Km_valid + oracle Km ==");
      do_reset;
      load_keys(40);
      if (keys_loaded !== 7'd40) begin
	 errors = errors + 1;
	 $display("  FAIL keys_loaded = %0d (expected 40)", keys_loaded);
      end else
	$display("  ok   keys_loaded = 40");
      rx_enable = 1;
      repeat (6) @(posedge clk);
      write_aksv(AKSV_SRC);
      // walk is ~42 cycles; wait generously for Km_valid to rise.
      w = 0;
      while ((Km_valid_hw !== 1'b1) && (w < 200)) begin
	 @(posedge clk); w = w + 1;
      end
      if (Km_valid_hw !== 1'b1) begin
	 errors = errors + 1;
	 $display("  FAIL Km_valid_hw never rose");
      end else begin
	 $display("  ok   Km_valid_hw rose");
	 if (Aksv !== AKSV_SRC) begin
	    errors = errors + 1;
	    $display("  FAIL Aksv latched = %010h (expected %010h)", Aksv, AKSV_SRC);
	 end
	 check_km(Km_hw, "case1");
      end

      //--------------------------------------------------------------
      // Case 2: only 20 keys loaded -> no Km_valid ever
      //--------------------------------------------------------------
      $display("== case 2: half-loaded (20 keys), expect NO Km_valid ==");
      do_reset;
      load_keys(20);
      if (keys_loaded !== 7'd20) begin
	 errors = errors + 1;
	 $display("  FAIL keys_loaded = %0d (expected 20)", keys_loaded);
      end else
	$display("  ok   keys_loaded = 20");
      mon_no_km = 1; km_seen = 0;
      rx_enable = 1;
      repeat (6) @(posedge clk);
      write_aksv(AKSV_SRC);      // aksv_done fires but store is half-loaded
      repeat (200) @(posedge clk);   // well past a full 40-cycle walk
      mon_no_km = 0;
      if (km_seen || (Km_valid_hw === 1'b1)) begin
	 errors = errors + 1;
	 $display("  FAIL Km_valid_hw asserted on a half-loaded store");
      end else
	$display("  ok   Km_valid_hw stayed low (no Km from partial load)");

      //--------------------------------------------------------------
      // Case 3: second aksv_done mid-walk -> clean restart, correct Km
      //--------------------------------------------------------------
      $display("== case 3: aksv_done mid-walk must restart cleanly ==");
      do_reset;
      load_keys(40);
      rx_enable = 1;
      repeat (6) @(posedge clk);
      write_aksv(AKSV_SRC);          // latch Aksv (also runs one real walk)
      // let that first real walk settle.
      w = 0;
      while ((Km_valid_hw !== 1'b1) && (w < 200)) begin @(posedge clk); w = w+1; end

      // Now start a fresh walk and interrupt it mid-flight with a second
      // aksv_done.  If the accumulator failed to reset km_acc, the final sum
      // would be doubled/partial; a clean restart reproduces the oracle Km.
      force_aksv_done;               // start walk A (clears Km_valid)
      repeat (3) @(posedge clk);
      if (Km_valid_hw !== 1'b0) begin
	 errors = errors + 1;
	 $display("  FAIL Km_valid_hw not cleared by a new aksv_done");
      end else
	$display("  ok   Km_valid_hw cleared on new aksv_done");
      repeat (10) @(posedge clk);    // mid-walk (< 40 cycles into walk A)
      if (Km_valid_hw === 1'b1) begin
	 errors = errors + 1;
	 $display("  FAIL walk A completed before the mid-walk retrigger");
      end
      force_aksv_done;               // restart -> walk B, abandon A
      release dut.aksv_done;
      w = 0;
      while ((Km_valid_hw !== 1'b1) && (w < 200)) begin @(posedge clk); w = w+1; end
      if (Km_valid_hw !== 1'b1) begin
	 errors = errors + 1;
	 $display("  FAIL Km_valid_hw never rose after restart");
      end else begin
	 $display("  ok   Km_valid_hw rose after clean restart");
	 check_km(Km_hw, "case3");
      end

      //--------------------------------------------------------------
      if (errors == 0)
	$display("TB_PASS all hdcp_rx Km checks passed");
      else
	$display("TB_FAIL %0d error(s)", errors);
      $finish;
   end

   // safety timeout
   initial begin
      #(20_000_000);   // 20 ms
      $display("TB_FAIL timeout");
      $finish;
   end

endmodule
