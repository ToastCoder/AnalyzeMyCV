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
# Azure App Service usually populates WEBSITES_PORT, default to 8000 if not set
PORT="${WEBSITES_PORT:-8000}"

# Starting Streamlit Frontend Client On Exposed Port
echo "Starting Streamlit Frontend Client on port $PORT..."
streamlit run client/streamlit_client.py --server.address 0.0.0.0 --server.port $PORT &
STREAMLIT_PID=$!
echo "Streamlit Frontend started with PID: $STREAMLIT_PID"

# Waiting For All Background Processes To Keep The Container Running
echo "Service startup complete. Monitoring processes..."
wait $FASTAPI_PID $STREAMLIT_PID
