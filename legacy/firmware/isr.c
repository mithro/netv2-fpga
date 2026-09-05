#include <generated/csr.h>
#include <irq.h>
#include <uart.h>

#include "hdmi_in0.h"
#include "hdmi_in1.h"
#include "km.h"
void isr(void);
void isr(void)
{
	unsigned int irqs;

	hdcp_debug_write(1);
	irqs = irq_pending() & irq_getmask();

	if(irqs & (1 << UART_INTERRUPT)) {
		uart_isr();
	}

#ifdef HDMI_IN1_INTERRUPT
	if(irqs & (1 << HDMI_IN1_INTERRUPT)) {
	  hdmi_in1_isr();
	}
#endif
#ifdef HDCP_INTERRUPT
	if(irqs & (1 << HDCP_INTERRUPT)) {
		hdcp_isr();
	}
#endif
#ifdef CSR_HDMI_IN0_DECODE_TERC4_EV_ENABLE_ADDR
	if(irqs & (1 << HDMI_IN0_INTERRUPT)) {
	  hdmi_in0_terc4_isr(); // actually handling a terc4 decode, not a DMA ISR. Awful API, I know.
	}
#endif
	
	hdcp_debug_write(0);
}
