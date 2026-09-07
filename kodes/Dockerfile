# Kodes server image
# PowerShell Core (for the PS modules) + Python 3 (Flask API)
FROM mcr.microsoft.com/powershell:latest

# Python 3 + pip (server side only; pyautogui/pyperclip/pyngrok stay on the client)
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
       gcc python3-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Server dependencies only
COPY requirements-server.txt /app/requirements-server.txt
RUN pip3 install --no-cache-dir -r requirements-server.txt

# Application sources
COPY . /app/

EXPOSE 9000

# Start the server directly (src.main imports client code; pyautogui/tkinter are
# absent from the server image). run_server() loads only the server package.
CMD ["python3", "-c", "from src.server.app import run_server; run_server()"]
