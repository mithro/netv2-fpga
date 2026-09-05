#include <stdio.h>
#include <generated/csr.h>

#include "mmcm.h"

#define MMCM_TIMEOUT 1000000

/*
 * Despite varying pixel clocks, we must keep the PLL VCO operating
 * in the specified range of 600MHz - 1200MHz.
 */
#ifdef CSR_HDMI_OUT0_BASE
void hdmi_out0_mmcm_write(int adr, int data) {
	hdmi_out0_driver_clocking_mmcm_adr_write(adr);
	hdmi_out0_driver_clocking_mmcm_dat_w_write(data);
	hdmi_out0_driver_clocking_mmcm_write_write(1);
	while(!hdmi_out0_driver_clocking_mmcm_drdy_read());
}

int hdmi_out0_mmcm_read(int adr) {
	hdmi_out0_driver_clocking_mmcm_adr_write(adr);
	hdmi_out0_driver_clocking_mmcm_read_write(1);
	while(!hdmi_out0_driver_clocking_mmcm_drdy_read());
	return hdmi_out0_driver_clocking_mmcm_dat_r_read();
}
#endif

#ifdef CSR_HDMI_IN0_BASE
void hdmi_in0_clocking_mmcm_write(int adr, int data) {
  int timeout = 0;
	hdmi_in0_clocking_mmcm_adr_write(adr);
	hdmi_in0_clocking_mmcm_dat_w_write(data);
	hdmi_in0_clocking_mmcm_write_write(1);
	while(!hdmi_in0_clocking_mmcm_drdy_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in0_clocking_mmcm_write failed with adr %x, data %x\n", adr, data);
	}
}

int hdmi_in0_clocking_mmcm_read(int adr) {
  int timeout = 0;
	hdmi_in0_clocking_mmcm_adr_write(adr);
	hdmi_in0_clocking_mmcm_read_write(1);
	while(!hdmi_in0_clocking_mmcm_drdy_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in0_clocking_mmcm_read failed with adr %x\n", adr);
	}

	return hdmi_in0_clocking_mmcm_dat_r_read();
}

#ifdef CSR_HDMI_IN0_CLOCKING_MMCM_DRDY_O_ADDR
void hdmi_in0_clocking_mmcm_write_o(int adr, int data) {
  int timeout = 0;
	hdmi_in0_clocking_mmcm_adr_write(adr);
	hdmi_in0_clocking_mmcm_dat_w_write(data);
	hdmi_in0_clocking_mmcm_write_o_write(1);
	while(!hdmi_in0_clocking_mmcm_drdy_o_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in0_clocking_mmcm_write_o failed with adr %x, data %x\n", adr, data);
	}
}

int hdmi_in0_clocking_mmcm_read_o(int adr) {
  int timeout = 0;
	hdmi_in0_clocking_mmcm_adr_write(adr);
	hdmi_in0_clocking_mmcm_read_o_write(1);
	while(!hdmi_in0_clocking_mmcm_drdy_o_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in0_clocking_mmcm_read_o failed with adr %x\n", adr);
	}

	return hdmi_in0_clocking_mmcm_dat_o_r_read();
}
#endif

static void hdmi_in_0_config_30_60mhz(void) {
	hdmi_in0_clocking_mmcm_write(0x14, 0x1000 | (10<<6) | 10); /* clkfbout_mult  = 20 */
	hdmi_in0_clocking_mmcm_write(0x08, 0x1000 | (10<<6) | 10); /* clkout0_divide = 20 */
	hdmi_in0_clocking_mmcm_write(0x0a, 0x1000 |  (8<<6) |  8); /* clkout1_divide = 16 */
	hdmi_in0_clocking_mmcm_write(0x0c, 0x1000 |  (2<<6) |  2); /* clkout2_divide =  4 */
	hdmi_in0_clocking_mmcm_write(0x0d, 0);                     /* clkout2_divide =  4 */
}

