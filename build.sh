#!/usr/bin/env bash
# Render build script — runs ONCE before the service starts.
# 1. Install Python deps
# 2. Build the React frontend so the FastAPI app can serve it from web/dist/
set -e

echo "==> Installing Python dependencies..."
pip install --upgrade pip setuptools wheel
pip install -e ".[aws]"
# Fix oscrypto version detection bug on OpenSSL 3.0+
pip install --upgrade "git+https://github.com/wbond/oscrypto.git@master"
pip install python-dotenv

echo "==> Installing frontend dependencies..."
cd web
npm ci
npm run build
cd ..

echo "==> Build complete. web/dist is ready."