#!/usr/bin/env bash
# Render build script — runs ONCE before the service starts.
# 1. Install Python deps
# 2. Build the React frontend so the FastAPI app can serve it from web/dist/
set -e

echo "==> Installing Python dependencies..."
pip install -e ".[aws]"
pip install python-dotenv

echo "==> Installing frontend dependencies..."
cd web
npm ci
npm run build
cd ..

echo "==> Build complete. web/dist is ready."