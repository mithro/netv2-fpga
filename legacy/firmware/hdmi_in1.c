#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <irq.h>
#include <uart.h>
#include <time.h>
#include <system.h>
#include <generated/csr.h>
#include <generated/mem.h>
#include "flags.h"

#ifdef CSR_HDMI_IN1_BASE

#include "hdmi_in1.h"

#ifdef IDELAYCTRL_CLOCK_FREQUENCY
static int idelay_freq = IDELAYCTRL_CLOCK_FREQUENCY;
#else
static int idelay_freq = 200000000; // default to 200 MHz
#endif
static int iodelay_tap_duration = 78;

int hdmi_in1_debug = 0;
int hdmi_in1_fb_index = 0;

#define FRAMEBUFFER_COUNT 2
#define FRAMEBUFFER_MASK (FRAMEBUFFER_COUNT - 1)

//#define HDMI_IN1_FRAMEBUFFERS_BASE (0x00000000 + 0x100000)
#define HDMI_IN1_FRAMEBUFFERS_BASE (0x06000000)
#define HDMI_IN1_FRAMEBUFFERS_SIZE (1920*1080*4)

//#define CLEAN_COMMUTATION
#define DEBUG

#define HDMI_IN1_PHASE_ADJUST_WER_THRESHOLD 1
#define HDMI_IN1_PHASE_ADJUST_WER_THRESHOLD_2 100000

#define HDMI_IN1_AUTO_CTL_DEFAULT   (0x6f)

#define HDMI_IN1_ROUNDING 3

unsigned int hdmi_in1_framebuffer_base(char n) {
	return HDMI_IN1_FRAMEBUFFERS_BASE + n*HDMI_IN1_FRAMEBUFFERS_SIZE;
}

#ifdef HDMI_IN1_INTERRUPT
static int hdmi_in1_fb_slot_indexes[2];
static int hdmi_in1_next_fb_index;
#endif

static int hdmi_in1_hres, hdmi_in1_vres;

extern void processor_update(void);

unsigned int isr_iter = 0;
extern volatile int cur_irq_mask;

#define SLOT1 1

