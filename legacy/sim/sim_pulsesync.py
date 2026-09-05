#!/usr/bin/env python3

import lxbuildenv_sim

# This variable defines all the external programs that this module
# relies on.  lxbuildenv reads this variable in order to ensure
# the build will finish without exiting due to missing third-party
# programs.
LX_DEPENDENCIES = ["riscv", "vivado"]

import sys

from migen import *

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.integration.builder import *
from litex.soc.cores.clock import *

from migen.genlib.cdc import PulseSynchronizer

sim_config = {
    # freqs
    "input_clk_freq": 50e6,
    "sys_clk_freq": 100e6,
    "adc_clk_freq": 20e6,
}


_io = [
    ("clk", 0, Pins("X")),
    ("rst", 0, Pins("X")),
]


class Platform(XilinxPlatform):
    def __init__(self):
        XilinxPlatform.__init__(self, "", _io)


class CRG(Module):
    def __init__(self, platform, core_config):
        # build a simulated PLL. You can add more pll.create_clkout() lines to add more clock frequencies as necessary
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_adc = ClockDomain()
        
        self.submodules.pll = pll = S7MMCM()
        self.comb += pll.reset.eq(platform.request("rst"))
        pll.register_clkin(platform.request("clk"), sim_config["input_clk_freq"])
        pll.create_clkout(self.cd_sys, sim_config["sys_clk_freq"])
        pll.create_clkout(self.cd_adc, sim_config["adc_clk_freq"])


pulse_vect = [0, 0, 1, 0, 0, 1, 1, 1, 1, 0, 0, 0]

class SimpleSim(Module):
    def __init__(self, platform):
        # instantiate the clock module
        crg = CRG(platform, sim_config)
        self.submodules += crg


        # instantiate the DUT
        pulse_in = Signal()
        pulse_out = Signal()
        self.submodules.pulsesync = PulseSynchronizer("sys", "adc")
        self.comb += self.pulsesync.i.eq(pulse_in)
        self.comb += pulse_out.eq(self.pulsesync.o)

        # connect test vectors to DUT
        mult = Signal(4) # allow each element in pulse_vect to be repeated "mult" times
        count = Signal(4) # counter variable to implement mult
        self.comb += mult.eq(5)  # in this case, 5

        index = Signal(4) # tracks the index of the vector we are in
        self.sync.sys += [  # generate vector index based on count/multiply params
            count.eq(count + 1),
            If(count == mult,
               index.eq(index + 1),
               count.eq(0),
            )
        ]
        # now assign vector to DUT signal(s)
        for k, i in enumerate(pulse_vect):
            self.sync.sys += [
                If( (count == 0) & (k == index),
                    pulse_in.eq(i)
                )
            ]

def generate_top():
    platform = Platform()
    soc = SimpleSim(platform)
    platform.build(soc, build_dir="./run", run=False)  # run=False prevents synthesis from happening, but a top.v file gets kicked out

    
# this generates a test bench wrapper verilog file, needed by the xilinx tools
def generate_top_tb():
    f = open("run/top_tb.v", "w")
    f.write("""
`timescale 1ns/1ps

module top_tb();

reg clk;
initial clk = 1'b1;
always #10 clk = ~clk;

top dut (
    .clk(clk),
    .rst(0)
);

endmodule""")
    f.close()


# this ties it all together
def run_sim(gui=False):
    os.system("mkdir -p run")
    os.system("rm -rf run/xsim.dir")
    if sys.platform == "win32":
        call_cmd = "call "
    else:
        call_cmd = ""
    os.system(call_cmd + "cd run && xvlog ../glbl.v")
    os.system(call_cmd + "cd run && xvlog top.v -sv")
    os.system(call_cmd + "cd run && xvlog top_tb.v -sv ")
    os.system(call_cmd + "cd run && xelab -debug typical top_tb glbl -s top_tb_sim -L unisims_ver -L unimacro_ver -L SIMPRIM_VER -L secureip -L $xsimdir/xil_defaultlib -timescale 1ns/1ps")
    if gui:
        os.system(call_cmd + "cd run && xsim top_tb_sim -gui")
    else:
        os.system(call_cmd + "cd run && xsim top_tb_sim -runall")


def main():
    generate_top()
    generate_top_tb()
    run_sim(gui=True)


if __name__ == "__main__":
    main()
