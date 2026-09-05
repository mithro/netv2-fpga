#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <irq.h>
#include <uart.h>
#include <time.h>
#include <generated/csr.h>
#include <generated/mem.h>
#include "flags.h"
#include <console.h>
#include <system.h>

#include "config.h"
#include "ci.h"
#include "processor.h"
#include "pattern.h"

#include "mmcm.h"
#include "km.h"

void * __stack_chk_guard = (void *) (0xDEADBEEF);
void __stack_chk_fail(void) {
  printf( "stack fail\n" );
}

int main(void)
{
	hdcp_hpd_ena_write(1);  // de-assert hot plug detect while booting
	irq_setmask(0);
	irq_setie(1);
	uart_init();

	//	hdmi_out0_i2c_init();

	puts("\nNeTV2 software built "__DATE__" "__TIME__);

	// mmcm_dump_code(); // call this to dump the PLL config out based on vivado compiled constants
	
	config_init();
	time_init();

	processor_init();
	processor_update();
	processor_start(config_get(CONFIG_KEY_RESOLUTION));

	ci_prompt();

	int wait_event;
	int hpd_wait = 0;
	int waiting = 1;
	elapsed(&wait_event, SYSTEM_CLOCK_FREQUENCY);
	
	hdcp_hpd_ena_write(0); // release hot plug detect once we're into the main loop
	
	while(1) {
	  processor_service();
	  ci_service();
	  uptime_service();

	  // put a delay of a few seconds before releasing HPD
	  if( waiting ) {
	    if( elapsed( &wait_event, SYSTEM_CLOCK_FREQUENCY ) ) {
	      hpd_wait++;
	    }
	    if( hpd_wait > 1 ) {
	      hdcp_hpd_ena_write(0); // release hot plug detect once we're into the main loop
	      waiting = 0;
	    }
	  }
	  
	  if( link_redo ) {
	    waiting = 1;
	    hpd_wait = 0;
	    link_redo = 0;
	    hdcp_hpd_ena_write(1); 
	  }
	}

	return 0;
}