static int hdmi_in1_compute_auto_bt_val(int bit_rate_value) {
  int del_mech = 1;
  int bt_val;
  int dcd_correct = 0;
  
  if(idelay_freq == 200000000) {
    if(bit_rate_value > 1984) { bt_val = 0x07 ; del_mech = 1 ; }
    else if (bit_rate_value > 1717) { bt_val = 0x08 ; del_mech = 1 ; }
    else if (bit_rate_value > 1514) { bt_val = 0x09 ; del_mech = 1 ; }
    else if (bit_rate_value > 1353) { bt_val = 0x0A ; del_mech = 1 ; }
    else if (bit_rate_value > 1224) { bt_val = 0x0B ; del_mech = 1 ; }
    else if (bit_rate_value > 1117) { bt_val = 0x0C ; del_mech = 1 ; }
    else if (bit_rate_value > 1027) { bt_val = 0x0D ; del_mech = 1 ; }
    else if (bit_rate_value > 951) { bt_val = 0x0E ; del_mech = 1 ; }
    else if (bit_rate_value > 885) { bt_val = 0x0F ; del_mech = 1 ; }
    else if (bit_rate_value > 828) { bt_val = 0x10 ; del_mech = 1 ; }
    else if (bit_rate_value > 778) { bt_val = 0x11 ; del_mech = 1 ; }
    else if (bit_rate_value > 733) { bt_val = 0x12 ; del_mech = 1 ; }
    else if (bit_rate_value > 694) { bt_val = 0x13 ; del_mech = 1 ; }
    else if (bit_rate_value > 658) { bt_val = 0x14 ; del_mech = 1 ; }
    else if (bit_rate_value > 626) { bt_val = 0x15 ; del_mech = 1 ; }
    else if (bit_rate_value > 597) { bt_val = 0x16 ; del_mech = 0 ; }
    else if (bit_rate_value > 570) { bt_val = 0x17 ; del_mech = 0 ; }
    else if (bit_rate_value > 546) { bt_val = 0x18 ; del_mech = 0 ; }
    else if (bit_rate_value > 524) { bt_val = 0x19 ; del_mech = 0 ; }
    else if (bit_rate_value > 503) { bt_val = 0x1A ; del_mech = 0 ; }
    else if (bit_rate_value > 484) { bt_val = 0x1B ; del_mech = 0 ; }
    else if (bit_rate_value > 466) { bt_val = 0x1C ; del_mech = 0 ; }
    else if (bit_rate_value > 450) { bt_val = 0x1D ; del_mech = 0 ; }
    else if (bit_rate_value > 435) { bt_val = 0x1E ; del_mech = 0 ; }
    else { bt_val = 0x1F ; del_mech = 0 ; }// min bit rate 420 Mbps
  } else if(idelay_freq == 300000000) {  
    if      ((bit_rate_value > 2030 && dcd_correct == 0) || (bit_rate_value > 1845 && dcd_correct == 1)) { bt_val = 0x0A ; del_mech = 1 ; }
    else if ((bit_rate_value > 1836 && dcd_correct == 0) || (bit_rate_value > 1669 && dcd_correct == 1)) { bt_val = 0x0B ; del_mech = 1 ; }
    else if ((bit_rate_value > 1675 && dcd_correct == 0) || (bit_rate_value > 1523 && dcd_correct == 1)) { bt_val = 0x0C ; del_mech = 1 ; }
    else if ((bit_rate_value > 1541 && dcd_correct == 0) || (bit_rate_value > 1401 && dcd_correct == 1)) { bt_val = 0x0D ; del_mech = 1 ; }
    else if ((bit_rate_value > 1426 && dcd_correct == 0) || (bit_rate_value > 1297 && dcd_correct == 1)) { bt_val = 0x0E ; del_mech = 1 ; }
    else if ((bit_rate_value > 1328 && dcd_correct == 0) || (bit_rate_value > 1207 && dcd_correct == 1)) { bt_val = 0x0F ; del_mech = 1 ; }
    else if ((bit_rate_value > 1242 && dcd_correct == 0) || (bit_rate_value > 1129 && dcd_correct == 1)) { bt_val = 0x10 ; del_mech = 1 ; }
    else if ((bit_rate_value > 1167 && dcd_correct == 0) || (bit_rate_value > 1061 && dcd_correct == 1)) { bt_val = 0x11 ; del_mech = 1 ; }
    else if ((bit_rate_value > 1100 && dcd_correct == 0) || (bit_rate_value > 999 && dcd_correct == 1)) { bt_val = 0x12 ; del_mech = 1 ; }
    else if ((bit_rate_value > 1040 && dcd_correct == 0) || (bit_rate_value > 946 && dcd_correct == 1)) { bt_val = 0x13 ; del_mech = 1 ; }
    else if ((bit_rate_value > 987 && dcd_correct == 0) || (bit_rate_value > 897 && dcd_correct == 1)) { bt_val = 0x14 ; del_mech = 1 ; }
    else if ((bit_rate_value > 939 && dcd_correct == 0) || (bit_rate_value > 853 && dcd_correct == 1)) { bt_val = 0x15 ; del_mech = 1 ; }
    else if ((bit_rate_value > 895 && dcd_correct == 0) || (bit_rate_value > 814 && dcd_correct == 1)) { bt_val = 0x16 ; del_mech = 0 ; }
    else if ((bit_rate_value > 855 && dcd_correct == 0) || (bit_rate_value > 777 && dcd_correct == 1)) { bt_val = 0x17 ; del_mech = 0 ; }
    else if ((bit_rate_value > 819 && dcd_correct == 0) || (bit_rate_value > 744 && dcd_correct == 1)) { bt_val = 0x18 ; del_mech = 0 ; }
    else if ((bit_rate_value > 785 && dcd_correct == 0) || (bit_rate_value > 714 && dcd_correct == 1)) { bt_val = 0x19 ; del_mech = 0 ; }
    else if ((bit_rate_value > 754 && dcd_correct == 0) || (bit_rate_value > 686 && dcd_correct == 1)) { bt_val = 0x1A ; del_mech = 0 ; }
    else if ((bit_rate_value > 726 && dcd_correct == 0) || (bit_rate_value > 660 && dcd_correct == 1)) { bt_val = 0x1B ; del_mech = 0 ; }
    else if ((bit_rate_value > 700 && dcd_correct == 0) || (bit_rate_value > 636 && dcd_correct == 1)) { bt_val = 0x1C ; del_mech = 0 ; }
    else if ((bit_rate_value > 675 && dcd_correct == 0) || (bit_rate_value > 614 && dcd_correct == 1)) { bt_val = 0x1D ; del_mech = 0 ; }
    else if ((bit_rate_value > 652 && dcd_correct == 0) || (bit_rate_value > 593 && dcd_correct == 1)) { bt_val = 0x1E ; del_mech = 0 ; }
    else { bt_val = 0x1F ;   del_mech = 0 ; }// min bit rate 631 Mbps
  } else if(idelay_freq == 400000000) {
    // original heuristic
    bt_val = (673 / iodelay_tap_duration) + HDMI_IN1_ROUNDING;
    del_mech = 1;
  } else {
    printf( "error: unhandled idelay_freq value, input link convergence will not work\n" );
  }

  if( del_mech == 0 ) {
    printf( "uhandled case: bitrate low enough that del_mech needs changing\n" );
  }
  return bt_val;
}

