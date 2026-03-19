#!/bin/bash
# Setup script for Streamlit Cloud
echo "Installing system dependencies..."
apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgthread-2.0-0 \
    libgtk-3-0 \
    libcairo-gobject2 \
    libpango-1.0-0 \
    libatk1.0-0 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-dev

echo "Setup complete!"