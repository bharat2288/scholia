#!/bin/bash
# =============================================================================
# Pod Setup Script
# =============================================================================
# Run this once when a pod starts to install dependencies and verify setup.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/.../setup_pod.sh | bash
#   OR
#   bash /data/scripts/setup_pod.sh
# =============================================================================

set -e  # Exit on error

echo "=============================================="
echo "Setting up Scholia processing pod"
echo "Pod ID: ${RUNPOD_POD_ID:-unknown}"
echo "=============================================="

# Check data volume is mounted
if [ ! -d "/data" ]; then
    echo "ERROR: /data volume not mounted!"
    exit 1
fi

# Create directory structure
echo "Creating directory structure..."
mkdir -p /data/input
mkdir -p /data/processing
mkdir -p /data/output
mkdir -p /data/logs
mkdir -p /data/archive
mkdir -p /data/scripts

echo "Directories created:"
ls -la /data/

# Install dots-ocr if not present
if ! python -c "import dots_ocr" 2>/dev/null; then
    echo "Installing dots-ocr..."
    pip install dots-ocr --quiet
else
    echo "dots-ocr already installed"
fi

# Verify CUDA is available
echo "Checking CUDA availability..."
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"

# Copy coordinator script to data volume (if not already there)
if [ -f "/workspace/coordinator.py" ]; then
    cp /workspace/coordinator.py /data/scripts/
    echo "Copied coordinator.py to /data/scripts/"
fi

echo ""
echo "=============================================="
echo "Setup complete!"
echo ""
echo "To start processing:"
echo "  python /data/scripts/coordinator.py"
echo ""
echo "To check status:"
echo "  python /data/scripts/coordinator.py --status"
echo "=============================================="
