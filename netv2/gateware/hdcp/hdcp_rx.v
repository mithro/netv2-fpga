`timescale 1 ns / 1 ps
//////////////////////////////////////////////////////////////////////////////
// HDCP 1.x receiver DDC I2C slave + receiver register file.
//
// Task H2 of docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md, spec
// sections 2 and 3 of docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md.
//
// This is a parallel I2C *slave* that lives on the hdmi_in0 DDC bus alongside
// the passive i2c_snoop.v (which is left byte-identical, spec section 1.4).  It
// answers ONLY the HDCP device address 0x3A (0x74 write / 0x75 read); every
// other address -- in particular 0x50 EDID, passed through to the downstream
// sink -- is released and the slave waits for STOP.  The bus is driven through
// an external open-drain FET (Q12H): sda_drive_low = 1 pulls SDA low, 0 lets
// the bus pull-up win.  rx_enable = 0 makes the slave completely inert so a
// bitstream load never disturbs the DDC bus at power-on.
//
// The SCL/SDA sampling front end (2-FF synchroniser + TRF_CYCLES=8 deglitch
// FSMs) is copied verbatim from legacy/overlay/i2c_snoop.v:443-624; the
// protocol FSM is new and, unlike the snooper, shifts *read* data out on the
// SCL falling edge (a slave transmitter must change SDA while SCL is low --
// spec section 2.4), not on the rising edge as the passive snooper does.
//
// SCL is input only: there is no DDC_SCL_PD net on the board, so no clock
// stretching is performed or possible (spec section 2.5).
//
// H3 will ADD a 40x56 sink-key store and a Km accumulator to this module.  The
// ports and a clearly marked section are stubbed out below so H3 has room; no
// Km logic is implemented in H2.
//////////////////////////////////////////////////////////////////////////////

module hdcp_rx (
		// Raw DDC pin levels (already inverted by the board's 74AHC14, but
		// this module takes them as-is and does its own 2-FF sync +
		// deglitch in the clk / eth domain -- spec section 7 crossing #1).
		input wire        SCL,
		input wire        SDA,

		input wire        clk,        // eth domain, 50 MHz
		input wire        reset,

		input wire        rx_enable,  // 0 => slave is inert, never drives SDA

		// Open-drain control: 1 pulls SDA low via the external FET.
		output wire       sda_drive_low,

		// Writable registers exposed to the rest of the receiver.
		output reg [63:0] An,         // 0x18..0x1F, little-endian
		output reg [39:0] Aksv,       // 0x10..0x14, little-endian
		output reg [7:0]  Ainfo,      // 0x15, stored but a no-op
		output reg        aksv_done,  // 1-cycle strobe on the 0x14 (last Aksv) write

		// Readable registers driven in from the rest of the receiver.
		input wire [39:0] Bksv,       // 0x00..0x04, little-endian
		input wire [15:0] Ri,         // 0x08..0x09, little-endian
		input wire [7:0]  Pj,         // 0x0A (0x00 -- 1.1_FEATURES = 0)

		//====================================================================
		// Km accumulator / key-store STUB ports -- H3 fills these in.
		// Present so the H4 wrapper and H3 accumulator have a stable
		// interface; deliberately UNIMPLEMENTED in H2 (tied off below).
		//====================================================================
		input wire [5:0]  key_index,  // H3: sink-key store write index
		input wire [31:0] key_lo,     // H3: low 32 bits of a sink key
		input wire [23:0] key_hi,     // H3: high 24 bits of a sink key
		input wire        key_we,     // H3: key-store write strobe (sys->eth synced)
		input wire        keys_clear, // H3: clear the key store / keys_loaded
		output wire [6:0] keys_loaded, // H3: count of distinct indices loaded
		output wire [55:0] Km_hw,      // H3: computed hardware Km
		output wire       Km_valid_hw  // H3: Km valid (asserts at KM_DONE)
		);

   // Fixed receiver capability registers (spec section 3).
   localparam [7:0] BCAPS       = 8'h80;    // bit7 HDMI_RESERVED only
   localparam [7:0] BSTATUS_LO  = 8'h00;    // 0x41
   localparam [7:0] BSTATUS_HI  = 8'h10;    // 0x42, HDMI_MODE (bit 12) => 0x1000 LE

   // 7-bit HDCP receiver address (0x74 write / 0x75 read).
   localparam [6:0] HDCP_ADDR7  = 7'h3A;

   parameter TRF_CYCLES = 5'd8;  // rise/fall deglitch, 160 ns @ 50 MHz (i2c_snoop.v:74)

   //====================================================================
   // Km accumulator + 40x56 sink-key store (H3, spec section 4).
   //
   // The key store is DISTRIBUTED RAM (LUTRAM), never block RAM: the 35T
   // baseline is at 95% BRAM (spec section 11.3), so 2240 bits of LUTRAM is
   // the cheap choice.  40 entries deep, indexed by key_index[5:0].  Async
   // reads (LUTRAM) mean the accumulator can read keys[j] combinationally.
   //
   // Loading (sys->eth synced key_we pulse; key_index/lo/hi quasi-static):
   //   key_we writes {key_hi, key_lo} at key_index; a write whose index
   //   equals the current keys_loaded advances keys_loaded (so a driver
   //   loading 0..39 in order ends at 40).  keys_clear resets keys_loaded.
   //
   // Km accumulator (spec section 4.3): on aksv_done, if all 40 keys are
   // loaded, walk indices 0..39 over 40 cycles summing keys[j] mod 2^56 for
   // each set Aksv[j] bit, then present Km_hw and raise Km_valid_hw.  A new
   // aksv_done mid-walk abandons the in-flight sum and restarts cleanly
   // (HDCP 1.4 transition B1:B1); a half-loaded store (< 40) yields no Km.
   //====================================================================
   (* ram_style = "distributed" *) reg [55:0] keys [0:39];

   reg [6:0]  keys_loaded_r;   // count of distinct in-order indices loaded (0..40)

   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 keys_loaded_r <= 7'd0;
      end else if (keys_clear) begin
	 keys_loaded_r <= 7'd0;
      end else if (key_we) begin
	 keys[key_index] <= {key_hi[23:0], key_lo[31:0]};
	 if ({1'b0, key_index} == keys_loaded_r)
	   keys_loaded_r <= keys_loaded_r + 7'd1;
      end
   end

   assign keys_loaded = keys_loaded_r;

   // Km accumulator FSM (all in the eth / clk domain).
   localparam [1:0] KM_IDLE = 2'd0;
   localparam [1:0] KM_RUN  = 2'd1;
   localparam [1:0] KM_DONE = 2'd2;

   reg [1:0]  km_state;
   reg [5:0]  km_idx;
   reg [55:0] km_acc;
   reg [55:0] km_hw_r;
   reg        km_valid_r;

   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 km_state   <= KM_IDLE;
	 km_idx     <= 6'd0;
	 km_acc     <= 56'd0;
	 km_hw_r    <= 56'd0;
	 km_valid_r <= 1'b0;
      end else if (aksv_done) begin
	 // Any new last-Aksv byte invalidates the previous Km (B1:B1) and, if
	 // the key store is fully loaded, (re)starts the accumulator cleanly --
	 // abandoning any in-flight sum.
	 km_valid_r <= 1'b0;
	 if (keys_loaded_r == 7'd40) begin
	    km_state <= KM_RUN;
	    km_idx   <= 6'd0;
	    km_acc   <= 56'd0;
	 end else begin
	    km_state <= KM_IDLE;   // half-loaded store: no Km produced
	 end
      end else begin
	 case (km_state)
	   KM_RUN: begin
	      // 56-bit truncating add (natural wraparound), spec section 4.3.
	      if (Aksv[km_idx])
		km_acc <= km_acc + keys[km_idx];
	      if (km_idx == 6'd39)
		km_state <= KM_DONE;
	      km_idx <= km_idx + 6'd1;
	   end
	   KM_DONE: begin
	      km_hw_r    <= km_acc;
	      km_valid_r <= 1'b1;
	      km_state   <= KM_IDLE;
	   end
	   default: ;  // KM_IDLE: hold
	 endcase
      end
   end

   assign Km_hw       = km_hw_r;
   assign Km_valid_hw = km_valid_r;

   // rx_enable is quasi-static (a MultiReg'd CSR in the wrapper); resync it
   // locally so a raw level cannot metastabilise the FSM.
   reg rx_en_s, rx_en_eff;
   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 rx_en_s   <= 1'b0;
	 rx_en_eff <= 1'b0;
      end else begin
	 rx_en_s   <= rx_enable;
	 rx_en_eff <= rx_en_s;
      end
   end

   //====================================================================
   // SCL low-level sampling FSM (verbatim from i2c_snoop.v:443-522)
   // Declared before the protocol FSM that consumes SCL_cstate/SDA_cstate.
   //====================================================================
   parameter SCL_HIGH = 4'b1 << 0;
   parameter SCL_FALL = 4'b1 << 1;
   parameter SCL_LOW  = 4'b1 << 2;
   parameter SCL_RISE = 4'b1 << 3;
   parameter SCL_nSTATES = 4;

   reg [(SCL_nSTATES-1):0] SCL_cstate = {{(SCL_nSTATES-1){1'b0}}, 1'b1};
   reg [(SCL_nSTATES-1):0] SCL_nstate;

   reg [4:0] SCL_rfcnt;
   reg       SCL_s, SCL_sync;
   reg       SDA_s, SDA_sync;

   always @(posedge clk or posedge reset) begin
      if (reset)
	SCL_cstate <= SCL_HIGH;
      else
	SCL_cstate <= SCL_nstate;
   end

   always @(*) begin
      case (SCL_cstate) //synthesis parallel_case full_case
	SCL_HIGH: SCL_nstate = ((SCL_rfcnt > TRF_CYCLES) && (SCL_sync == 1'b0)) ? SCL_FALL : SCL_HIGH;
	SCL_FALL: SCL_nstate = SCL_LOW;
	SCL_LOW:  SCL_nstate = ((SCL_rfcnt > TRF_CYCLES) && (SCL_sync == 1'b1)) ? SCL_RISE : SCL_LOW;
	SCL_RISE: SCL_nstate = SCL_HIGH;
	default:  SCL_nstate = SCL_HIGH;
      endcase
   end

   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 SCL_rfcnt <= 5'b0;
      end else begin
	 case (SCL_cstate) // synthesis parallel_case full_case
	   SCL_HIGH: SCL_rfcnt <= (SCL_sync == 1'b1) ? 5'b0 : SCL_rfcnt + 5'b1;
	   SCL_FALL: SCL_rfcnt <= 5'b0;
	   SCL_LOW:  SCL_rfcnt <= (SCL_sync == 1'b0) ? 5'b0 : SCL_rfcnt + 5'b1;
	   SCL_RISE: SCL_rfcnt <= 5'b0;
	   default:  SCL_rfcnt <= 5'b0;
	 endcase
      end
   end

   //====================================================================
   // SDA low-level sampling FSM (verbatim from i2c_snoop.v:525-605)
   //====================================================================
   parameter SDA_HIGH = 4'b1 << 0;
   parameter SDA_FALL = 4'b1 << 1;
   parameter SDA_LOW  = 4'b1 << 2;
   parameter SDA_RISE = 4'b1 << 3;
   parameter SDA_nSTATES = 4;

   reg [(SDA_nSTATES-1):0] SDA_cstate = {{(SDA_nSTATES-1){1'b0}}, 1'b1};
   reg [(SDA_nSTATES-1):0] SDA_nstate;

   reg [4:0] SDA_rfcnt;

   always @(posedge clk or posedge reset) begin
      if (reset)
	SDA_cstate <= SDA_HIGH;
      else
	SDA_cstate <= SDA_nstate;
   end

   always @(*) begin
      case (SDA_cstate) //synthesis parallel_case full_case
	SDA_HIGH: SDA_nstate = ((SDA_rfcnt > TRF_CYCLES) && (SDA_sync == 1'b0)) ? SDA_FALL : SDA_HIGH;
	SDA_FALL: SDA_nstate = SDA_LOW;
	SDA_LOW:  SDA_nstate = ((SDA_rfcnt > TRF_CYCLES) && (SDA_sync == 1'b1)) ? SDA_RISE : SDA_LOW;
	SDA_RISE: SDA_nstate = SDA_HIGH;
	default:  SDA_nstate = SDA_HIGH;
      endcase
   end

   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 SDA_rfcnt <= 5'b0;
      end else begin
	 case (SDA_cstate) // synthesis parallel_case full_case
	   SDA_HIGH: SDA_rfcnt <= (SDA_sync == 1'b1) ? 5'b0 : SDA_rfcnt + 5'b1;
	   SDA_FALL: SDA_rfcnt <= 5'b0;
	   SDA_LOW:  SDA_rfcnt <= (SDA_sync == 1'b0) ? 5'b0 : SDA_rfcnt + 5'b1;
	   SDA_RISE: SDA_rfcnt <= 5'b0;
	   default:  SDA_rfcnt <= 5'b0;
	 endcase
      end
   end

   //====================================================================
   // 2-FF synchronisers for the raw pins (i2c_snoop.v:612-624)
   //====================================================================
   (* ASYNC_REG = "TRUE" *) reg SCL_meta, SDA_meta;
   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 SCL_meta <= 1'b0; SCL_s <= 1'b0; SCL_sync <= 1'b0;
	 SDA_meta <= 1'b0; SDA_s <= 1'b0; SDA_sync <= 1'b0;
      end else begin
	 SCL_meta <= SCL;  SCL_s <= SCL_meta;  SCL_sync <= SCL_s;
	 SDA_meta <= SDA;  SDA_s <= SDA_meta;  SDA_sync <= SDA_s;
      end
   end

   ////////////////
   ///// protocol-level state machine (new; not the snooper's)
   ////////////////
   parameter I2C_START     = 14'b1 << 0; // one cycle
   parameter I2C_RESTART   = 14'b1 << 1;
   parameter I2C_DADDR     = 14'b1 << 2;
   parameter I2C_ACK_DADDR = 14'b1 << 3;
   parameter I2C_ADDR      = 14'b1 << 4;
   parameter I2C_ACK_ADDR  = 14'b1 << 5;
   parameter I2C_WR_DATA   = 14'b1 << 6;
   parameter I2C_ACK_WR    = 14'b1 << 7;
   parameter I2C_END_WR    = 14'b1 << 8;
   parameter I2C_RD_DATA   = 14'b1 << 9;
   parameter I2C_ACK_RD    = 14'b1 << 10;
   parameter I2C_END_RD    = 14'b1 << 11;
   parameter I2C_END_RD2   = 14'b1 << 12;
   parameter I2C_WAITSTOP  = 14'b1 << 13;

   parameter I2C_nSTATES = 14;

   reg [(I2C_nSTATES-1):0] I2C_cstate = {{(I2C_nSTATES-1){1'b0}}, 1'b1};
   reg [(I2C_nSTATES-1):0] I2C_nstate;

   reg [3:0]  I2C_bitcnt;
   reg [7:0]  I2C_daddr;   // device address byte being shifted in
   reg [7:0]  reg_ptr;     // register pointer (persists across transactions)
   reg [7:0]  I2C_wdata;   // write data byte being shifted in
   reg [7:0]  rd_shift;    // read data byte being shifted out (MSB first)
   reg [15:0] ri_lat;      // Ri latched at START for a tear-free 2-byte read

   // Combinational address match, gated by rx_enable: only ever ACK 0x3A, and
   // only when armed.  Evaluated inside I2C_ACK_DADDR (spec section 2.3).
   wire addr_match = rx_en_eff && (I2C_daddr[7:1] == HDCP_ADDR7);

   // Combinational register read mux (spec section 3).  Anything else reads 0.
   reg [7:0] rd_byte;
   always @(*) begin
      case (reg_ptr)
	8'h00:   rd_byte = Bksv[7:0];
	8'h01:   rd_byte = Bksv[15:8];
	8'h02:   rd_byte = Bksv[23:16];
	8'h03:   rd_byte = Bksv[31:24];
	8'h04:   rd_byte = Bksv[39:32];
	8'h08:   rd_byte = ri_lat[7:0];
	8'h09:   rd_byte = ri_lat[15:8];
	8'h0A:   rd_byte = Pj;
	8'h40:   rd_byte = BCAPS;
	8'h41:   rd_byte = BSTATUS_LO;
	8'h42:   rd_byte = BSTATUS_HI;
	default: rd_byte = 8'h00;
      endcase
   end

   // Open-drain output: only ever pull LOW, never source high.
   //  - ACK the device address if addressed (0x74/0x75) and armed
   //  - ACK the register-pointer byte and every written data byte (addressed)
   //  - drive a read-data 0 bit; leave a 1 to the bus pull-up
   assign sda_drive_low = rx_en_eff &&
	  ( (I2C_cstate == I2C_ACK_DADDR && addr_match) ||
	    (I2C_cstate == I2C_ACK_ADDR)                ||
	    (I2C_cstate == I2C_ACK_WR)                  ||
	    (I2C_cstate == I2C_RD_DATA && (rd_shift[7] == 1'b0)) );

   //====================================================================
   // state register: STOP always resets to I2C_START
   //====================================================================
   always @(posedge clk) begin
      if (reset || ((SCL_cstate == SCL_HIGH) && (SDA_cstate == SDA_RISE)))
	I2C_cstate <= I2C_START;
      else
	I2C_cstate <= I2C_nstate;
   end

   //====================================================================
   // next-state logic
   //====================================================================
   always @(*) begin
      case (I2C_cstate) //synthesis parallel_case full_case
	I2C_START: begin
	   I2C_nstate = ((SDA_cstate == SDA_FALL) && (SCL_cstate == SCL_HIGH)) ?
			I2C_DADDR : I2C_START;
	end
	I2C_RESTART: begin
	   I2C_nstate = I2C_DADDR;
	end
	I2C_DADDR: begin
	   I2C_nstate = ((I2C_bitcnt > 4'h7) && (SCL_cstate == SCL_FALL)) ?
			I2C_ACK_DADDR : I2C_DADDR;
	end
	I2C_ACK_DADDR: begin
	   // Decide during the ACK bit itself: match => ACK and branch on R/W;
	   // no match (foreign address, or disarmed) => release and wait for STOP.
	   I2C_nstate = (SCL_cstate == SCL_FALL) ?
			( addr_match ?
			  (I2C_daddr[0] == 1'b0 ? I2C_ADDR : I2C_RD_DATA) :
			  I2C_WAITSTOP ) :
			I2C_ACK_DADDR;
	end

	// write branch: register pointer byte
	I2C_ADDR: begin
	   I2C_nstate = ((I2C_bitcnt > 4'h7) && (SCL_cstate == SCL_FALL)) ?
			I2C_ACK_ADDR : I2C_ADDR;
	end
	I2C_ACK_ADDR: begin
	   I2C_nstate = (SCL_cstate == SCL_FALL) ? I2C_WR_DATA : I2C_ACK_ADDR;
	end

	// write branch: data bytes
	I2C_WR_DATA: begin
	   I2C_nstate = ((SDA_cstate == SDA_FALL) && (SCL_cstate == SCL_HIGH)) ?
			I2C_RESTART :
			((I2C_bitcnt > 4'h7) && (SCL_cstate == SCL_FALL)) ?
			I2C_ACK_WR : I2C_WR_DATA;
	end
	I2C_ACK_WR: begin
	   I2C_nstate = (SCL_cstate == SCL_FALL) ? I2C_END_WR : I2C_ACK_WR;
	end
	I2C_END_WR: begin // one cycle: commit ptr++ ; SCL is low here
	   I2C_nstate = I2C_WR_DATA;
	end

	// read branch: data bytes, shifted out on SCL falling edge
	I2C_RD_DATA: begin
	   I2C_nstate = ((SDA_cstate == SDA_FALL) && (SCL_cstate == SCL_HIGH)) ?
			I2C_RESTART :
			((I2C_bitcnt == 4'h7) && (SCL_cstate == SCL_FALL)) ?
			I2C_ACK_RD : I2C_RD_DATA;
	end
	I2C_ACK_RD: begin // sample master (n)ack on the rising edge
	   I2C_nstate = (SCL_cstate == SCL_RISE) ? I2C_END_RD : I2C_ACK_RD;
	end
	I2C_END_RD: begin // ack (SDA low) => continue; nack => back to start
	   I2C_nstate = (SDA_cstate == SDA_LOW) ? I2C_END_RD2 : I2C_START;
	end
	I2C_END_RD2: begin // wait for a clean falling edge before next byte
	   I2C_nstate = (SCL_cstate == SCL_FALL) ? I2C_RD_DATA : I2C_END_RD2;
	end

	// not addressed: idle until STOP or repeated START
	I2C_WAITSTOP: begin
	   I2C_nstate = ((SCL_cstate == SCL_HIGH) && (SDA_cstate == SDA_RISE)) ?
			I2C_START :
			((SCL_cstate == SCL_HIGH) && (SDA_cstate == SDA_FALL)) ?
			I2C_RESTART :
			I2C_WAITSTOP;
	end
	default: I2C_nstate = I2C_START;
      endcase
   end

   //====================================================================
   // datapath: shift registers, register pointer, aksv strobe
   //====================================================================
   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 I2C_bitcnt <= 4'b0;
	 I2C_daddr  <= 8'b0;
	 reg_ptr    <= 8'b0;    // persists across transactions
	 I2C_wdata  <= 8'b0;
	 rd_shift   <= 8'b0;
	 ri_lat     <= 16'b0;
	 aksv_done  <= 1'b0;
	 An         <= 64'b0;
	 Aksv       <= 40'b0;
	 Ainfo      <= 8'b0;
      end else begin
	 aksv_done <= 1'b0;   // default; pulsed only in I2C_END_WR below

	 case (I2C_cstate) // synthesis parallel_case full_case
	   I2C_START: begin
	      I2C_bitcnt <= 4'b0;
	      I2C_daddr  <= 8'b0;
	      I2C_wdata  <= 8'b0;
	      ri_lat     <= Ri;   // latch Ri once per transaction (tear-free read)
	   end

	   I2C_RESTART: begin
	      I2C_bitcnt <= 4'b0;
	      I2C_daddr  <= 8'b0;
	      I2C_wdata  <= 8'b0;
	      // reg_ptr and ri_lat preserved (combined write-ptr,Sr,read)
	   end

	   I2C_DADDR: begin // shift in device address on rising edges
	      if (SCL_cstate == SCL_RISE) begin
		 I2C_bitcnt   <= I2C_bitcnt + 4'b1;
		 I2C_daddr    <= {I2C_daddr[6:0],
				  (SDA_cstate == SDA_HIGH) ? 1'b1 : 1'b0};
	      end
	   end

	   I2C_ACK_DADDR: begin
	      I2C_bitcnt <= 4'b0;
	      rd_shift   <= rd_byte;  // preload first read byte (harmless on write)
	   end

	   I2C_ADDR: begin // shift in register pointer on rising edges
	      if (SCL_cstate == SCL_RISE) begin
		 I2C_bitcnt <= I2C_bitcnt + 4'b1;
		 reg_ptr    <= {reg_ptr[6:0],
				(SDA_cstate == SDA_HIGH) ? 1'b1 : 1'b0};
	      end
	   end

	   I2C_ACK_ADDR: begin
	      I2C_bitcnt <= 4'b0;
	   end

	   I2C_WR_DATA: begin // shift in write data on rising edges
	      if (SCL_cstate == SCL_RISE) begin
		 I2C_bitcnt <= I2C_bitcnt + 4'b1;
		 I2C_wdata  <= {I2C_wdata[6:0],
				(SDA_cstate == SDA_HIGH) ? 1'b1 : 1'b0};
	      end
	   end

	   I2C_ACK_WR: begin
	      I2C_bitcnt <= 4'b0;
	      // register commit happens in the write-decode block below
	   end

	   I2C_END_WR: begin // one cycle: pointer auto-increment + aksv strobe
	      reg_ptr    <= reg_ptr + 8'b1;
	      I2C_bitcnt <= 4'b0;
	      I2C_wdata  <= 8'b0;
	      aksv_done  <= (reg_ptr == 8'h14);  // last Aksv byte just written
	   end

	   I2C_RD_DATA: begin // shift out data on FALLING edges (slave transmit)
	      if (SCL_cstate == SCL_FALL) begin
		 I2C_bitcnt <= I2C_bitcnt + 4'b1;
		 rd_shift   <= {rd_shift[6:0], 1'b0};
	      end
	   end

	   I2C_ACK_RD: begin
	      I2C_bitcnt <= 4'b0;
	   end

	   I2C_END_RD: begin // pointer auto-increment on a read
	      reg_ptr    <= reg_ptr + 8'b1;
	      I2C_bitcnt <= 4'b0;
	   end

	   I2C_END_RD2: begin
	      rd_shift   <= rd_byte;  // reload with the (incremented) pointer's byte
	      I2C_bitcnt <= 4'b0;
	   end

	   I2C_WAITSTOP: begin
	      I2C_bitcnt <= 4'b0;
	      I2C_daddr  <= 8'b0;
	   end

	   default: ;
	 endcase

	 // ---- write decode: little-endian register bytes (spec section 3) ----
	 if (I2C_cstate == I2C_ACK_WR) begin
	    case (reg_ptr)
	      8'h10: Aksv[7:0]   <= I2C_wdata;
	      8'h11: Aksv[15:8]  <= I2C_wdata;
	      8'h12: Aksv[23:16] <= I2C_wdata;
	      8'h13: Aksv[31:24] <= I2C_wdata;
	      8'h14: Aksv[39:32] <= I2C_wdata;
	      8'h15: Ainfo       <= I2C_wdata;   // stored, no-op
	      8'h18: An[7:0]     <= I2C_wdata;
	      8'h19: An[15:8]    <= I2C_wdata;
	      8'h1A: An[23:16]   <= I2C_wdata;
	      8'h1B: An[31:24]   <= I2C_wdata;
	      8'h1C: An[39:32]   <= I2C_wdata;
	      8'h1D: An[47:40]   <= I2C_wdata;
	      8'h1E: An[55:48]   <= I2C_wdata;
	      8'h1F: An[63:56]   <= I2C_wdata;
	      default: ;   // read-only / reserved offsets: ACKed and discarded
	    endcase
	 end

	 // Ainfo clears on the last-Aksv (0x14) write (spec section 2.8).
	 if ((I2C_cstate == I2C_END_WR) && (reg_ptr == 8'h14))
	   Ainfo <= 8'h0;
      end
   end

endmodule // hdcp_rx