#ifdef HDMI_IN1_INTERRUPT
void hdmi_in1_isr(void)
{
	int fb_index = -1;
	int length;
	int expected_length;
	unsigned int address_min, address_max, address;
	unsigned int stat;

	stat = hdmi_in1_dma_ev_pending_read(); // see which slot is pending

	cur_irq_mask = irq_getmask();
	//	if( isr_iter % 29 == 0 )
	//	  printf( "%d.%d.%x.%x ", stat, isr_iter, cur_irq_mask, irq_pending() );
	isr_iter++;

	// check address base/bounds
	address_min = HDMI_IN1_FRAMEBUFFERS_BASE & 0x0fffffff;
	address_max = address_min + HDMI_IN1_FRAMEBUFFERS_SIZE*FRAMEBUFFER_COUNT;
	address = hdmi_in1_dma_slot0_address_read();
	if((hdmi_in1_dma_slot0_status_read() == DVISAMPLER_SLOT_PENDING)
		&& ((address < address_min) || (address > address_max)))
	  printf("hdmi_in1: slot0: stray DMA at %08x\r\n", address);

#if SLOT1
	address = hdmi_in1_dma_slot1_address_read();
	if((hdmi_in1_dma_slot1_status_read() == DVISAMPLER_SLOT_PENDING)
		&& ((address < address_min) || (address > address_max)))
	  printf("hdmi_in1: slot1: stray DMA at %08x\r\n", address);
#endif

#ifdef CLEAN_COMMUTATION
	if((hdmi_in1_resdetection_hres_read() != hdmi_in1_hres)
	  || (hdmi_in1_resdetection_vres_read() != hdmi_in1_vres)) {
		/* Dump frames until we get the expected resolution */
		if(hdmi_in1_dma_slot0_status_read() == DVISAMPLER_SLOT_PENDING) {
			hdmi_in1_dma_slot0_address_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[0]));
			hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_LOADED);
		}
#if SLOT1
		if(hdmi_in1_dma_slot1_status_read() == DVISAMPLER_SLOT_PENDING) {
			hdmi_in1_dma_slot1_address_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[1]));
			hdmi_in1_dma_slot1_status_write(DVISAMPLER_SLOT_LOADED);
		}
#endif
		return;
	}
#endif

	expected_length = hdmi_in1_hres*hdmi_in1_vres*4;
	
	if(hdmi_in1_dma_slot0_status_read() == DVISAMPLER_SLOT_PENDING) {
	  hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_EMPTY);
	  length = hdmi_in1_dma_slot0_address_read() - (hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[0]) & 0x0fffffff);
	  if(length == expected_length) {
	    fb_index = hdmi_in1_fb_slot_indexes[0];
	    hdmi_in1_fb_slot_indexes[0] = hdmi_in1_next_fb_index;
	    hdmi_in1_next_fb_index = (hdmi_in1_next_fb_index + 1) & FRAMEBUFFER_MASK;
	  } else {
#ifdef DEBUG
	    printf("hdmi_in1: slot0: unexpected frame length: %d\r\n", length);
#endif
	  }
	  
	  hdmi_in1_dma_slot0_address_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[0]));
	  hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_LOADED);
	  hdmi_in1_dma_ev_pending_write(1);   // clear the pending slot for this channel
	  
	} else if( stat & 0x1 ) {
	  hdmi_in1_dma_slot0_address_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[0]));
	  hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_LOADED);
	  hdmi_in1_dma_ev_pending_write(1);  
	  printf("hdmi_in1: slot0: interrupt event but DMA wasn't pending\n");
	}

#if SLOT1	
	if(hdmi_in1_dma_slot1_status_read() == DVISAMPLER_SLOT_PENDING) {
	  hdmi_in1_dma_slot1_status_write(DVISAMPLER_SLOT_EMPTY);
	  length = hdmi_in1_dma_slot1_address_read() - (hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[1]) & 0x0fffffff);
	  if(length == expected_length) {
	    fb_index = hdmi_in1_fb_slot_indexes[1];
	    hdmi_in1_fb_slot_indexes[1] = hdmi_in1_next_fb_index;
	    hdmi_in1_next_fb_index = (hdmi_in1_next_fb_index + 1) & FRAMEBUFFER_MASK;
	  } else {
#ifdef DEBUG
	    printf("hdmi_in1: slot1: unexpected frame length: %d\r\n", length);
#endif
	  }
	  hdmi_in1_dma_slot1_address_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[1]));
	  hdmi_in1_dma_slot1_status_write(DVISAMPLER_SLOT_LOADED);
	  hdmi_in1_dma_ev_pending_write(2);   // clear the pending slot for this channel
	  
	} else if( stat & 0x2 ) {
	  hdmi_in1_dma_slot1_address_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_slot_indexes[1]));
	  hdmi_in1_dma_slot1_status_write(DVISAMPLER_SLOT_LOADED);
	  hdmi_in1_dma_ev_pending_write(2);   // clear the pending slot for this channel
	  printf("hdmi_in1: slot1: interrupt event but DMA wasn't pending\n");
	}

	if(fb_index != -1) {
	  hdmi_in1_fb_index = fb_index;
	}
