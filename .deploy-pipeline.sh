#!/usr/bin/env bash
# 🛰 PiDog Deployment Pipeline - Simple Version
set +e  # Don't exit on error

# Configuration
REMOTE_HOST="pidog"
REMOTE_IP="192.168.0.15"
REMOTE_PATH="/home/pidog/pidog"

echo "📦 Pre-flight check: Starting deployment pipeline..."

# Set the global environment variable that sshpass looks for automatically
export SSHPASS="m2210931385"

echo "🛰  Syncing codebase to Raspberry PiDog..."

# First, clean up garbage files on remote (simple approach)
echo "🧹 Cleaning up garbage files on remote..."
sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pidog@${REMOTE_IP} "cd ${REMOTE_PATH} && rm -f '*.swp' '*.swo' 2>/dev/null || true"

# List files in current directory for debugging
echo "📁 Current directory contents:"
ls -la "./"

# Sync all files from CURRENT DIRECTORY (where script is run) to remote
# This syncs ONLY the project files, not the entire OS!
echo "📁 Syncing files..."
rsync_output=$(sshpass -e rsync -avz \
    --exclude='__pycache__/' \
    --exclude='.git/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.log' \
    --exclude='*.tmp' \
    --exclude='*.swp' \
    --exclude='*.md' \
    --exclude='*.swo' \
    --exclude='.aider*' \
    --exclude='*.sh' \
    --exclude='*.appimage' \
    --exclude='/proc/' \
    --exclude='/sys/' \
    --exclude='/dev/' \
    --exclude='/run/' \
    --exclude='/boot/' \
    --exclude='/usr/' \
    --exclude='/var/' \
    --exclude='/etc/' \
    --exclude='/home/' \
    --exclude='/.ssh/' \
    --exclude='/pidog/' \
    --exclude='/.aider*/' \
    --exclude='/robot-hat/' \
    --exclude='/Sunfounder SDK/' \
    -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" \
    "./" \
    pidog@${REMOTE_IP}:${REMOTE_PATH}/ 2>&1)

rsync_exit_code=$?

# Display the rsync output (file list)
echo "$rsync_output"

if [ $rsync_exit_code -eq 0 ]; then
    echo ""
    echo "✅ Deployment successful!"
    echo "📁 Files copied to pidog@${REMOTE_IP}:${REMOTE_PATH}"
else
    echo ""
    echo "⚠️ Deployment completed with warnings (exit code: $rsync_exit_code)"
fi

echo ""
echo "🔍 Running Main Scaffold Script"

echo "🔍 Starting main.py on remote (execution ID: $$)"

sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null pidog@${REMOTE_IP} "python3 ${REMOTE_PATH}/main.py" &
SSH_PID=$!
echo "🔍 SSH command PID: $SSH_PID"

# Wait for the SSH command to complete
wait $SSH_PID
EXIT_CODE=$?

echo "🔍 SSH command completed with exit code: $EXIT_CODE"

echo "🔍 Deployment pipeline completed"
exit 1
