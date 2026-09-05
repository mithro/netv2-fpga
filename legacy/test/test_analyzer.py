#!/usr/bin/env python3

from litex.soc.tools.remote import RemoteClient

from litescope import LiteScopeAnalyzerDriver

wb = RemoteClient()
wb.open()

# # #

analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
analyzer.configure_subsampler(1)
analyzer.configure_group(0)

#analyzer.add_trigger(cond={"soc_videooverlaysoc_videooverlaysoc_videooverlaysoc_interrupt": 0x8})
#analyzer.add_rising_edge_trigger("soc_videooverlaysoc_videooverlaysoc_videooverlaysoc_interrupt")
#analyzer.add_falling_edge_trigger("soc_videooverlaysoc_hdmi_in1_frame_de")
analyzer.add_falling_edge_trigger("soc_videooverlaysoc_hdmi_in1_frame_de")
#analyzer.add_trigger(cond={"soc_videooverlaysoc_hdcp_ctl_code" : 9})
#analyzer.add_trigger(cond={"soc_videooverlaysoc_analyzer_fsm2_state" : 0})

analyzer.run(offset=32, length=64)
analyzer.wait_done()
analyzer.upload()
analyzer.save("dump.vcd")

# # #

wb.close()
