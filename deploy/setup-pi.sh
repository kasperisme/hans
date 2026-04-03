#!/bin/bash
# Setup script for Raspberry Pi
# Run this on a fresh Ubuntu Server installation

set -e

echo "=== Hans Home Automation Setup ==="

# Update system
echo "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
echo "Installing Python and build tools..."
sudo apt install -y python3.11 python3.11-venv python3-pip git

# Install Chrome/Chromium for Claude computer use
echo "Installing Chromium..."
sudo apt install -y chromium-browser

# Create project directory
PROJECT_DIR="$HOME/hans"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Cloning repository..."
    git clone https://github.com/YOUR_USERNAME/hans.git "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# Create virtual environment
echo "Creating Python virtual environment..."
python3.11 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Check for .env file
if [ ! -f ".env" ]; then
    echo ""
    echo "WARNING: .env file not found!"
    echo "Copy .env.example to .env and fill in your credentials:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
fi

# Install systemd service
echo "Installing systemd service..."
sudo cp deploy/hans-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hans-bot.service

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit .env with your API credentials: nano .env"
echo "2. Start the bot: sudo systemctl start hans-bot"
echo "3. Check status: sudo systemctl status hans-bot"
echo "4. View logs: journalctl -u hans-bot -f"
