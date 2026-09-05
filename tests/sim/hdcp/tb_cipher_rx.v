`timescale 1ns/1ps
//////////////////////////////////////////////////////////////////////////////
// Testbench for hdcp_cipher_rx (the HDCP-receiver cipher patch).
//
// Proves the patched Ri output and R0_valid strobe are bit-exact with the
// Python reference model netv2/hdcp/cipher.py.  For each (Km, An) vector it
// runs one authentication block cipher (auth=1 -> R0) then 256 rekey block
// ciphers (auth=0 -> per-frame Ri), sampling the Ri output on each R0_valid
// pulse.  Golden R0/Ri128/Ri256 come from $readmemh of a file produced by
// gen_cipher_vectors.py, so the model is the oracle (design of record 5.1).
//
// Plusargs:
//   +vectors=<path>  golden $readmemh file (default cipher_vectors.hex)
//   +results=<path>  machine-readable capture file (default cipher_rx_results.txt)
//////////////////////////////////////////////////////////////////////////////
module tb_cipher_rx;

   localparam NVEC = 3;

   reg         clk = 0;
   reg         reset = 1;
   reg [55:0]  Km;
   reg [63:0]  An;
   reg         init = 0, auth = 0, rekeyc = 0, streamc = 0;
   wire [23:0] pr_data;
   wire        stream_ready;
   wire [15:0] Ri;
   wire        R0_valid;

   integer     v, base, f, fd, errors;
   reg [63:0]  V [0:(NVEC*5)-1];   // Km An R0 Ri128 Ri256, flat, per vector
   reg [15:0]  exp_r0, exp_ri128, exp_ri256;
   reg [1023:0] vecfile, resfile;

   hdcp_cipher_rx dut(.clk(clk), .reset(reset), .Km(Km), .An(An),
		      .hdcpBlockCipher_init(init), .authentication(auth),
		      .hdcpRekeyCipher(rekeyc), .hdcpStreamCipher(streamc),
		      .pr_data(pr_data), .stream_ready(stream_ready),
		      .Ri(Ri), .R0_valid(R0_valid));

   always #5 clk = ~clk;

   // Sample the Ri output on each R0_valid pulse.  Pulse index 0 is the
   // authentication run (R0); index k is rekey frame k, so index 128/256 are
   // the frame-128/256 Ri.  Reset (per vector) clears the counter and captures.
   integer     valid_count;
   reg [15:0]  cap_r0, cap_ri128, cap_ri256;
   always @(posedge clk or posedge reset) begin
      if (reset) begin
	 valid_count <= 0;
	 cap_r0    <= 16'hxxxx;
	 cap_ri128 <= 16'hxxxx;
	 cap_ri256 <= 16'hxxxx;
      end else if (R0_valid) begin
	 if (valid_count == 0)   cap_r0    <= Ri;
	 if (valid_count == 128) cap_ri128 <= Ri;
	 if (valid_count == 256) cap_ri256 <= Ri;
	 valid_count <= valid_count + 1;
      end
   end

   // one block-cipher run: pulse init (+auth) then wait for stream_ready
   task do_init(input a);
      begin
	 @(negedge clk); init = 1; auth = a;
	 @(negedge clk); init = 0; auth = 0;
	 repeat (4) @(negedge clk);
	 while (!stream_ready) @(negedge clk);
      end
   endtask

   task check(input [15:0] got, input [15:0] exp, input [255:0] label);
      begin
	 if (got !== exp) begin
	    errors = errors + 1;
	    $display("  FAIL %0s: RTL=%04h model=%04h", label, got, exp);
	 end else begin
	    $display("  ok   %0s: %04h", label, got);
	 end
      end
   endtask

   initial begin
      if (!$value$plusargs("vectors=%s", vecfile)) vecfile = "cipher_vectors.hex";
      if (!$value$plusargs("results=%s", resfile)) resfile = "cipher_rx_results.txt";
      $readmemh(vecfile, V);
      fd = $fopen(resfile, "w");
      errors = 0;

      for (v = 0; v < NVEC; v = v + 1) begin
	 base = v * 5;
	 // per-vector reset clears cipher state and the capture monitor
	 reset = 1; init = 0; auth = 0; rekeyc = 0; streamc = 0;
	 Km = V[base+0][55:0];
	 An = V[base+1];
	 repeat (4) @(negedge clk);
	 reset = 0;
	 repeat (2) @(negedge clk);

	 // authentication -> R0
	 do_init(1'b1);
	 // 256 rekey frames -> per-frame Ri
	 for (f = 1; f <= 256; f = f + 1)
	   do_init(1'b0);

	 exp_r0    = V[base+2][15:0];
	 exp_ri128 = V[base+3][15:0];
	 exp_ri256 = V[base+4][15:0];

	 $display("VEC %0d Km=%014h An=%016h", v, Km, An);
	 check(cap_r0,    exp_r0,    "R0");
	 check(cap_ri128, exp_ri128, "Ri@128");
	 check(cap_ri256, exp_ri256, "Ri@256");

	 // machine-readable line for run_cipher_rx.py to re-check vs the oracle
	 $fwrite(fd, "RESULT %0d km=%014h an=%016h r0=%04h ri128=%04h ri256=%04h\n",
		 v, Km, An, cap_r0, cap_ri128, cap_ri256);
      end

      $fclose(fd);
      if (errors == 0)
	$display("TB_PASS all %0d vectors match the oracle", NVEC);
      else
	$display("TB_FAIL %0d mismatches", errors);
      $finish;
   end

endmodule
