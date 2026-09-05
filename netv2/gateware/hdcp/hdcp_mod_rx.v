`timescale 1 ns / 1 ps
//////////////////////////////////////////////////////////////////////////////
// HDCP RECEIVER PATCH (netv2/gateware/hdcp): hdcp_mod_rx
//
// This is a renamed, patched copy of legacy/overlay/hdcp_mod.v.  The ORIGINAL
// legacy controller is never edited.  Changes here, all ADDITIVE (the overlay
// keystream datapath -- cipher_stream / stream_ready and every original signal
// -- is byte-identical to the legacy module):
//
//   1. module hdcp_mod -> hdcp_mod_rx.
//   2. the internal `hdcp_cipher` instance -> `hdcp_cipher_rx` (the H1 cipher
//      patch), whose extra outputs Ri[15:0] and R0_valid expose the R0/Ri that
//      the block cipher produces in output[23:16].
//   3. new receiver outputs, latched in the pix (this) clock domain:
//        R0[15:0]        -- the initial-authentication R0'  (design 5.2)
//        R0_valid_out    -- one-cycle strobe when R0' is latched
//        Ri_link[15:0]   -- the value the transmitter reads at 0x08: R0' until
//                           the 128th frame, then the Ri of the most recent
//                           128-frame boundary (HDCP 1.4 sec 2.2.3 / design 5.2)
//        frame_count[15:0] -- frames counted at the EESS (vsync && ctl==1001)
//                             boundary the controller already tracks (design 5.3)
//        Ri_frame[15:0]  -- raw per-frame Ri from the latest rekey (debug)
//
// See docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md sections 5.2
// and 5.3, and netv2/gateware/hdcp/README.md.
//
// R0-vs-Ri "trap" (design 5.2): the controller runs the block cipher TWICE
// back-to-back at authentication -- HDCP_AUTH_PULSE with authentication=1
// produces (Ks, M0, R0), then HDCP_AUTH_VSYNC_PULSE with authentication=0
// immediately produces (K1, M1, R1).  So the SAME cipher output holds R0 right
// after auth and R1 a microsecond later.  R0 must therefore be latched from the
// FIRST (auth) run only.  The H1 cipher exposes Ri/R0_valid but NOT the auth
// flag, so we recover it from THIS controller's own FSM: `cur_is_auth` is set
// while the auth run is in flight and cleared for every rekey run.
//////////////////////////////////////////////////////////////////////////////

// generates a stream of hdcp cipher data
module hdcp_mod_rx (
		 input wire 	    clk, // pixclk
		 input wire 	    rst,
		 input wire 	    de,
		 input wire 	    hsync, // positive active
		 input wire 	    vsync,
		 input wire 	    line_end, // need to double check the purpose but nominally de && (sdata == CTRLTOKEN*)
		 input wire 	    hpd, // high == no cable present
		 input wire 	    Aksv14_write, // strobe to indicate ksv was written
		 input wire [63:0]  An,
		 input wire [55:0]  Km,
		 input wire 	    Km_valid,
		 input wire 	    hdcp_ena,
		 input wire [3:0]   ctl_code, // control code
		 output wire [23:0] cipher_stream,
		 output wire 	    stream_ready,
		 // --- HDCP receiver additions (design 5.2 / 5.3) ---
		 output wire [15:0] R0,          // initial-authentication R0'
		 output wire 	    R0_valid_out, // 1-cycle strobe when R0' latched
		 output wire [15:0] Ri_link,     // value the Tx reads at 0x08 (mod-128)
		 output wire [15:0] frame_count, // frames counted at EESS boundary
		 output wire [15:0] Ri_frame     // raw per-frame Ri (debug)
		 );

   reg         Km_rdy0;
   reg         Km_rdy1;
   reg 	       Km_rdy2;
   wire        Km_ready;
   reg 	       hdcp_requested;

   wire       vsync_rising;
   reg 	      vsync_v2;
   always @(posedge clk) begin
      vsync_v2 <= vsync;
   end
   assign vsync_rising = vsync & !vsync_v2;

   ///////
   // HDCP
   ///////
   parameter HDCP_UNPLUG      = 18'b1 << 0;  // 1
   parameter HDCP_WAIT_AKSV   = 18'b1 << 1;  // 2
   parameter HDCP_AUTH_PULSE  = 18'b1 << 2;  // 4
   parameter HDCP_AUTH        = 18'b1 << 3;  // 8
   parameter HDCP_AUTH_WAIT   = 18'b1 << 4;  // 10
   parameter HDCP_AUTH_VSYNC_PULSE  = 18'b1 << 5;  // 20
   parameter HDCP_AUTH_VSYNC        = 18'b1 << 6;  // 40
   parameter HDCP_AUTH_VSYNC_WAIT   = 18'b1 << 7;  // 80
   parameter HDCP_WAIT_1001   = 18'b1 << 8;  // 100
   parameter HDCP_WAIT_1001_END = 18'b1 << 9;  // 200
   parameter HDCP_VSYNC       = 18'b1 << 10; // 400
   parameter HDCP_VSYNC_PULSE = 18'b1 << 11; // 800
   parameter HDCP_VSYNC_WAIT  = 18'b1 << 12; // 1000
   parameter HDCP_READY       = 18'b1 << 13; // 2000
   parameter HDCP_REKEY       = 18'b1 << 14; // 4000
   parameter HDCP_REKEY_WAIT  = 18'b1 << 15; // 8000
   parameter HDCP_WAIT_KMRDY  = 18'b1 << 16; // 10000

   parameter HDCP_nSTATES = 17;

   reg [(HDCP_nSTATES-1):0]     HDCP_cstate = {{(HDCP_nSTATES-1){1'b0}}, 1'b1};
   reg [(HDCP_nSTATES-1):0]     HDCP_nstate;

   reg 				auth_mode;
   reg 				hdcp_init;
   wire 			hdcp_stream_ena;

   reg 				active_line;
   wire 			hdcp_rekey;

   reg 				hsync_v, hsync_v2;

   assign hdcp_is_ready = (HDCP_cstate == HDCP_READY);

   reg 				le_pipe;

   assign hdcp_rekey = line_end;

   always @ (posedge clk) begin
      if( rst == 1'b1 ) begin
	 active_line <= 1'b0;
	 hsync_v <= 1'b0;
	 hsync_v2 <= 1'b0;
      end else begin
	 hsync_v <= hsync;
	 hsync_v2 <= hsync_v;

	 if( de ) begin
	    active_line <= 1'b1;
	 end else if( !hsync_v & hsync_v2 ) begin // hsync falling
	    active_line <= 1'b0;
	 end
      end
   end

   always @ (posedge clk) begin
      if ( hpd | rst )
	HDCP_cstate <= HDCP_UNPLUG;
      else
	if( Aksv14_write ) begin
	   HDCP_cstate <= HDCP_AUTH_PULSE; // hack for tivo series 3
	end else begin
	   HDCP_cstate <=#1 HDCP_nstate;
	end
   end

   always @ (*) begin
      case (HDCP_cstate) //synthesis parallel_case full_case
	HDCP_UNPLUG: begin
	   HDCP_nstate = hpd ? HDCP_UNPLUG : HDCP_WAIT_AKSV;
	end
	HDCP_WAIT_AKSV: begin
	   HDCP_nstate = Aksv14_write ? HDCP_AUTH_PULSE : HDCP_WAIT_AKSV;
	end

	// this state is unreachable
	HDCP_WAIT_KMRDY: begin
	   HDCP_nstate = Km_ready ? HDCP_AUTH_PULSE : HDCP_WAIT_KMRDY;
	end

	HDCP_AUTH_PULSE: begin
	   HDCP_nstate = HDCP_AUTH;
	end
	HDCP_AUTH: begin
	   HDCP_nstate = stream_ready? HDCP_AUTH : HDCP_AUTH_WAIT;
	end
	HDCP_AUTH_WAIT: begin
	   HDCP_nstate = stream_ready ? HDCP_AUTH_VSYNC_PULSE : HDCP_AUTH_WAIT;
	end

	HDCP_AUTH_VSYNC_PULSE: begin
	   HDCP_nstate = HDCP_AUTH_VSYNC;
	end
	HDCP_AUTH_VSYNC: begin
	   HDCP_nstate = stream_ready ? HDCP_AUTH_VSYNC : HDCP_AUTH_VSYNC_WAIT;
	end
	HDCP_AUTH_VSYNC_WAIT: begin
	   HDCP_nstate = stream_ready ? HDCP_WAIT_1001 : HDCP_AUTH_VSYNC_WAIT;
	end

	// our primary wait state
	HDCP_WAIT_1001: begin
	   HDCP_nstate = (vsync && (ctl_code[3:0] == 4'b1001)) ?
			 HDCP_WAIT_1001_END : HDCP_WAIT_1001;
	end
	HDCP_WAIT_1001_END: begin
	   HDCP_nstate = (vsync && (ctl_code[3:0] == 4'b1001)) ?
			 HDCP_WAIT_1001_END : HDCP_READY;
	end


	HDCP_VSYNC_PULSE: begin
	   HDCP_nstate = HDCP_VSYNC;
	end
	HDCP_VSYNC: begin
	   HDCP_nstate = stream_ready ? HDCP_VSYNC : HDCP_VSYNC_WAIT;
	end
	HDCP_VSYNC_WAIT: begin
	   HDCP_nstate = stream_ready ? HDCP_WAIT_1001 : HDCP_VSYNC_WAIT;
	end

	// our primary cipher state
	HDCP_READY: begin
	   HDCP_nstate = (stream_ready == 1'b0) ? HDCP_REKEY_WAIT :
			 vsync_rising ? HDCP_VSYNC_PULSE :
			 HDCP_READY;
	end

	HDCP_REKEY: begin
	   HDCP_nstate = stream_ready ? HDCP_REKEY : HDCP_REKEY_WAIT;
	end
	HDCP_REKEY_WAIT: begin
	   HDCP_nstate = stream_ready ? HDCP_READY : HDCP_REKEY_WAIT;
	end
      endcase // case (HDCP_cstate)
   end

   assign Km_ready = Km_rdy2; // for now make it level triggered ("cheezy mode")

   always @ (posedge clk ) begin
      if( rst | hpd ) begin
	 auth_mode <=#1 1'b0;
	 hdcp_init <=#1 1'b0;
	 hdcp_requested <=#1 1'b0;

	 Km_rdy0 <= 1'b0;
	 Km_rdy1 <= 1'b0;
	 Km_rdy2 <= 1'b0;
      end else begin
	 Km_rdy0 <= Km_valid;
	 Km_rdy1 <= Km_rdy0;
	 Km_rdy2 <= Km_rdy1;

	 case (HDCP_cstate) //synthesis parallel_case full_case
	   HDCP_UNPLUG: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end
	   HDCP_WAIT_AKSV: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end

	   HDCP_WAIT_KMRDY: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end

	   HDCP_AUTH_PULSE: begin
	      auth_mode <=#1 1'b1;
	      hdcp_init <=#1 1'b1; // pulse just one cycle
	      hdcp_requested <=#1 1'b0;
	   end
	   HDCP_AUTH: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end
	   HDCP_AUTH_WAIT: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end

	   HDCP_AUTH_VSYNC_PULSE: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b1;  // pulse init, but not with auth_mode
	      hdcp_requested <=#1 1'b0;
	   end
	   HDCP_AUTH_VSYNC: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end
	   HDCP_AUTH_VSYNC_WAIT: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end

	   HDCP_WAIT_1001: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end
	   HDCP_WAIT_1001_END: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b0;
	   end

	   HDCP_VSYNC_PULSE: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b1;  // pulse init, but not with auth_mode
	      hdcp_requested <=#1 1'b1;
	   end
	   HDCP_VSYNC: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b1;
	   end
	   HDCP_VSYNC_WAIT: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b1;
	   end

	   HDCP_READY: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b1;
	   end

	   HDCP_REKEY: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b1;
	   end
	   HDCP_REKEY_WAIT: begin
	      auth_mode <=#1 1'b0;
	      hdcp_init <=#1 1'b0;
	      hdcp_requested <=#1 1'b1;
	   end
	 endcase // case (HDCP_cstate)
      end // else: !if( ~rstbtn_n | hpd )
   end // always @ (posedge tx0_pclk)


   ///////////////////////////////////////////////////////////////////////////
   // HDCP RECEIVER ADDITION (design 5.2): recover the auth-vs-rekey identity of
   // the cipher run that is currently in flight.  The controller pulses the
   // cipher's `authentication` input only in HDCP_AUTH_PULSE; every later run
   // (HDCP_AUTH_VSYNC_PULSE and HDCP_VSYNC_PULSE) is a rekey with
   // authentication=0.  `cur_is_auth` mirrors that intent and, because it is
   // sticky between the *_PULSE states, is still valid ~112 cycles later when
   // the cipher raises R0_valid (which lands while the FSM waits in
   // HDCP_AUTH_WAIT for the auth run, or HDCP_*_VSYNC_WAIT for a rekey run).
   ///////////////////////////////////////////////////////////////////////////
   reg cur_is_auth;
   always @(posedge clk) begin
      if( rst | hpd )
	cur_is_auth <= 1'b0;
      else if( Aksv14_write || (HDCP_cstate == HDCP_AUTH_PULSE) )
	cur_is_auth <= 1'b1;   // an authentication (R0) run is being launched
      else if( (HDCP_cstate == HDCP_AUTH_VSYNC_PULSE) ||
	       (HDCP_cstate == HDCP_VSYNC_PULSE) )
	cur_is_auth <= 1'b0;   // a per-frame rekey (Ri) run is being launched
   end

   ///////////////////////////////////////////////////////////////////////////
   // HDCP RECEIVER ADDITION (design 5.2 / 5.3): latch R0', the per-frame Ri,
   // and the mod-128 link value Ri_link.
   //
   // The H1 cipher raises R0_valid one cycle before stream_ready with Ri stable
   // (design 5.1).  On that strobe:
   //   * an auth run (cur_is_auth) latches R0' and seeds Ri_link with it, and
   //     resets the frame counter (state B1->B2);
   //   * a rekey run latches the raw per-frame Ri into Ri_frame_r.
   //
   // The frame counter and the mod-128 Ri_link update advance on the EESS
   // boundary the controller already tracks -- (HDCP_cstate == HDCP_WAIT_1001)
   // && vsync && ctl_code==1001 -- which occurs once per frame, AFTER that
   // frame's rekey has completed (so Ri_frame_r already holds the frame's Ri).
   // Ri_link is refreshed to Ri_frame_r only when the counter increment lands on
   // a multiple of 128 -- HDCP 1.4 sec 2.2.3, "updated for every 128th frame
   // counter increment, starting with the 128th" -- matching cipher.py's
   // ri (ri_current) vs ri_frame.  Everything is in this pix clock domain.
   ///////////////////////////////////////////////////////////////////////////
   wire cipher_R0_valid;
   wire [15:0] cipher_Ri;

   wire eess_frame = (HDCP_cstate == HDCP_WAIT_1001) &&
		     vsync && (ctl_code[3:0] == 4'b1001);

   reg [15:0] R0_r;
   reg [15:0] Ri_frame_r;
   reg [15:0] Ri_link_r;
   reg [15:0] frame_counter;
   reg        R0_valid_r;

   always @(posedge clk) begin
      if( rst | hpd ) begin
	 R0_r          <= 16'd0;
	 Ri_frame_r    <= 16'd0;
	 Ri_link_r     <= 16'd0;
	 frame_counter <= 16'd0;
	 R0_valid_r    <= 1'b0;
      end else begin
	 R0_valid_r <= 1'b0;

	 // cipher-completion capture (auth R0 vs per-frame Ri)
	 if( cipher_R0_valid ) begin
	    if( cur_is_auth ) begin
	       R0_r          <= cipher_Ri;
	       Ri_frame_r    <= cipher_Ri;
	       Ri_link_r     <= cipher_Ri;  // link value starts as R0'
	       frame_counter <= 16'd0;
	       R0_valid_r    <= 1'b1;
	    end else begin
	       Ri_frame_r    <= cipher_Ri;  // raw per-frame Ri
	    end
	 end

	 // frame counting + mod-128 Ri_link publish, on the EESS boundary
	 if( eess_frame ) begin
	    frame_counter <= frame_counter + 16'd1;
	    if( ((frame_counter + 16'd1) & 16'd127) == 16'd0 )
	      Ri_link_r <= Ri_frame_r;
	 end
      end
   end

   assign R0           = R0_r;
   assign R0_valid_out = R0_valid_r;
   assign Ri_link      = Ri_link_r;
   assign frame_count  = frame_counter;
   assign Ri_frame     = Ri_frame_r;

   hdcp_cipher_rx  cipher (
		.clk(clk),
		.reset(rst),
		.Km(Km),
		.An(An),
		.hdcpBlockCipher_init(hdcp_init),
		.authentication(auth_mode),
		.hdcpRekeyCipher(hdcp_rekey),
		.hdcpStreamCipher(hdcp_ena && (HDCP_cstate == HDCP_READY)),
		.pr_data(cipher_stream),
		.stream_ready(stream_ready),
		.Ri(cipher_Ri),
		.R0_valid(cipher_R0_valid)
		);
endmodule // hdcp_mod_rx
