#!/bin/sh
# Install the source agent on rpiz-3.  Run from the repo root on the host:
#   sh agent/install.sh tim@rpiz-3.welland.mithis.com
set -e
HOST="$1"
scp -q agent/netv2_source_agent.py netv2test/patterns.py agent/netv2-source-agent.service "$HOST:/tmp/"
ssh "$HOST" 'sudo mkdir -p /opt/netv2-agent && sudo cp /tmp/netv2_source_agent.py /tmp/patterns.py /opt/netv2-agent/ && sudo cp /tmp/netv2-source-agent.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable netv2-source-agent.service && sudo systemctl restart netv2-source-agent.service && sleep 3 && systemctl --no-pager status netv2-source-agent.service | head -12'