#endif
	
	// processor_update(); // this just does the below line
	hdmi_core_out0_initiator_base_write(hdmi_in1_framebuffer_base(hdmi_in1_fb_index));

}
#endif

static int hdmi_in1_connected;
static int hdmi_in1_locked;
int hdmi_in1_algorithm = 0;

void hdmi_in1_init_video(int hres, int vres)
{
	if( idelay_freq == 400000000 ) {
	  iodelay_tap_duration = 39;
	} else if( idelay_freq == 300000000 ) {
	  iodelay_tap_duration = 52;
	} else {
	  iodelay_tap_duration = 78;
	}

	hdmi_in1_clocking_mmcm_reset_write(1);
	hdmi_in1_connected = hdmi_in1_locked = 0;
	hdmi_in1_hres = hres; hdmi_in1_vres = vres;

#ifdef  HDMI_IN1_INTERRUPT
	unsigned int mask;

	hdmi_in1_dma_frame_size_write(hres*vres*4);
	hdmi_in1_fb_slot_indexes[0] = 0;
	hdmi_in1_dma_slot0_address_write(hdmi_in1_framebuffer_base(0));
	hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_LOADED);

	hdmi_in1_fb_slot_indexes[1] = 1;
	hdmi_in1_dma_slot1_address_write(hdmi_in1_framebuffer_base(1));
	hdmi_in1_dma_slot1_status_write(DVISAMPLER_SLOT_LOADED);
	
	hdmi_in1_next_fb_index = 1;
	hdmi_in1_fb_index = 0;

	hdmi_in1_dma_ev_pending_write(hdmi_in1_dma_ev_pending_read());
	hdmi_in1_dma_ev_enable_write(0x1);
	mask = irq_getmask();
	mask |= 1 << HDMI_IN1_INTERRUPT;
	irq_setmask(mask);

#endif

#if 1
#ifdef CSR_HDMI_IN1_DATA0_CAP_EYE_BIT_TIME_ADDR
#if 0
	int bit_time = (673 / iodelay_tap_duration) + HDMI_IN1_ROUNDING;  // 18 if you should round up, not truncate
#else
	int bit_time = hdmi_in1_compute_auto_bt_val( 1450 );
#endif
	printf( "hdmi_in1: setting algo 2 eye time to %d IDELAY periods\n", bit_time );
	hdmi_in1_data0_cap_eye_bit_time_write(bit_time);
	hdmi_in1_data1_cap_eye_bit_time_write(bit_time);
	hdmi_in1_data2_cap_eye_bit_time_write(bit_time);

#if 0
	// empirically, this link does really well with variant 1 of algorithm 0; not sure why but seems quite robust
	// SHIP IT
	hdmi_in1_data0_cap_algorithm_write(1); // 1 is just delay criteria change, 2 is auto-delay machine
	hdmi_in1_data1_cap_algorithm_write(1);
	hdmi_in1_data2_cap_algorithm_write(1);
	hdmi_in1_algorithm = 0;
	hdmi_in1_data0_cap_auto_ctl_write(7);
	hdmi_in1_data1_cap_auto_ctl_write(7);
	hdmi_in1_data2_cap_auto_ctl_write(7);
#else
	hdmi_in1_data0_cap_algorithm_write(2); // 1 is just delay criteria change, 2 is auto-delay machine
	hdmi_in1_data1_cap_algorithm_write(2);
	hdmi_in1_data2_cap_algorithm_write(2);
	hdmi_in1_algorithm = 2;
	hdmi_in1_data0_cap_auto_ctl_write(HDMI_IN1_AUTO_CTL_DEFAULT);
	hdmi_in1_data1_cap_auto_ctl_write(HDMI_IN1_AUTO_CTL_DEFAULT);
	hdmi_in1_data2_cap_auto_ctl_write(HDMI_IN1_AUTO_CTL_DEFAULT);
