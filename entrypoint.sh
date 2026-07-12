#!/bin/sh

# Ensuring The Script Is Executable
chmod +x ./entrypoint.sh

# Starting FastAPI Backend Service Internally
echo "Starting FastAPI Backend Service on port 8080..."
uvicorn api.main:app --host 0.0.0.0 --port 8080 --workers 4 &
FASTAPI_PID=$!
echo "FastAPI Backend started with PID: $FASTAPI_PID"

sleep 3

# Setting Web App Port
PORT="${WEBSITES_PORT:-8000}"

# Starting Streamlit On Internal Port 8001
echo "Starting Streamlit Frontend Client on port 8001..."
streamlit run client/streamlit_client.py --server.address 0.0.0.0 --server.port 8001 &
STREAMLIT_PID=$!
echo "Streamlit Frontend started with PID: $STREAMLIT_PID"

# Wait For Streamlit To Be Ready Before Starting Proxy
echo "Waiting for Streamlit to be ready..."
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:8001/_stcore/health >/dev/null 2>&1; then
    echo "Streamlit is ready."
    break
  fi
  sleep 1
done

# Starting Python Reverse Proxy On Public Port
echo "Starting reverse proxy on port $PORT..."
python proxy.py &
PROXY_PID=$!
echo "Reverse proxy started with PID: $PROXY_PID"

# Waiting For All Background Processes To Keep The Container Running
echo "Service startup complete. Monitoring processes..."
wait $FASTAPI_PID $STREAMLIT_PID $PROXY_PID