static void hdmi_in_0_config_60_120mhz(void) {
	hdmi_in0_clocking_mmcm_write(0x14, 0x1000 |  (5<<6) | 5); /* clkfbout_mult  = 10 */
	hdmi_in0_clocking_mmcm_write(0x08, 0x1000 |  (5<<6) | 5); /* clkout0_divide = 10 */
	hdmi_in0_clocking_mmcm_write(0x0a, 0x1000 |  (4<<6) | 4); /* clkout1_divide =  8 */
	hdmi_in0_clocking_mmcm_write(0x0c, 0x1000 |  (1<<6) | 1); /* clkout2_divide =  2 */
	hdmi_in0_clocking_mmcm_write(0x0d, 0);                    /* clkout2_divide =  2 */

	// lock/filter parameters derived from these VCO settings for 720p:
	/*      p_BANDWIDTH="OPTIMIZED", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked,

                # VCO
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=13.5, #6.734, 7.2
                p_CLKFBOUT_MULT_F=10.0, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=clk_input_bufr, i_CLKFBIN=mmcm_fb_o, o_CLKFBOUT=mmcm_fb, */
	hdmi_in0_clocking_mmcm_write(0x18, 0x3e8); // lock register 1
	hdmi_in0_clocking_mmcm_write(0x19, (0x0 << 15) | (0x1c << 10) | 0x3001); // lock register 2
	hdmi_in0_clocking_mmcm_write(0x1A, (0x1 << 15) | (0x1c << 10) | 0x33e9); // lock register 3
	hdmi_in0_clocking_mmcm_write(0x4E, (0x1 << 15) | (0x3 << 11) | (0x1 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	hdmi_in0_clocking_mmcm_write(0x4F, (0x2 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8

#ifdef CSR_HDMI_IN0_CLOCKING_MMCM_DRDY_O_ADDR
	hdmi_in0_clocking_mmcm_write_o(0x14, 0x1000 |  (5<<6) | 5);  /* clkfbout_mult  = 10 */
	hdmi_in0_clocking_mmcm_write_o(0x15, 0);                     /* clkfbout_mult  = 10 (edge = 0) */
	hdmi_in0_clocking_mmcm_write_o(0x08, 0x1000 |  (5<<6) | 5);  /* clkout0_divide = 10 */
	hdmi_in0_clocking_mmcm_write_o(0x09, 0)     ;                /* clkout0_divide = 10 (edge = 0) */
	// clkout1 is not used
	hdmi_in0_clocking_mmcm_write_o(0x0c, 0x1000 |  (1<<6) | 1);  /* clkout2_divide = 2 */
	hdmi_in0_clocking_mmcm_write_o(0x0d, 0);                     /* clkout2_divide = 2 */

	// lock/filter parameters derived from these VCO settings for 1080p, low bandwidth:
	/*      p_BANDWIDTH="LOW", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked_o,

           # VCO
           p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=6.734,
           p_CLKFBOUT_MULT=10, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1, # PLL range is 800-1866 MHz, unlike MMCM which is 600-1440 MHz
           i_CLKIN1=mmcm_clk0,  # uncompensated delay for best phase match between master/slave
           i_CLKFBIN=mmcm_fb2_o, o_CLKFBOUT=mmcm_fb2_o, */
	hdmi_in0_clocking_mmcm_write_o(0x18, 0x3e8); // lock register 1
	hdmi_in0_clocking_mmcm_write_o(0x19, (0x0 << 15) | (0x1c << 10) | 0x3001); // lock register 2
	hdmi_in0_clocking_mmcm_write_o(0x1A, (0x1 << 15) | (0x1c << 10) | 0x33e9); // lock register 3
	// FiltReg1:   table[9]:0x0 (r):0x0 table[8:7]:0x1 (r):0x0 table[6]:0x0 (r):0x8
	hdmi_in0_clocking_mmcm_write_o(0x4E, (0x0 << 15) | (0x1 << 11) | (0x0 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	// FiltReg2:   table[5]:0x0 (r):0x0 table[4:3]:0x0 (r):0x0 table[2:1]:0x2 (r):0x0 table[0]:0x0 (r):0x8
	hdmi_in0_clocking_mmcm_write_o(0x4F, (0x0 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8
#endif
}

static void hdmi_in_0_config_120_240mhz(void) {
	hdmi_in0_clocking_mmcm_write(0x14, 0x1000 |  (2<<6) | 3);  /* clkfbout_mult  = 5 (2/3) */
	hdmi_in0_clocking_mmcm_write(0x15, 1 << 7);                /* clkfbout_mult  = 5 (edge = 1) */
	hdmi_in0_clocking_mmcm_write(0x08, 0x1000 |  (2<<6) | 3);  /* clkout0_divide = 5 (2/3) */
	hdmi_in0_clocking_mmcm_write(0x09, 1 << 7);                /* clkout0_divide = 5 (edge = 1) */
	hdmi_in0_clocking_mmcm_write(0x0a, 0x1000 |  (2<<6) | 2);  /* clkout1_divide = 4 */
	hdmi_in0_clocking_mmcm_write(0x0c, 0x1000 |  (0<<6) | 0);  /* clkout2_divide = 1 */
	hdmi_in0_clocking_mmcm_write(0x0d, (1<<6));                /* clkout2_divide = 1 */
	
	// lock/filter parameters derived from these VCO settings for 1080p, low bandwidth:
	/*      p_BANDWIDTH="OPTIMIZED", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked,

	                  # VCO
	  p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=6.734,
	  p_CLKFBOUT_MULT_F=10.0, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1,
	  i_CLKIN1=clk_input_bufr, i_CLKFBIN=mmcm_fb_o, o_CLKFBOUT=mmcm_fb, */
	hdmi_in0_clocking_mmcm_write(0x18, 0x3e8); // lock register 1
	hdmi_in0_clocking_mmcm_write(0x19, (0x0 << 15) | (0xe << 10) | 0x3801); // lock register 2
	hdmi_in0_clocking_mmcm_write(0x1A, (0x1 << 15) | (0xe << 10) | 0x3be9); // lock register 3
	hdmi_in0_clocking_mmcm_write(0x4E, (0x0 << 15) | (0x1 << 11) | (0x0 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	hdmi_in0_clocking_mmcm_write(0x4F, (0x3 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8

#ifdef CSR_HDMI_IN0_CLOCKING_MMCM_DRDY_O_ADDR   // PLLE2 demands to configure at x10 even at high frequency
	hdmi_in0_clocking_mmcm_write_o(0x14, 0x1000 |  (5<<6) | 5);  /* clkfbout_mult  = 10 */
	hdmi_in0_clocking_mmcm_write_o(0x15, 0);                     /* clkfbout_mult  = 10 (edge = 0) */
	hdmi_in0_clocking_mmcm_write_o(0x08, 0x1000 |  (5<<6) | 5);  /* clkout0_divide = 10 */
	hdmi_in0_clocking_mmcm_write_o(0x09, 0)     ;                /* clkout0_divide = 10 (edge = 0) */
	// clkout1 is not used
	hdmi_in0_clocking_mmcm_write_o(0x0c, 0x1000 |  (1<<6) | 1);  /* clkout2_divide = 2 */
	hdmi_in0_clocking_mmcm_write_o(0x0d, 0);                     /* clkout2_divide = 2 */

	// lock/filter parameters derived from these VCO settings for 1080p, low bandwidth:
	/*      p_BANDWIDTH="LOW", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked_o,

           # VCO
           p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=6.734,
           p_CLKFBOUT_MULT=10, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1, # PLL range is 800-1866 MHz, unlike MMCM which is 600-1440 MHz
           i_CLKIN1=mmcm_clk0,  # uncompensated delay for best phase match between master/slave
           i_CLKFBIN=mmcm_fb2_o, o_CLKFBOUT=mmcm_fb2_o, */
	hdmi_in0_clocking_mmcm_write_o(0x18, 0x3e8); // lock register 1
	hdmi_in0_clocking_mmcm_write_o(0x19, (0x0 << 15) | (0x1c << 10) | 0x3001); // lock register 2
	hdmi_in0_clocking_mmcm_write_o(0x1A, (0x1 << 15) | (0x1c << 10) | 0x33e9); // lock register 3
	// FiltReg1:   table[9]:0x0 (r):0x0 table[8:7]:0x1 (r):0x0 table[6]:0x0 (r):0x8
	hdmi_in0_clocking_mmcm_write_o(0x4E, (0x0 << 15) | (0x1 << 11) | (0x0 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	// FiltReg2:   table[5]:0x0 (r):0x0 table[4:3]:0x0 (r):0x0 table[2:1]:0x2 (r):0x0 table[0]:0x0 (r):0x8
	hdmi_in0_clocking_mmcm_write_o(0x4F, (0x0 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8
#endif
}
#endif

#ifdef CSR_HDMI_IN1_BASE
void hdmi_in1_clocking_mmcm_write(int adr, int data) {
  int timeout = 0;
	hdmi_in1_clocking_mmcm_adr_write(adr);
	hdmi_in1_clocking_mmcm_dat_w_write(data);
	hdmi_in1_clocking_mmcm_write_write(1);
	while(!hdmi_in1_clocking_mmcm_drdy_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in1_clocking_mmcm_write failed with adr %x, data %x\n", adr, data);
	}
}

int hdmi_in1_clocking_mmcm_read(int adr) {
  int timeout = 0;
	hdmi_in1_clocking_mmcm_adr_write(adr);
	hdmi_in1_clocking_mmcm_read_write(1);
	while(!hdmi_in1_clocking_mmcm_drdy_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in1_clocking_mmcm_read failed with adr %x\n", adr);
	}
	  
	return hdmi_in1_clocking_mmcm_dat_r_read();
}

#ifdef CSR_HDMI_IN1_CLOCKING_MMCM_DRDY_O_ADDR
void hdmi_in1_clocking_mmcm_write_o(int adr, int data) {
  int timeout = 0;
	hdmi_in1_clocking_mmcm_adr_write(adr);
	hdmi_in1_clocking_mmcm_dat_w_write(data);
	hdmi_in1_clocking_mmcm_write_o_write(1);
	while(!hdmi_in1_clocking_mmcm_drdy_o_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in1_clocking_mmcm_write_o failed with adr %x, data %x\n", adr, data);
	}
	  
}

int hdmi_in1_clocking_mmcm_read_o(int adr) {
  int timeout = 0;
	hdmi_in1_clocking_mmcm_adr_write(adr);
	hdmi_in1_clocking_mmcm_read_o_write(1);
	while(!hdmi_in1_clocking_mmcm_drdy_o_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("hdmi_in1_clocking_mmcm_read_o failed with adr %x\n", adr);
	}
	  
	return hdmi_in1_clocking_mmcm_dat_o_r_read();
}
#endif

static void hdmi_in_1_config_30_60mhz(void) {
	hdmi_in1_clocking_mmcm_write(0x14, 0x1000 | (10<<6) | 10); /* clkfbout_mult  = 20 */
	hdmi_in1_clocking_mmcm_write(0x08, 0x1000 | (10<<6) | 10); /* clkout0_divide = 20 */
	hdmi_in1_clocking_mmcm_write(0x0a, 0x1000 |  (8<<6) |  8); /* clkout1_divide = 16 */
	hdmi_in1_clocking_mmcm_write(0x0c, 0x1000 |  (2<<6) |  2); /* clkout2_divide =  4 */
	hdmi_in1_clocking_mmcm_write(0x0d, 0);                     /* clkout2_divide =  4 */
}

static void hdmi_in_1_config_60_120mhz(void) {
	hdmi_in1_clocking_mmcm_write(0x14, 0x1000 |  (5<<6) | 5); /* clkfbout_mult  = 10 */
	hdmi_in1_clocking_mmcm_write(0x08, 0x1000 |  (5<<6) | 5); /* clkout0_divide = 10 */
	hdmi_in1_clocking_mmcm_write(0x0a, 0x1000 |  (4<<6) | 4); /* clkout1_divide =  8 */
	hdmi_in1_clocking_mmcm_write(0x0c, 0x1000 |  (1<<6) | 1); /* clkout2_divide =  2 */
	hdmi_in1_clocking_mmcm_write(0x0d, 0);                    /* clkout2_divide =  2 */

	// lock/filter parameters derived from these VCO settings for 720p:
	/*      p_BANDWIDTH="OPTIMIZED", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked,

                # VCO
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=13.5, #6.734, 7.2
                p_CLKFBOUT_MULT_F=10.0, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=clk_input_bufr, i_CLKFBIN=mmcm_fb_o, o_CLKFBOUT=mmcm_fb, */
	hdmi_in1_clocking_mmcm_write(0x18, 0x3e8); // lock register 1
	hdmi_in1_clocking_mmcm_write(0x19, (0x0 << 15) | (0x1c << 10) | 0x3001); // lock register 2
	hdmi_in1_clocking_mmcm_write(0x1A, (0x1 << 15) | (0x1c << 10) | 0x33e9); // lock register 3
	hdmi_in1_clocking_mmcm_write(0x4E, (0x1 << 15) | (0x3 << 11) | (0x1 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	hdmi_in1_clocking_mmcm_write(0x4F, (0x2 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8
	
#ifdef CSR_HDMI_IN1_CLOCKING_MMCM_DRDY_O_ADDR
	hdmi_in1_clocking_mmcm_write_o(0x14, 0x1000 |  (2<<6) | 3);  /* clkfbout_mult  = 5 (2/3) */
	hdmi_in1_clocking_mmcm_write_o(0x15, 1 << 7);                /* clkfbout_mult  = 5 (edge = 1) */
	hdmi_in1_clocking_mmcm_write_o(0x08, 0x1000 |  (2<<6) | 3);  /* clkout0_divide = 5 (2/3) */
	hdmi_in1_clocking_mmcm_write_o(0x09, 1 << 7);                /* clkout0_divide = 5 (edge = 1) */
	// hdmi_in1_clocking_mmcm_write_o(0x0a, 0x1000 |  (2<<6) | 2);  /* clkout1_divide = 4 */
	hdmi_in1_clocking_mmcm_write_o(0x0c, 0x1000 |  (0<<6) | 0);  /* clkout2_divide = 1 */
	hdmi_in1_clocking_mmcm_write_o(0x0d, (1<<6));                /* clkout2_divide = 1 */

	// lock/filter parameters derived from these VCO settings for 1080p, low bandwidth:
	/*      p_BANDWIDTH="LOW", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked_o,

                # VCO
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=6.734,
                p_CLKFBOUT_MULT_F=5.0, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=mmcm_clk0,  # uncompesated delay for best phase match between master/slave
                i_CLKFBIN=mmcm_fb_o, o_CLKFBOUT=mmcm_fb_o,  */
	hdmi_in1_clocking_mmcm_write_o(0x18, 0x3e8); // lock register 1
	hdmi_in1_clocking_mmcm_write_o(0x19, (0x0 << 15) | (0x1c << 10) | 0x3001); // lock register 2
	hdmi_in1_clocking_mmcm_write_o(0x1A, (0x1 << 15) | (0x1c << 10) | 0x33e9); // lock register 3
	// FiltReg1:   table[9]:0x0 (r):0x0 table[8:7]:0x1 (r):0x0 table[6]:0x0 (r):0x8
	hdmi_in1_clocking_mmcm_write_o(0x4E, (0x0 << 15) | (0x1 << 11) | (0x0 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	// FiltReg2:   table[5]:0x0 (r):0x0 table[4:3]:0x0 (r):0x0 table[2:1]:0x2 (r):0x0 table[0]:0x0 (r):0x8
	hdmi_in1_clocking_mmcm_write_o(0x4F, (0x0 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8
#endif
}

static void hdmi_in_1_config_120_240mhz(void) {
	hdmi_in1_clocking_mmcm_write(0x14, 0x1000 |  (2<<6) | 3);  /* clkfbout_mult  = 5 (2/3) */
	hdmi_in1_clocking_mmcm_write(0x15, 1 << 7);                /* clkfbout_mult  = 5 (edge = 1) */
	hdmi_in1_clocking_mmcm_write(0x08, 0x1000 |  (2<<6) | 3);  /* clkout0_divide = 5 (2/3) */
	hdmi_in1_clocking_mmcm_write(0x09, 1 << 7);                /* clkout0_divide = 5 (edge = 1) */
	hdmi_in1_clocking_mmcm_write(0x0a, 0x1000 |  (2<<6) | 2);  /* clkout1_divide = 4 */
	hdmi_in1_clocking_mmcm_write(0x0c, 0x1000 |  (0<<6) | 0);  /* clkout2_divide = 1 */
	hdmi_in1_clocking_mmcm_write(0x0d, (1<<6));                /* clkout2_divide = 1 */
	
	// lock/filter parameters derived from these VCO settings for 1080p, low bandwidth:
	/*      p_BANDWIDTH="OPTIMIZED", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked,

	                  # VCO
	  p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=6.734,
	  p_CLKFBOUT_MULT_F=5.0, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1,
	  i_CLKIN1=clk_input_bufr, i_CLKFBIN=mmcm_fb_o, o_CLKFBOUT=mmcm_fb, */
	hdmi_in1_clocking_mmcm_write(0x18, 0x3e8); // lock register 1
	hdmi_in1_clocking_mmcm_write(0x19, (0x0 << 15) | (0xe << 10) | 0x3801); // lock register 2
	hdmi_in1_clocking_mmcm_write(0x1A, (0x1 << 15) | (0xe << 10) | 0x3be9); // lock register 3
	hdmi_in1_clocking_mmcm_write(0x4E, (0x0 << 15) | (0x1 << 11) | (0x0 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	hdmi_in1_clocking_mmcm_write(0x4F, (0x3 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8

#ifdef CSR_HDMI_IN1_CLOCKING_MMCM_DRDY_O_ADDR
	hdmi_in1_clocking_mmcm_write_o(0x14, 0x1000 |  (5<<6) | 5);  /* clkfbout_mult  = 10 */
	hdmi_in1_clocking_mmcm_write_o(0x15, 0);                     /* clkfbout_mult  = 10 (edge = 0) */
	hdmi_in1_clocking_mmcm_write_o(0x08, 0x1000 |  (5<<6) | 5);  /* clkout0_divide = 10 */
	hdmi_in1_clocking_mmcm_write_o(0x09, 0)     ;                /* clkout0_divide = 10 (edge = 0) */
	// clkout1 is not used
	hdmi_in1_clocking_mmcm_write_o(0x0c, 0x1000 |  (1<<6) | 1);  /* clkout2_divide = 2 */
	hdmi_in1_clocking_mmcm_write_o(0x0d, 0);                     /* clkout2_divide = 2 */

	// lock/filter parameters derived from these VCO settings for 1080p, low bandwidth:
	/*      p_BANDWIDTH="LOW", i_RST=self._mmcm_reset.storage, o_LOCKED=mmcm_locked_o,

           # VCO
           p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=6.734,
           p_CLKFBOUT_MULT=10, p_CLKFBOUT_PHASE=0.000, p_DIVCLK_DIVIDE=1, # PLL range is 800-1866 MHz, unlike MMCM which is 600-1440 MHz
           i_CLKIN1=mmcm_clk0,  # uncompensated delay for best phase match between master/slave
           i_CLKFBIN=mmcm_fb2_o, o_CLKFBOUT=mmcm_fb2_o, */
	hdmi_in1_clocking_mmcm_write_o(0x18, 0x3e8); // lock register 1
	hdmi_in1_clocking_mmcm_write_o(0x19, (0x0 << 15) | (0x1c << 10) | 0x3001); // lock register 2
	hdmi_in1_clocking_mmcm_write_o(0x1A, (0x1 << 15) | (0x1c << 10) | 0x33e9); // lock register 3
	// FiltReg1:   table[9]:0x0 (r):0x0 table[8:7]:0x1 (r):0x0 table[6]:0x0 (r):0x8
	hdmi_in1_clocking_mmcm_write_o(0x4E, (0x0 << 15) | (0x1 << 11) | (0x0 << 8) | 0x8); // filter register 1, reserved[7:0] is 0x8
	// FiltReg2:   table[5]:0x0 (r):0x0 table[4:3]:0x0 (r):0x0 table[2:1]:0x2 (r):0x0 table[0]:0x0 (r):0x8
	hdmi_in1_clocking_mmcm_write_o(0x4F, (0x0 << 11) | (0x2 << 7)  | (0x0 << 4) | 0x8); // filter register 2, reserved[7:0] is 0x8
#endif
}
#endif

/*
  "table" values are generated by doing a direct dump of the mmcm/plle2 values and recording them
  without going to the intermediate decoded values, which is error-prone during the recoding process...
 */
#define MTE 46  // MCM table entries
void hdmi_in_0_config_120_240mhz_table() {
  // according to xap888, register 0x28 should be all high when using DRP, so manually edit dumps accordingly
  
  // hdmi0 MMCM  (bandwidth = LOW)
  int hdmi0_mmcm_low[MTE] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x1083, 0xa, 0x1082, 0xb, 0x0, 0xc, 0x1041,
			     0xd, 0x40, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40,
			     0x12, 0x41, 0x13, 0x40, 0x16, 0x1041, 0x14, 0x1083, 0x15, 0x80,
			     0x18, 0x3e8, 0x19, 0x3801, 0x1a, 0xbbe9, 0x4e, 0x808, 0x4f, 0x1900};
  
  // hdmi0 MMCM  (bandwidth = OPTIMIZED/HIGH)
  int hdmi0_mmcm_opt[MTE] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x1083, 0xa, 0x1082, 0xb, 0x0, 0xc, 0x1041,
			     0xd, 0x40, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40,
			     0x12, 0x41, 0x13, 0x40, 0x16, 0x1041, 0x14, 0x1083, 0x15, 0x80,
			     0x18, 0x3e8, 0x19, 0x3801, 0x1a, 0xbbe9, 0x4e, 0x9108, 0x4f, 0x1900};

  // hdmi0 PLLE (bandwidth = LOW)
  int hdmi0_plle[46] = {0x28, 0xffff, 0x9, 0x0, 0x8, 0x1145, 0xa, 0x41, 0xb, 0x40, 0xc, 0x1041, 0xd, 0x0, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40, 0x12, 0x0, 0x13, 0x0, 0x16, 0x1041, 0x14, 0x1145, 0x15, 0x0, 0x18, 0x3e8, 0x19, 0x7001, 0x1a, 0xf3e9, 0x4e, 0x808, 0x4f, 0x100};

  printf("setting optimized bandwdith on hdmi in 0\n");
  int i;
  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in0_clocking_mmcm_write(hdmi0_mmcm_opt[i], hdmi0_mmcm_opt[i+1]);
  }

  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in0_clocking_mmcm_write_o(hdmi0_plle[i], hdmi0_plle[i+1]);
  }
}

void hdmi_in_0_config_60_120mhz_table() {
  // hdmi0 MMCM  (bandwidth = OPTIMIZED/HIGH)
  int hdmi0_mmcm_opt[MTE] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x11c8, 0xa, 0x1186, 0xb, 0x0, 0xc, 0x1042, 0xd, 0x80, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40, 0x12, 0x41, 0x13, 0x40, 0x16, 0x1041, 0x14, 0x11c8, 0x15, 0x80, 0x18, 0x28a, 0x19, 0x7c01, 0x1a, 0xffe9, 0x4e, 0x9908, 0x4f, 0x8100};
  
  // hdmi0 PLLE (bandwidth = HIGH) high reduces output jitter, low maximizes input jitter tolerance
  int hdmi0_plle[MTE] = {0x28, 0xffff, 0x9, 0x0, 0x8, 0x128a, 0xa, 0x41, 0xb, 0x40, 0xc, 0x1082, 0xd, 0x0, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40, 0x12, 0x0, 0x13, 0x0, 0x16, 0x1041, 0x14, 0x128a, 0x15, 0x0, 0x18, 0x1f4, 0x19, 0x7c01, 0x1a, 0xffe9, 0x4e, 0x1908, 0x4f, 0x1800};

  int i;
  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in0_clocking_mmcm_write(hdmi0_mmcm_opt[i], hdmi0_mmcm_opt[i+1]);
  }

  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in0_clocking_mmcm_write_o(hdmi0_plle[i], hdmi0_plle[i+1]);
  }
}

void hdmi_in_1_config_120_240mhz_table() {
  // hdmi1 MMCM
  int hdmi1_mmcm[MTE] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x1083, 0xa, 0x1082, 0xb, 0x0, 0xc, 0x1041, 0xd, 0x40, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40, 0x12, 0x41, 0x13, 0x40, 0x16, 0x1041, 0x14, 0x1083, 0x15, 0x80, 0x18, 0x3e8, 0x19, 0x3801, 0x1a, 0xbbe9, 0x4e, 0x9108, 0x4f, 0x1900};

  int i;
  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in1_clocking_mmcm_write(hdmi1_mmcm[i], hdmi1_mmcm[i+1]);
  }
}

void hdmi_in_1_config_60_120mhz_table() {
  // hdmi1 MMCM
  int hdmi1_mmcm[46] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x11c8, 0xa, 0x1186, 0xb, 0x0, 0xc, 0x1042, 0xd, 0x80, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40, 0x12, 0x41, 0x13, 0x40, 0x16, 0x1041, 0x14, 0x11c8, 0x15, 0x80, 0x18, 0x28a, 0x19, 0x7c01, 0x1a, 0xffe9, 0x4e, 0x9908, 0x4f, 0x8100};

  int i;
  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in1_clocking_mmcm_write(hdmi1_mmcm[i], hdmi1_mmcm[i+1]);
  }
}

void mmcm_config_for_clock(int freq)
{
	/*
	 * FIXME: we also need to configure phase detector
	 */
  //   mmcm_dump(); // used to extract params if we make changes to VCOs
#ifdef CSR_HDMI_IN0_BASE
	hdmi_in0_clocking_mmcm_reset_write(1);
	if(freq < 3000)
		printf("Frequency too low for input MMCMs\r\n");
	else if(freq < 6000)
		hdmi_in_0_config_30_60mhz();
	else if(freq < 12000)
		hdmi_in_0_config_60_120mhz_table();
	else if(freq < 24000)
	        hdmi_in_0_config_120_240mhz_table();
	else
		printf("Frequency too high for input MMCMs\r\n");
	hdmi_in0_clocking_mmcm_reset_write(0);
#endif

#ifdef CSR_HDMI_IN1_BASE
	hdmi_in1_clocking_mmcm_reset_write(1);
	if(freq < 3000)
		printf("Frequency too low for input MMCMs\r\n");
	else if(freq < 6000)
		hdmi_in_1_config_30_60mhz();
	else if(freq < 12000)
		hdmi_in_1_config_60_120mhz_table();
	else if(freq < 24000)
		hdmi_in_1_config_120_240mhz_table();
	else
		printf("Frequency too high for input MMCMs\r\n");
	hdmi_in1_clocking_mmcm_reset_write(0);
#endif
}


void mmcm_decode_clkreg1(unsigned int data) {
  printf( "  phase mux:0x%x", (data >> 13) & 0x7 );
  printf( " (r):0x%x", (data >> 12) & 0x1 );
  printf( " high time:0x%x", (data >> 6) & 0x3F );
  printf( " low time:0x%x", (data >> 0) & 0x3F );
}

void mmcm_decode_clkreg2(unsigned int data) {
  printf( "  both:" );
  printf( " mx:0x%x", (data >> 8) & 0x3 );
  printf( " edge:0x%x", (data >> 7) & 0x1 );
  printf( " no count:0x%x", (data >> 6) & 0x1 );
  printf( " delay time:0x%x | ", (data >> 0) & 0x3F );

  printf( "  int:" );
  printf( " (r):0x%x", (data >> 15) & 0x1 );
  printf( " frac:0x%x", (data >> 12) & 0x7 );
  printf( " frac_en:0x%x", (data >> 11) & 0x1 );
  printf( " frac_wf_r:0x%x | ", (data >> 10) & 0x1 );
  
  printf( "  frac:" );
  printf( " (r):0x%x", (data >> 14) & 0x3 );
  printf( " phase_mux_f_clkout0:0x%x", (data >> 11) & 0x7 );
  printf( " frac_wf_f_clkout0:0x%x\n", (data >> 10) & 0x1 );
}

void mmcm_decode_divreg(unsigned int data) {
  printf( "  (r):0x%x", (data >> 14) & 0x3 );
  printf( " edge:0x%x", (data >> 13) & 0x1 );
  printf( " no count:0x%x", (data >> 12) & 0x1 );
  printf( " high time:0x%x", (data >> 6) & 0x3f );
  printf( " low time:0x%x\n", (data >> 0) & 0x3f );
}

void mmcm_decode_lockreg1(unsigned int data) {
  printf( "  (r):0x%x", (data >> 10) & 0x3f );
  printf( " lktable[29:0]:0x%x\n", (data >> 0) & 0x3FF );
}

void mmcm_decode_lockreg2(unsigned int data) {
  printf( "  (r):0x%x", (data >> 15) & 0x1 );
  printf( " lktable[34:30]:0x%x", (data >> 10) & 0x1F );
  printf( " lktable[9:0]:0x%x\n", (data >> 0) & 0x3FFF );
}

void mmcm_decode_lockreg3(unsigned int data) {
  printf( "  (r):0x%x", (data >> 15) & 0x1 );
  printf( " lktable[39:35]:0x%x", (data >> 10) & 0x1F );
  printf( " lktable[19:10]:0x%x\n", (data >> 0) & 0x3FFF );
}

void mmcm_decode_filtreg1(unsigned int data) {
  printf( "  table[9]:0x%x", (data >> 15) & 0x1 );
  printf( " (r):0x%x", (data >> 13) & 0x3 );
  printf( " table[8:7]:0x%x", (data >> 11) & 0x3 );
  printf( " (r):0x%x", (data >> 9) & 0x3 );
  printf( " table[6]:0x%x", (data >> 8) & 0x1 );
  printf( " (r):0x%x\n", (data >> 0) & 0xFF );
}

void mmcm_decode_filtreg2(unsigned int data) {
  printf( "  table[5]:0x%x", (data >> 15) & 0x1 );
  printf( " (r):0x%x", (data >> 13) & 0x3 );
  printf( " table[4:3]:0x%x", (data >> 11) & 0x3 );
  printf( " (r):0x%x", (data >> 9) & 0x3 );
  printf( " table[2:1]:0x%x", (data >> 7) & 0x3 );
  printf( " (r):0x%x", (data >> 5) & 0x3 );
  printf( " table[0]:0x%x", (data >> 4) & 0x1 );
  printf( " (r):0x%x\n", (data >> 5) & 0xF );
}

void mmcm_decode_power7(unsigned int data) {
  printf( "  power (must be high):0x%x\n", data & 0xFFFF );
}

void mmcm_decode_reg(unsigned int adr, unsigned int data) {

  switch(adr) {
  case 0x6:
    printf( "\nCLKOUT5 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0x8:
    printf( "\nCLKOUT0 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0xA:
    printf( "\nCLKOUT1 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0xC:
    printf( "\nCLKOUT2 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0xE:
    printf( "\nCLKOUT3 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0x10:
    printf( "\nCLKOUT4 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0x12:
    printf( "\nCLKOUT6 ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
  case 0x14:
    printf( "\nCLKFBOUT ClkReg1: " );
    mmcm_decode_clkreg1(data);
    break;
    
  case 0x7:
    printf( "\nCLKOUT5 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0x9:
    printf( "\nCLKOUT0 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0xB:
    printf( "\nCLKOUT1 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0xD:
    printf( "\nCLKOUT2 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0xF:
    printf( "\nCLKOUT3 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0x11:
    printf( "\nCLKOUT4 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0x13:
    printf( "\nCLKOUT6 ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;
  case 0x15:
    printf( "\nCLKFBOUT ClkReg2: " );
    mmcm_decode_clkreg2(data);
    break;

  case 0x16:
    printf( "\nDivReg: " );
    mmcm_decode_divreg(data);
    break;

  case 0x18:
    printf( "\nLockReg1: " );
    mmcm_decode_lockreg1(data);
    break;

  case 0x19:
    printf( "\nLockReg2: " );
    mmcm_decode_lockreg2(data);
    break;

  case 0x1A:
    printf( "\nLockReg3: " );
    mmcm_decode_lockreg3(data);
    break;

  case 0x28:
    printf( "\nPowerReg 7 series: " );
    mmcm_decode_power7(data);
    break;

  case 0x4E:
    printf( "\nFiltReg1: " );
    mmcm_decode_filtreg1(data);
    break;

  case 0x4F:
    printf( "\nFiltReg2: " );
    mmcm_decode_filtreg2(data);
    break;

  default:
    if( data != 0 )
      printf( " %04x(r)", data );
    else
      printf( " 0(r)", data );
  }
}
#ifdef CSR_CRG_BASE
void crg_mmcm_write(int adr, int data) {
  int timeout = 0;
	crg_mmcm_adr_write(adr);
	crg_mmcm_dat_w_write(data);
	crg_mmcm_write_write(1);
	while(!crg_mmcm_drdy_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("crg_mmcm_write failed with adr %x, data %x\n", adr, data);
	}
}

int crg_mmcm_read(int adr) {
  int timeout = 0;
	crg_mmcm_adr_write(adr);
	crg_mmcm_read_write(1);
	while(!crg_mmcm_drdy_read() && timeout < MMCM_TIMEOUT)
	  timeout++;
	if( timeout >= MMCM_TIMEOUT ) {
	  printf("crg_mmcm_read failed with adr %x\n", adr);
	}

	return crg_mmcm_dat_r_read();
}
#endif

#define S7_MMCM_MAP_LEN  23
// map order comes from xapp888 -- no explanation in docs for why the order is necessary, but it seems important
static int addr_map[S7_MMCM_MAP_LEN] = {0x28, 0x9, 0x8, 0xa, 0xb, 0xc, 0xd, 0xe, 0xf, 0x10, 0x11, 0x6, 0x7,
					0x12, 0x13, 0x16, 0x14, 0x15, 0x18, 0x19, 0x1a, 0x4e, 0x4f};

void mmcm_dump_code(void) {
  int i;

#ifdef CSR_CRG_BASE
  printf( "// CRG MMCM\n" );
  printf( "int crg_mmcm[%d] = {", S7_MMCM_MAP_LEN * 2 );
  for( i = 0; i < S7_MMCM_MAP_LEN; i++ ) {
    if( addr_map[i] == 0x28 )  // this state substitutes to all 1's for DRP to work
      printf( "0x28, 0xffff" );
    else
      printf( "0x%x, 0x%x", addr_map[i], crg_mmcm_read(addr_map[i]) );
    if( i < S7_MMCM_MAP_LEN - 1 )
      printf( ", " );
  }
  printf( "};\n" );
#endif
	
  printf( "// hdmi0 MMCM\n" );
  printf( "int hdmi0_mmcm[%d] = {", S7_MMCM_MAP_LEN * 2 );
  for( i = 0; i < S7_MMCM_MAP_LEN; i++ ) {
    if( addr_map[i] == 0x28 )  // this state substitutes to all 1's for DRP to work
      printf( "0x28, 0xffff" );
    else
      printf( "0x%x, 0x%x", addr_map[i], hdmi_in0_clocking_mmcm_read(addr_map[i]) );
    if( i < S7_MMCM_MAP_LEN - 1 )
      printf( ", " );
  }
  printf( "};\n" );
  
  printf( "// hdmi0 PLLE\n" );
  printf( "int hdmi0_plle[%d] = {", S7_MMCM_MAP_LEN * 2 );
  for( i = 0; i < S7_MMCM_MAP_LEN; i++ ) {
    if( addr_map[i] == 0x28 )  // this state substitutes to all 1's for DRP to work
      printf( "0x28, 0xffff" );
    else
      printf( "0x%x, 0x%x", addr_map[i], hdmi_in0_clocking_mmcm_read_o(addr_map[i]) );
    if( i < S7_MMCM_MAP_LEN - 1 )
      printf( ", " );
  }
  printf( "};\n" );
  
  printf( "// hdmi1 MMCM\n" );
  printf( "int hdmi1_mmcm[%d] = {", S7_MMCM_MAP_LEN * 2 );
  for( i = 0; i < S7_MMCM_MAP_LEN; i++ ) {
    if( addr_map[i] == 0x28 )  // this state substitutes to all 1's for DRP to work
      printf( "0x28, 0xffff" );
    else
      printf( "0x%x, 0x%x", addr_map[i], hdmi_in1_clocking_mmcm_read(addr_map[i]) );
    if( i < S7_MMCM_MAP_LEN - 1 )
      printf( ", " );
  }
  printf( "};\n" );

#if 0    // not configured on NeTV2
  printf( "// hdmi1 PLLE\n" );
  printf( "int hdmi1_plle[%d] = {", S7_MMCM_MAP_LEN * 2 );
  for( i = 0; i < S7_MMCM_MAP_LEN; i++ ) {
    if( addr_map[i] == 0x28 )  // this state substitutes to all 1's for DRP to work
      printf( "0x28, 0xffff" );
    else
      printf( "0x%x, 0x%x", addr_map[i], hdmi_in1_clocking_mmcm_read_o(addr_map[i]) );
    if( i < S7_MMCM_MAP_LEN - 1 )
      printf( ", " );
  }
  printf( "};\n" );
#endif
}

void mmcm_dump(void)
{
	int i;

#ifdef CSR_HDMI_OUT0_BASE
	printf("framebuffer MMCM:\r\n");
	for(i=0;i<128;i++)
		printf("%04x ", hdmi_out0_mmcm_read(i));
	printf("\r\n");
#endif
#ifdef CSR_HDMI_IN0_BASE
	printf("dvisampler 0 MMCM:\r\n");
	for(i=0;i<128;i++)
	  mmcm_decode_reg(i, hdmi_in0_clocking_mmcm_read(i));
	printf("\r\n");
#ifdef CSR_HDMI_IN0_CLOCKING_MMCM_DRDY_O_ADDR
	printf("=====================================================\r\n");
	printf("output 0 PLLE2:\r\n");
	for(i=0;i<128;i++)
	  mmcm_decode_reg(i, hdmi_in0_clocking_mmcm_read_o(i));
	printf("\r\n");
#endif
#endif

#ifdef CSR_HDMI_IN1_BASE
	printf("dvisampler 1 MMCM:\r\n");
	for(i=0;i<128;i++)
	  mmcm_decode_reg(i, hdmi_in1_clocking_mmcm_read(i));
	printf("\r\n");
#ifdef CSR_HDMI_IN1_CLOCKING_MMCM_DRDY_O_ADDR
	printf("=====================================================\r\n");
	printf("output 1 PLLE2:\r\n");
	for(i=0;i<128;i++)
	  mmcm_decode_reg(i, hdmi_in1_clocking_mmcm_read_o(i));
	printf("\r\n");
#endif
#endif

}


// This function takes the divide value and the bandwidth setting of the MMCM
//  and outputs the digital filter settings necessary.
//  "divide" is ironically, the CLK_FBOUT_MULT number that goes into the PLL. 
int mmcm_filter_lookup( int divide, int bandwidth ) {
  int filter_lookup;
  
  // CP_RES_LFHF
  int lookup_low[64] = {188, 188, 188, 188, 156, 172, 180, 140,
			148, 148, 164, 184, 184, 184, 184, 132,
			132, 132, 152, 152, 152, 152, 152, 152,
			152, 168, 168, 168, 168, 168, 176, 176,
			176, 176, 176, 176, 176, 176, 176, 176,
			176, 176, 176, 176, 176, 176, 176, 136,
			136, 136, 136, 136, 136, 136, 136, 136,
			136, 136, 136, 136, 136, 136, 136, 136};


  // CP_RES_LFHF
  int lookup_high[64] = {188, 316, 364, 476, 860, 940, 948, 972,
			 916, 980, 996, 836, 996, 996, 996, 996,
			 980, 980, 772, 772, 772, 368, 368, 368,
			 368, 208, 208, 208, 208, 208, 208, 208,
			 208, 208, 208, 208, 208, 208, 208, 208,
			 208, 160, 160, 160, 160, 160, 452, 452,
			 304, 304, 304, 304, 388, 388, 344, 344,
			 344, 144, 144, 144, 144, 296, 240, 240};

  if( bandwidth == 0 ) {
    // Set lookup_entry with the explicit bits from lookup with a part select
    // Low Bandwidth
    filter_lookup = lookup_low[ 64 - divide ];
  } else {
    filter_lookup = lookup_high[ 64 - divide ];
  }

  return filter_lookup;
}

int lock_bit_4e( int digital_filt, int prev_val ) {
  return  (0x66FF & prev_val) |
    ((digital_filt & (1 << 9)) >> 9) << 15 |
    ((digital_filt & (3 << 7)) >> 7) << 11 |
    ((digital_filt & (1 << 6)) >> 6) << 8;
}

int lock_bit_4f( int digital_filt, int prev_val ) {
  return (0x666F & prev_val) |
    ((digital_filt & (1 << 5)) >> 5) << 15 |
    ((digital_filt & (3 << 3)) >> 3) << 11 |
    ((digital_filt & (3 << 1)) >> 1) << 7 |
    ((digital_filt & (1 << 0)) >> 0) << 4;
}

void set_mmcm0_filt( int mult, int bw ) {
  int filter_val;
  int prev_val;
  int new_val;
  int hdmi0_mmcm_opt[MTE] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x1083, 0xa, 0x1082, 0xb, 0x0, 0xc, 0x1041,
			     0xd, 0x40, 0xe, 0x41, 0xf, 0x40, 0x10, 0x41, 0x11, 0x40, 0x6, 0x41, 0x7, 0x40,
			     0x12, 0x41, 0x13, 0x40, 0x16, 0x1041, 0x14, 0x1083, 0x15, 0x80,
			     0x18, 0x3e8, 0x19, 0x3801, 0x1a, 0xbbe9, 0x4e, 0x9108, 0x4f, 0x1900};
  
  if( (mult > 64) || (mult < 1) ) {
    printf( "mmcm0_filt: invalid mult %d\n", mult );
    return;
  }

  filter_val = mmcm_filter_lookup( mult, bw > 0 ? 1 : 0 );

  printf( "filter_val: %x\n", filter_val );
  prev_val = hdmi_in0_clocking_mmcm_read( 0x4e );
  printf( "mmcm0_filt: %04x was in 0x4e\n", prev_val );
  new_val = lock_bit_4e( filter_val, prev_val );
  printf( "mmcm0_filt: writing %04x to 0x4e\n", new_val );
  hdmi0_mmcm_opt[43] = new_val;


  prev_val = hdmi_in0_clocking_mmcm_read( 0x4f );
  printf( "mmcm0_filt: %04x was in 0x4f\n", prev_val );
  new_val = lock_bit_4f( filter_val, prev_val );
  printf( "mmcm0_filt: writing %04x to 0x4f\n", new_val );
  hdmi_in0_clocking_mmcm_write(0x4f, new_val);
  hdmi0_mmcm_opt[45] = new_val;

  // write the whole table in anew
  int i;
  for( i = 0; i < MTE; i += 2 ) {
    hdmi_in0_clocking_mmcm_write(hdmi0_mmcm_opt[i], hdmi0_mmcm_opt[i+1]);
  }
 
}