#endif
#endif
#endif
	
	
}

void hdmi_in1_disable(void)
{
#ifdef HDMI_IN1_INTERRUPT
	unsigned int mask;

	mask = irq_getmask();
	mask &= ~(1 << HDMI_IN1_INTERRUPT);
	irq_setmask(mask);

	hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_EMPTY);
	hdmi_in1_dma_slot1_status_write(DVISAMPLER_SLOT_EMPTY);
#endif
	hdmi_in1_clocking_mmcm_reset_write(1);
}

void hdmi_in1_clear_framebuffers(void)
{
	int i;
	flush_l2_cache();

	volatile unsigned int *framebuffer = (unsigned int *)(MAIN_RAM_BASE + HDMI_IN1_FRAMEBUFFERS_BASE);
	for(i=0; i<(HDMI_IN1_FRAMEBUFFERS_SIZE*FRAMEBUFFER_COUNT)/4; i++) {
		framebuffer[i] = 0x80108010; /* black in YCbCr 4:2:2*/
	}
}

int hdmi_in1_d0, hdmi_in1_d1, hdmi_in1_d2;

void hdmi_in1_print_status(void)
{
	hdmi_in1_data0_wer_update_write(1);
	hdmi_in1_data1_wer_update_write(1);
	hdmi_in1_data2_wer_update_write(1);
	printf("hdmi_in1: ph:%4d(%2d/%2d)%02x %4d(%2d/%2d)%02x %4d(%2d/%2d)%02x // charsync:%d%d%d [%d %d %d] // eye:%08x %08x %08x // WER:%3d %3d %3d // chansync:%d // res:%dx%d\r\n",
	       hdmi_in1_d0, hdmi_in1_data0_cap_cntvalueout_m_read(), hdmi_in1_data0_cap_cntvalueout_s_read(), hdmi_in1_data0_cap_lateness_read(),
	       hdmi_in1_d1, hdmi_in1_data1_cap_cntvalueout_m_read(), hdmi_in1_data1_cap_cntvalueout_s_read(), hdmi_in1_data1_cap_lateness_read(),
	       hdmi_in1_d2, hdmi_in1_data2_cap_cntvalueout_m_read(), hdmi_in1_data2_cap_cntvalueout_s_read(), hdmi_in1_data2_cap_lateness_read(),
	        
		hdmi_in1_data0_charsync_char_synced_read(),
		hdmi_in1_data1_charsync_char_synced_read(),
		hdmi_in1_data2_charsync_char_synced_read(),
		hdmi_in1_data0_charsync_ctl_pos_read(),
		hdmi_in1_data1_charsync_ctl_pos_read(),
		hdmi_in1_data2_charsync_ctl_pos_read(),
	       hdmi_in1_data0_cap_eye_read(),
	       hdmi_in1_data1_cap_eye_read(),
	       hdmi_in1_data2_cap_eye_read(),
		hdmi_in1_data0_wer_value_read(),
		hdmi_in1_data1_wer_value_read(),
		hdmi_in1_data2_wer_value_read(),
		hdmi_in1_chansync_channels_synced_read(),
		hdmi_in1_resdetection_hres_read(),
		hdmi_in1_resdetection_vres_read());
}

static int hdmi_in1_eye[3];
static int hdmi_in1_phase_target;

void hdmi_in1_update_eye() {
  // increasing the delta between master and slave pushes the master farther from the transition point
  hdmi_in1_eye[0] = hdmi_in1_data0_cap_cntvalueout_s_read() - hdmi_in1_data0_cap_cntvalueout_m_read();
  hdmi_in1_eye[1] = hdmi_in1_data1_cap_cntvalueout_s_read() - hdmi_in1_data1_cap_cntvalueout_m_read();
  hdmi_in1_eye[2] = hdmi_in1_data2_cap_cntvalueout_s_read() - hdmi_in1_data2_cap_cntvalueout_m_read();
}

