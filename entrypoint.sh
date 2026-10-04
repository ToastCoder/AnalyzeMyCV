#!/bin/sh

# Starting FastAPI Backend Service Internally
# Bound to loopback: only the Streamlit frontend in this container may call it.
# A single worker keeps the in-process per-user rate limit accurate; blocking PDF
# and LLM work runs in a thread pool, so requests still proceed concurrently.
echo "Starting FastAPI Backend Service on 127.0.0.1:8080..."
uvicorn api.main:app --host 127.0.0.1 --port 8080 --workers 1 &
FASTAPI_PID=$!
echo "FastAPI Backend started with PID: $FASTAPI_PID"

sleep 3

# Setting Web App Port
PORT="${WEBSITES_PORT:-8000}"

# Starting Streamlit On Internal Port 8001 (loopback only; the proxy is the public entry point).
# maxUploadSize is a CLI flag so it overrides any STREAMLIT_SERVER_MAX_UPLOAD_SIZE app setting.
echo "Starting Streamlit Frontend Client on 127.0.0.1:8001..."
streamlit run client/streamlit_client.py --server.address 127.0.0.1 --server.port 8001 --server.maxUploadSize 8 &
STREAMLIT_PID=$!
echo "Streamlit Frontend started with PID: $STREAMLIT_PID"

# Wait For Streamlit To Be Ready Before Starting Proxy
echo "Waiting for Streamlit to be ready..."
for i in $(seq 1 30); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/_stcore/health', timeout=2)" >/dev/null 2>&1; then
    echo "Streamlit is ready."
    break
  fi
  sleep 1
done

# Starting Python Reverse Proxy On Public Port
echo "Starting reverse proxy on port $PORT..."
PROXY_PORT="$PORT" python proxy.py &
PROXY_PID=$!
echo "Reverse proxy started with PID: $PROXY_PID"

# Waiting For All Background Processes To Keep The Container Running
echo "Service startup complete. Monitoring processes..."
wait $FASTAPI_PID $STREAMLIT_PID $PROXY_PID
