#!/usr/bin/env bash
# Render start script — runs on every instance boot.
# Starts the execution service in the background, then hands off to uvicorn
# which is the foreground (watched) process Render cares about.
set -e

PORT="${PORT:-8000}"
EXEC_PORT="${SIDEKICK_EXEC_PORT:-8088}"

echo "==> Starting sidekick-execution on port $EXEC_PORT..."
python -m sidekick_execution serve --host 0.0.0.0 --port "$EXEC_PORT" &
EXEC_PID=$!

# Give the execution service a moment to bind
sleep 2

echo "==> Starting sidekick core on port $PORT..."
exec uvicorn sidekick.api.app:create_app \
    --factory \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers 1 \
    --log-level info