int hdmi_in1_calibrate_delays(int freq)
{
	int i, phase_detector_delay;

	if( hdmi_in1_algorithm == 0 ) {
	hdmi_in1_data0_cap_dly_ctl_write(DVISAMPLER_DELAY_RST);
	hdmi_in1_data1_cap_dly_ctl_write(DVISAMPLER_DELAY_RST);
	hdmi_in1_data2_cap_dly_ctl_write(DVISAMPLER_DELAY_RST);
	hdmi_in1_data0_cap_phase_reset_write(1);
	hdmi_in1_data1_cap_phase_reset_write(1);
	hdmi_in1_data2_cap_phase_reset_write(1);
	hdmi_in1_d0 = hdmi_in1_d1 = hdmi_in1_d2 = 0;

	/* preload slave phase detector idelay with 90° phase shift
	  (78 ps taps on 7-series) */
	// 148.5 pixclk * 10 = 1485MHz bitrate = 0.673ns window
	// 10e6/(2*freq*39) = 8 = 312 ps delay
	// TODO: VALIDATE /4 SETTING
	phase_detector_delay = 10000000/(4*freq*iodelay_tap_duration) + 1;
	printf("HDMI in1 calibrate delays @ %dMHz, %d taps\n", freq, phase_detector_delay);
	for(i=0; i<phase_detector_delay; i++) {
		hdmi_in1_data0_cap_dly_ctl_write(DVISAMPLER_DELAY_SLAVE_INC);
		hdmi_in1_data1_cap_dly_ctl_write(DVISAMPLER_DELAY_SLAVE_INC);
		hdmi_in1_data2_cap_dly_ctl_write(DVISAMPLER_DELAY_SLAVE_INC);
	}
	hdmi_in1_update_eye();
	}
	return 1;
}

// it doesn't make sense to let the delay controller wrap around
// you're trying to control the distance between master and slave,
// and 31 taps * 39ps = 2356 ps, but the bit period is 673ps @ 1080p
// so that's 3.5 bit periods per delay sweep; when the delay wraps around
// to zero on the slave, you end up trying to align to data that's several
// cycles old
void hdmi_in1_fixup_eye() {
  int wrap_amount;
  int i;
  int delay;

  int wrap_limit;

  wrap_limit = 673 / iodelay_tap_duration + 1;

  delay = hdmi_in1_data0_cap_cntvalueout_m_read();
  if( (delay > wrap_limit) && (delay != 31) ) {
    for (i=0; i < delay; i++) {
      hdmi_in1_data0_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_DEC |
				       DVISAMPLER_DELAY_SLAVE_DEC);
      hdmi_in1_d0--;
    }
  } else if( delay == 31 ) {
    for(i=0; i < (wrap_limit); i++ ) {
      hdmi_in1_data0_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_INC |
				       DVISAMPLER_DELAY_SLAVE_INC);
      hdmi_in1_d0++;
    }
  }

  delay = hdmi_in1_data1_cap_cntvalueout_m_read();
  if( (delay > wrap_limit) && (delay != 31) ) {
    for (i=0; i < delay; i++) {
      hdmi_in1_data1_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_DEC |
				       DVISAMPLER_DELAY_SLAVE_DEC);
      hdmi_in1_d1--;
    }
  } else if( delay == 31 ) {
    for(i=0; i < (wrap_limit); i++ ) {
      hdmi_in1_data1_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_INC |
				       DVISAMPLER_DELAY_SLAVE_INC);
      hdmi_in1_d1++;
    }
  }

  delay = hdmi_in1_data2_cap_cntvalueout_m_read();
  if( (delay > wrap_limit) && (delay != 31) ) {
    for (i=0; i < delay; i++) {
      hdmi_in1_data2_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_DEC |
				       DVISAMPLER_DELAY_SLAVE_DEC);
      hdmi_in1_d2--;
    }
  } else if( delay == 31 ) {
    for(i=0; i < (wrap_limit); i++ ) {
      hdmi_in1_data2_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_INC |
				       DVISAMPLER_DELAY_SLAVE_INC);
      hdmi_in1_d2++;
    }
  }
  
}

int hdmi_in1_adjust_phase(void)
{
	switch(hdmi_in1_data0_cap_phase_read()) {
		case DVISAMPLER_TOO_LATE:
			hdmi_in1_data0_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_DEC |
				                             DVISAMPLER_DELAY_SLAVE_DEC);
			hdmi_in1_d0--;
			hdmi_in1_data0_cap_phase_reset_write(1);
			break;
		case DVISAMPLER_TOO_EARLY:
			hdmi_in1_data0_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_INC |
				                             DVISAMPLER_DELAY_SLAVE_INC);
			hdmi_in1_d0++;
			hdmi_in1_data0_cap_phase_reset_write(1);
			break;
	}
	switch(hdmi_in1_data1_cap_phase_read()) {
		case DVISAMPLER_TOO_LATE:
			hdmi_in1_data1_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_DEC |
				                             DVISAMPLER_DELAY_SLAVE_DEC);
			hdmi_in1_d1--;
			hdmi_in1_data1_cap_phase_reset_write(1);
			break;
		case DVISAMPLER_TOO_EARLY:
			hdmi_in1_data1_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_INC |
				                             DVISAMPLER_DELAY_SLAVE_INC);
			hdmi_in1_d1++;
			hdmi_in1_data1_cap_phase_reset_write(1);
			break;
	}
	switch(hdmi_in1_data2_cap_phase_read()) {
		case DVISAMPLER_TOO_LATE:
			hdmi_in1_data2_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_DEC |
				                             DVISAMPLER_DELAY_SLAVE_DEC);
			hdmi_in1_d2--;
			hdmi_in1_data2_cap_phase_reset_write(1);
			break;
		case DVISAMPLER_TOO_EARLY:
			hdmi_in1_data2_cap_dly_ctl_write(DVISAMPLER_DELAY_MASTER_INC |
				                             DVISAMPLER_DELAY_SLAVE_INC);
			hdmi_in1_d2++;
			hdmi_in1_data2_cap_phase_reset_write(1);
			break;
	}
	
	hdmi_in1_fixup_eye();
	hdmi_in1_update_eye();
	
	return 1;
}

