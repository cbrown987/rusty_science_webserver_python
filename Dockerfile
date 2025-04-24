# Dockerfile for the main Flask App

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install Rust (needed by Flask app if it *also* compiles/uses rust directly,
# otherwise potentially removable if ONLY the sandbox container uses rustc)
# Keep build-essential and curl for rustup
ENV PATH="/root/.cargo/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]

# IMPORTANT NOTE:
# To run this container, you MUST mount the Docker socket, e.g.:
# docker run -p 5000:5000 -v /var/run/docker.sock:/var/run/docker.sock your-flask-app-image-name
# This gives the Flask app container permission to control the Docker daemon.
# Be aware of the security implications of this.