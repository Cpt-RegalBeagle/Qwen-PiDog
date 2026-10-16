#!/bin/bash

# Configuration Variables
PI_USER="pidog"
PI_IP="192.168.0.15"  # Replace with your Pi's IP address
PI_PASS="m2210931385"  # 🔑 Enter your cleartext password here
LOG_PATH="/home/pidog/runtime.log"

echo "🖥️ Launching authenticated tabbed Konsole dashboard..."

# Launch Konsole using sshpass to automatically inject the password
# StrictHostKeyChecking=no prevents it from getting stuck on host verification prompts
konsole \
    --tabs-from-file <(cat <<EOF
title: 📊 PiDog Hardware Metrics; command: sshpass -p "${PI_PASS}" ssh -o StrictHostKeyChecking=no -t ${PI_USER}@${PI_IP} 'btop'
title: 📜 Live Runtime Logs; command: sshpass -p "${PI_PASS}" ssh -o StrictHostKeyChecking=no -t ${PI_USER}@${PI_IP} 'tail -n 100 -f ${LOG_PATH}'
EOF
) &

exit 0