static void phase_delay(void) {
  volatile int i;
  for( i = 0; i < 10; i++ )
    ;
}

int hdmi_in1_init_phase(void)
{
	int o_d0, o_d1, o_d2;
	int i, j;

        if( hdmi_in1_algorithm == 0 ) { 
	for(i=0;i<100;i++) {
		o_d0 = hdmi_in1_d0;
		o_d1 = hdmi_in1_d1;
		o_d2 = hdmi_in1_d2;
		for(j=0;j<1000;j++) {
			if(!hdmi_in1_adjust_phase())
				return 0;
			phase_delay();
		}
		if((abs(hdmi_in1_d0 - o_d0) < 4) && (abs(hdmi_in1_d1 - o_d1) < 4) && (abs(hdmi_in1_d2 - o_d2) < 4))
			return 1;
	}
	}
	return 0;
}

int hdmi_in1_phase_startup(int freq)
{
	int ret;
	int attempts;

	attempts = 0;
	if( hdmi_in1_algorithm == 2 ) {
#if 0
	  int bit_time;
	  bit_time = 10000000/(freq*iodelay_tap_duration) + HDMI_IN1_ROUNDING; // need to round up on fractional to cover the whole bit time
#else
	int bit_time = hdmi_in1_compute_auto_bt_val( freq / 10 );
#endif
	  printf( "hdmi_in1: setting algo 2 eye time to %d IDELAY periods\n", bit_time );
	  hdmi_in1_data0_cap_eye_bit_time_write(bit_time);
	  hdmi_in1_data1_cap_eye_bit_time_write(bit_time);
	  hdmi_in1_data2_cap_eye_bit_time_write(bit_time);
	}

	if( hdmi_in1_algorithm == 0 ) {
	while(1) {
		attempts++;
		hdmi_in1_calibrate_delays(freq);
		if(hdmi_in1_debug)
			printf("hdmi_in1: delays calibrated\r\n");
		ret = hdmi_in1_init_phase();
		if(ret) {
			if(hdmi_in1_debug)
				printf("hdmi_in1: phase init OK\r\n");
			return 1;
		} else {
			printf("hdmi_in1: phase init failed\r\n");
			if(attempts > 3) {
				printf("hdmi_in1: giving up\r\n");
				hdmi_in1_calibrate_delays(freq);
				return 0;
			}
		}
	}
	}
}

static void hdmi_in1_check_overflow(void)
{
#ifdef HDMI_IN1_INTERRUPT
	if(hdmi_in1_frame_overflow_read()) {
		printf("hdmi_in1: FIFO overflow\r\n");
		hdmi_in1_frame_overflow_write(1);
	}
#endif
}

static int hdmi_in1_clocking_locked_filtered(void)
{
	static int lock_start_time;
	static int lock_status;

	if(hdmi_in1_clocking_locked_read()) {
		switch(lock_status) {
			case 0:
				elapsed(&lock_start_time, -1);
				lock_status = 1;
				break;
			case 1:
				if(elapsed(&lock_start_time, SYSTEM_CLOCK_FREQUENCY/4))
					lock_status = 2;
				break;
			case 2:
				return 1;
		}
	} else
		lock_status = 0;
	return 0;
}

static int hdmi_in1_get_wer(void){
	int wer = 0;
	wer += hdmi_in1_data0_wer_value_read();
	wer += hdmi_in1_data1_wer_value_read();
	wer += hdmi_in1_data2_wer_value_read();
	return wer;
} 

