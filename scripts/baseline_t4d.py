"""Read status and TERC4 counters from the stock firmware (phase 1 baseline).
Piped to the golden unit's python3 over ssh stdin; creates no file there."""
import os
import subprocess

from netv2test.console import Console

PM2 = "/home/pi/n/bin/pm2"
# pm2 has a "#!/usr/bin/env node" shebang; a non-interactive ssh session does
# not source .bashrc, so /home/pi/n/bin (where node lives) is not on PATH.
# Without it pm2 stop/start silently fail and MagicMirror keeps the console
# open, corrupting our reads.
ENV = dict(os.environ)
ENV["PATH"] = "/home/pi/n/bin:" + ENV.get("PATH", "")

subprocess.call([PM2, "stop", "mm"], stdout=subprocess.DEVNULL, env=ENV)
try:
    c = Console(port="/dev/ttyS0", baud=115200)
    c.command("json off")
    for cmd in ["status", "debug t4i", "debug t4d", "debug t4d"]:
        print("=== " + cmd)
        print(c.command(cmd))
finally:
    subprocess.call([PM2, "start", "mm"], stdout=subprocess.DEVNULL, env=ENV)
    subprocess.call([PM2, "list"], env=ENV)
