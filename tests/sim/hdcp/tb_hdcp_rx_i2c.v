`timescale 1ns/1ps
//////////////////////////////////////////////////////////////////////////////
// Testbench for hdcp_rx (task H2): the HDCP receiver DDC I2C slave.
//
// A task-based Verilog I2C *master* model bit-bangs SCL and an open-drain SDA
// with a bus pull-up modelled (SDA is the wired-AND of the master pull-down and
// the DUT's sda_drive_low).  SCL is driven by the master only (the slave never
// stretches).  Bus levels are logical (high = idle); the board's inverting
// buffer belongs to the H4 wrapper, not to this unit test of the module logic.
//
// Checks (spec sections 2 and 3):
//   * write Aksv (5 bytes @0x10) and An (8 bytes @0x18); aksv_done pulses
//     exactly once, on the 0x14 (5th Aksv) byte, and An/Aksv hold the values;
//   * read Bksv (5B @0x00), Bcaps (1B @0x40 = 0x80), Bstatus (2B @0x41 = 0x00,
//     0x10), Ri (2B @0x08) back, little-endian, exactly as the Pi parses them;
//   * a transaction to 0x50 and to 0xA0 is never ACKed (sda_drive_low stays 0);
//   * with rx_enable = 0, a full 0x74 transaction leaves sda_drive_low at 0.
//
// Prints TB_PASS / TB_FAIL for run_hdcp_rx_i2c.py to grep.
//////////////////////////////////////////////////////////////////////////////
module tb_hdcp_rx_i2c;

   // ---- rig constants ----
   localparam [39:0] BKSV_SINK = 40'h59cabe3384;   // rig KSV_sink
   localparam [15:0] RI_CONST  = 16'h57a9;
   localparam [39:0] AKSV_TEST = 40'h108df2b8de;
   localparam [63:0] AN_TEST   = 64'h46b6537884e56c78;

   // ---- master timing (ns).  clk = 50 MHz (20 ns); deglitch fires after
   //      >8 clks (~180 ns), so a >=1 us bus phase has huge margin. ----
   localparam integer TQ = 1000;  // quarter bit

   reg clk = 0;
   reg reset = 1;
   reg rx_enable = 0;

   // master drive controls (open-drain semantics via pull-ups)
   reg scl_drv     = 1'b1;  // 1 = release (bus pulls high); 0 = drive low
   reg mst_sda_low = 1'b0;  // 1 = master pulls SDA low

   wire        sda_drive_low;
   wire [63:0] An;
   wire [39:0] Aksv;
   wire [7:0]  Ainfo;
   wire        aksv_done;
   wire [6:0]  keys_loaded;
   wire [55:0] Km_hw;
   wire        Km_valid_hw;

   wire SCL_line = scl_drv;                                  // only master drives SCL
   wire SDA_line = (mst_sda_low || sda_drive_low) ? 1'b0 : 1'b1;

   hdcp_rx dut (
	.SCL(SCL_line), .SDA(SDA_line),
	.clk(clk), .reset(reset), .rx_enable(rx_enable),
	.sda_drive_low(sda_drive_low),
	.An(An), .Aksv(Aksv), .Ainfo(Ainfo), .aksv_done(aksv_done),
	.Bksv(BKSV_SINK), .Ri(RI_CONST), .Pj(8'h00),
	// H3 Km stub ports
	.key_index(6'd0), .key_lo(32'd0), .key_hi(24'd0),
	.key_we(1'b0), .keys_clear(1'b0),
	.keys_loaded(keys_loaded), .Km_hw(Km_hw), .Km_valid_hw(Km_valid_hw)
   );

   always #10 clk = ~clk;   // 50 MHz

   // ---- monitors ----
   integer aksv_count = 0;
   always @(posedge clk) if (aksv_done) aksv_count = aksv_count + 1;

   reg mon_no_drive = 0;    // when 1, sda_drive_low must stay 0
   reg drive_viol   = 0;
   always @(posedge clk) if (mon_no_drive && sda_drive_low) drive_viol = 1;

   integer errors = 0;

   //====================================================================
   // I2C master model
   //====================================================================
   task i2c_start;   // (repeated) start: SDA high->low while SCL high
      begin
	 scl_drv = 1; mst_sda_low = 0; #(2*TQ);
	 mst_sda_low = 1;             #(2*TQ);   // START
	 scl_drv = 0;                 #(TQ);     // SCL low, ready for data
      end
   endtask

   task i2c_stop;    // stop: SDA low->high while SCL high
      begin
	 scl_drv = 0; mst_sda_low = 1; #(TQ);
	 scl_drv = 1;                  #(2*TQ);
	 mst_sda_low = 0;              #(2*TQ);  // STOP
      end
   endtask

   task wr_bit(input b);
      begin
	 mst_sda_low = ~b;   // b=1 -> release high; b=0 -> pull low
	 #(TQ);              // setup while SCL low
	 scl_drv = 1; #(2*TQ);
	 scl_drv = 0; #(TQ);
      end
   endtask

   // write a byte, return ack (1 = slave ACKed)
   task wr_byte(input [7:0] d, output ack);
      integer i;
      begin
	 for (i = 7; i >= 0; i = i - 1) wr_bit(d[i]);
	 mst_sda_low = 0; #(TQ);       // release SDA for ACK
	 scl_drv = 1;     #(TQ);
	 ack = ~SDA_line;              // ACK = slave pulled SDA low
	 #(TQ);
	 scl_drv = 0;     #(TQ);
      end
   endtask

   // read a bit driven by the slave (sampled during SCL high)
   task rd_bit(output b);
      begin
	 mst_sda_low = 0; #(TQ);       // release SDA
	 scl_drv = 1;     #(TQ);
	 b = SDA_line;
	 #(TQ);
	 scl_drv = 0;     #(TQ);
      end
   endtask

   // read a byte; last=1 -> master NACKs (end of read), else ACKs
   task rd_byte(input last, output [7:0] d);
      integer i;
      reg rbit;
      begin
	 d = 8'h00;
	 for (i = 7; i >= 0; i = i - 1) begin
	    rd_bit(rbit);
	    d[i] = rbit;
	 end
	 mst_sda_low = last ? 1'b0 : 1'b1;   // ACK = SDA low; NACK = release
	 #(TQ);
	 scl_drv = 1; #(2*TQ);
	 scl_drv = 0; mst_sda_low = 0; #(TQ);
      end
   endtask

   //====================================================================
   // check helpers
   //====================================================================
   task expect_byte(input [7:0] got, input [7:0] exp, input [255:0] label);
      begin
	 if (got !== exp) begin
	    errors = errors + 1;
	    $display("  FAIL %0s: got %02h exp %02h", label, got, exp);
	 end else
	   $display("  ok   %0s: %02h", label, got);
      end
   endtask

   //====================================================================
   // stimulus
   //====================================================================
   reg ack;
   reg [7:0] b0, b1, b2, b3, b4;

   initial begin
      // hold reset
      scl_drv = 1; mst_sda_low = 0; rx_enable = 0; reset = 1;
      repeat (10) @(posedge clk);
      reset = 0;
      repeat (10) @(posedge clk);

      //--------------------------------------------------------------
      // 1) rx_enable = 0: the slave must be completely inert
      //--------------------------------------------------------------
      $display("== rx_enable=0: slave must never drive ==");
      mon_no_drive = 1; drive_viol = 0;
      i2c_start;
      wr_byte(8'h74, ack);            // HDCP write address
      if (ack !== 1'b0) begin
	 errors = errors + 1;
	 $display("  FAIL rx_enable=0: slave ACKed 0x74 (ack=%b)", ack);
      end else
	$display("  ok   rx_enable=0: 0x74 not ACKed");
      wr_byte(8'h00, ack);            // would-be pointer
      i2c_start;                      // repeated start
      wr_byte(8'h75, ack);            // read address
      rd_byte(1'b1, b0);              // attempt a read
      i2c_stop;
      if (drive_viol) begin
	 errors = errors + 1;
	 $display("  FAIL rx_enable=0: sda_drive_low asserted");
      end else
	$display("  ok   rx_enable=0: sda_drive_low stayed 0");
      mon_no_drive = 0;

      //--------------------------------------------------------------
      // arm the slave
      //--------------------------------------------------------------
      rx_enable = 1;
      repeat (10) @(posedge clk);

      //--------------------------------------------------------------
      // 2) foreign addresses 0x50 and 0xA0: never ACKed, never driven
      //--------------------------------------------------------------
      $display("== foreign addresses must not be ACKed/driven ==");
      mon_no_drive = 1; drive_viol = 0;
      i2c_start; wr_byte(8'h50, ack);
      if (ack !== 1'b0) begin errors=errors+1; $display("  FAIL 0x50 ACKed"); end
      else $display("  ok   0x50 not ACKed");
      i2c_stop;
      i2c_start; wr_byte(8'hA0, ack);
      if (ack !== 1'b0) begin errors=errors+1; $display("  FAIL 0xA0 ACKed"); end
      else $display("  ok   0xA0 not ACKed");
      i2c_stop;
      if (drive_viol) begin
	 errors = errors + 1;
	 $display("  FAIL foreign addr: sda_drive_low asserted");
      end else
	$display("  ok   foreign addr: sda_drive_low stayed 0");
      mon_no_drive = 0;

      //--------------------------------------------------------------
      // 3) write Aksv (5 bytes @0x10) -- aksv_done must pulse once
      //--------------------------------------------------------------
      $display("== write Aksv @0x10 ==");
      aksv_count = 0;
      i2c_start;
      wr_byte(8'h74, ack); if (ack!==1'b1) begin errors=errors+1; $display("  FAIL 0x74 not ACKed"); end
      wr_byte(8'h10, ack); if (ack!==1'b1) begin errors=errors+1; $display("  FAIL ptr 0x10 not ACKed"); end
      wr_byte(AKSV_TEST[7:0],   ack);
      wr_byte(AKSV_TEST[15:8],  ack);
      wr_byte(AKSV_TEST[23:16], ack);
      wr_byte(AKSV_TEST[31:24], ack);
      if (aksv_count !== 0) begin
	 errors = errors + 1;
	 $display("  FAIL aksv_done fired early (count=%0d before 5th byte)", aksv_count);
      end
      wr_byte(AKSV_TEST[39:32], ack);   // 0x14 -- last byte, triggers aksv_done
      i2c_stop;
      repeat (5) @(posedge clk);
      if (aksv_count !== 1) begin
	 errors = errors + 1;
	 $display("  FAIL aksv_done count = %0d (expected 1)", aksv_count);
      end else
	$display("  ok   aksv_done pulsed once on the 0x14 byte");
      if (Aksv !== AKSV_TEST) begin
	 errors = errors + 1;
	 $display("  FAIL Aksv = %010h (expected %010h)", Aksv, AKSV_TEST);
      end else
	$display("  ok   Aksv = %010h", Aksv);

      //--------------------------------------------------------------
      // 4) write An (8 bytes @0x18)
      //--------------------------------------------------------------
      $display("== write An @0x18 ==");
      i2c_start;
      wr_byte(8'h74, ack);
      wr_byte(8'h18, ack);
      wr_byte(AN_TEST[7:0],   ack);
      wr_byte(AN_TEST[15:8],  ack);
      wr_byte(AN_TEST[23:16], ack);
      wr_byte(AN_TEST[31:24], ack);
      wr_byte(AN_TEST[39:32], ack);
      wr_byte(AN_TEST[47:40], ack);
      wr_byte(AN_TEST[55:48], ack);
      wr_byte(AN_TEST[63:56], ack);
      i2c_stop;
      repeat (5) @(posedge clk);
      if (An !== AN_TEST) begin
	 errors = errors + 1;
	 $display("  FAIL An = %016h (expected %016h)", An, AN_TEST);
      end else
	$display("  ok   An = %016h", An);
      if (aksv_count !== 1) begin
	 errors = errors + 1;
	 $display("  FAIL aksv_done fired on An write (count=%0d)", aksv_count);
      end else
	$display("  ok   An write did not trigger aksv_done");

      //--------------------------------------------------------------
      // 5) read Bksv (5B @0x00), combined write-ptr,Sr,read
      //--------------------------------------------------------------
      $display("== read Bksv @0x00 (LE) ==");
      i2c_start;
      wr_byte(8'h74, ack);
      wr_byte(8'h00, ack);            // set pointer
      i2c_start;                      // repeated start
      wr_byte(8'h75, ack); if (ack!==1'b1) begin errors=errors+1; $display("  FAIL 0x75 not ACKed"); end
      rd_byte(1'b0, b0);
      rd_byte(1'b0, b1);
      rd_byte(1'b0, b2);
      rd_byte(1'b0, b3);
      rd_byte(1'b1, b4);              // last byte -> NACK
      i2c_stop;
      expect_byte(b0, BKSV_SINK[7:0],   "Bksv[0]");
      expect_byte(b1, BKSV_SINK[15:8],  "Bksv[1]");
      expect_byte(b2, BKSV_SINK[23:16], "Bksv[2]");
      expect_byte(b3, BKSV_SINK[31:24], "Bksv[3]");
      expect_byte(b4, BKSV_SINK[39:32], "Bksv[4]");

      //--------------------------------------------------------------
      // 6) read Bcaps (1B @0x40 = 0x80)
      //--------------------------------------------------------------
      $display("== read Bcaps @0x40 ==");
      i2c_start; wr_byte(8'h74, ack); wr_byte(8'h40, ack);
      i2c_start; wr_byte(8'h75, ack);
      rd_byte(1'b1, b0);
      i2c_stop;
      expect_byte(b0, 8'h80, "Bcaps");

      //--------------------------------------------------------------
      // 7) read Bstatus (2B @0x41 = 0x00, 0x10)  -> Pi sees 0x1000
      //--------------------------------------------------------------
      $display("== read Bstatus @0x41 (LE) ==");
      i2c_start; wr_byte(8'h74, ack); wr_byte(8'h41, ack);
      i2c_start; wr_byte(8'h75, ack);
      rd_byte(1'b0, b0);
      rd_byte(1'b1, b1);
      i2c_stop;
      expect_byte(b0, 8'h00, "Bstatus[0]");
      expect_byte(b1, 8'h10, "Bstatus[1]");

      //--------------------------------------------------------------
      // 8) read Ri' (2B @0x08 = 0xa9, 0x57)
      //--------------------------------------------------------------
      $display("== read Ri' @0x08 (LE) ==");
      i2c_start; wr_byte(8'h74, ack); wr_byte(8'h08, ack);
      i2c_start; wr_byte(8'h75, ack);
      rd_byte(1'b0, b0);
      rd_byte(1'b1, b1);
      i2c_stop;
      expect_byte(b0, RI_CONST[7:0],  "Ri[0]");
      expect_byte(b1, RI_CONST[15:8], "Ri[1]");

      //--------------------------------------------------------------
      // verdict
      //--------------------------------------------------------------
      if (errors == 0)
	$display("TB_PASS all hdcp_rx I2C checks passed");
      else
	$display("TB_FAIL %0d error(s)", errors);
      $finish;
   end

   // safety timeout
   initial begin
      #(5_000_000);   // 5 ms
      $display("TB_FAIL timeout");
      $finish;
   end

endmodule