#if 0
unsigned int service_count = 0;
void service_dma(void) {
#if 0
  flush_cpu_icache();
  flush_cpu_dcache();
  if(hdmi_in1_dma_slot0_status_read() == DVISAMPLER_SLOT_PENDING) {
	  hdmi_in1_dma_frame_size_write(1920*1080*4);
	  hdmi_in1_dma_slot0_address_write(hdmi_in1_framebuffer_base(0));
	  hdmi_in1_dma_slot1_address_write(hdmi_in1_framebuffer_base(1));
	  printf( "slot0 %x s%d ", hdmi_in1_dma_slot0_address_read(), service_count++ );
	  //	  hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_LOADED);
	  hdmi_in1_dma_slot0_status_write(DVISAMPLER_SLOT_EMPTY);
	}
  flush_cpu_icache();
  flush_cpu_dcache();
#else

  // self-start
  if(hdmi_in1_dma_address_valid_read() == 0) {
    hdmi_in1_dma_address_valid_write(1);
  }

  // restart on vsync
  if(hdmi_in1_dma_dma_running_read() == 0 && hdmi_in1_dma_address_valid_read() == 1) {
    hdmi_in1_dma_dma_go_write(1);
    if( hdmi_in1_dma_last_count_reached_read() != (hdmi_in1_framebuffer_base(0) + 1920*1080*4) / 32 )
      printf( "DMA count err: last %x, %d ", hdmi_in1_dma_last_count_reached_read(), service_count++ );
  }
#endif
}
#endif

static int did_reset = 0;

void hdmi_in1_service(int freq)
{
	static int last_event;
	static int ticks_unconverged = 0;
	static int last_reset;

	if(elapsed(&last_reset, SYSTEM_CLOCK_FREQUENCY/32)) {
	  if( did_reset ) {
	    hdmi_in1_clocking_searchreset_write(0);
	    hdmi_in1_clocking_mmcm_reset_write(0);
	    did_reset--;
	  }
	}
	
	if(hdmi_in1_connected) {
	  if(!hdmi_in1_edid_hpd_notif_read()) {
	    if(hdmi_in1_debug)
	      printf("hdmi_in1: disconnected\r\n");
	    hdmi_in1_connected = 0;
	    hdmi_in1_locked = 0;
	    hdmi_in1_clocking_mmcm_reset_write(1);
	    //			hdmi_in1_clear_framebuffers();
	  } else {
	    if(hdmi_in1_locked) {
	      if(hdmi_in1_clocking_locked_filtered()) {
		//		service_dma();
		if(elapsed(&last_event, SYSTEM_CLOCK_FREQUENCY/8)) {
		  hdmi_in1_data0_wer_update_write(1);
		  hdmi_in1_data1_wer_update_write(1);
		  hdmi_in1_data2_wer_update_write(1);
		  
		  if(hdmi_in1_debug)
		    hdmi_in1_print_status();
		  
		  if(hdmi_in1_get_wer() >= HDMI_IN1_PHASE_ADJUST_WER_THRESHOLD) {
		    if( hdmi_in1_algorithm == 0 ) {
		      hdmi_in1_adjust_phase();
		      ticks_unconverged++;
		      if( ticks_unconverged > 40 ) { // enough iterations to sweep the space roughly twice
			ticks_unconverged = 0;
			printf("hdmi_in1: kick!\r\n");
			hdmi_in1_phase_startup(freq); // kick the link if it gets stuck in a loop for a few seconds
		      }
		    }
		  } else {
		    ticks_unconverged = 0;
		  }
		  
		  if(((hdmi_in1_get_wer() >= HDMI_IN1_PHASE_ADJUST_WER_THRESHOLD_2) ||
		      (hdmi_in1_resdetection_hres_read() != 1920) ||
		      (hdmi_in1_resdetection_vres_read() != 1080))
		     && (did_reset == 0) ) {
		    hdmi_in1_clocking_searchreset_write(1);
		    hdmi_in1_clocking_mmcm_reset_write(1);
		    did_reset = 55;
		  }
		  
		}
	      } else {
		if(hdmi_in1_debug)
		  printf("hdmi_in1: lost PLL lock\r\n");
		hdmi_in1_locked = 0;
		//					hdmi_in1_clear_framebuffers();
	      }
	    } else {
	      if(hdmi_in1_clocking_locked_filtered()) {
		if(hdmi_in1_debug)
		  printf("hdmi_in1: PLL locked\r\n");
		hdmi_in1_phase_startup(freq);
		if(hdmi_in1_debug)
		  hdmi_in1_print_status();
		hdmi_in1_locked = 1;
	      }
	    }
	  }
	} else {
	  if(hdmi_in1_edid_hpd_notif_read()) {
	    if(hdmi_in1_debug)
	      printf("hdmi_in1: connected\r\n");
	    hdmi_in1_connected = 1;
	    hdmi_in1_clocking_mmcm_reset_write(0);
	  }
	}
	hdmi_in1_check_overflow();
}

#endif
