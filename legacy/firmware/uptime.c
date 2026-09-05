#include <stdio.h>
#include <string.h>
#include <time.h>

#include <generated/csr.h>

#include "uptime.h"

#include "stdio_wrap.h"

static int uptime_seconds = 0;
static int last_event;

void uptime_service(void)
{
	if(elapsed(&last_event, SYSTEM_CLOCK_FREQUENCY)) {
		uptime_seconds++;
	}
}

// return ms since boot
// doesn't gracefully handle overflow, so perhaps once in 49 days the system will glitch
uint32_t uptime_ms(void) {
  int timer_cur;
  int delta;

  elapsed(&timer_cur, -1);
  delta = timer_cur - last_event;
  if( delta < 0 )
    delta += timer0_reload_read();
  
  return uptime_seconds * 1000 + (delta / (SYSTEM_CLOCK_FREQUENCY / 1000));
}

int uptime(void)
{
	return uptime_seconds;
}

void uptime_print(void)
{
	wprintf("uptime: %s\n", uptime_str());
}

const char* uptime_str(void)
{
	static char buffer[9];
	sprintf(buffer, "%02d:%02d:%02d",
		(uptime_seconds/3600)%24,
		(uptime_seconds/60)%60,
		uptime_seconds%60);
	return buffer;
}
