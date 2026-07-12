# Using Slim Base Image For Smallest Possible Footprint
FROM python:3.10-slim

# Setting Environment Variables To Prevent Python From Generating Pyc Files
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Installing Nginx For Reverse Proxying
RUN apt-get update && apt-get install -y --no-install-recommends nginx && \
    rm -rf /var/lib/apt/lists/*

# Setting Working Directory
WORKDIR /app

# Copying Requirements And Installing Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copying The Entire Application Source Code
COPY . .

# Replacing Default Nginx Config
RUN cp /app/nginx.conf /etc/nginx/nginx.conf

# Exposing Port For Azure Web App Service
EXPOSE 8000

# Making The Entrypoint Script Executable
RUN chmod +x entrypoint.sh

# Setting The Entrypoint To Orchestration Script
ENTRYPOINT ["./entrypoint.sh"]
