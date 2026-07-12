# Using Slim Base Image For Smallest Possible Footprint
FROM python:3.10-slim

# Setting Environment Variables To Prevent Python From Generating Pyc Files
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Setting Working Directory
WORKDIR /app

# Copying Requirements And Installing Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copying The Entire Application Source Code
COPY . .

# Exposing Port For Azure Web App Service
EXPOSE 8000

# Making The Entrypoint Script Executable
RUN chmod +x entrypoint.sh

# Setting The Entrypoint To Orchestration Script
ENTRYPOINT ["./entrypoint.sh"]
