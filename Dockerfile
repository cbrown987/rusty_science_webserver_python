# Dockerfile for the main Flask App

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

ENV PATH="/root/.cargo/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

WORKDIR /app


RUN pip install uv
COPY pyproject.toml pyproject.toml
RUN uv pip install --no-cache --system .

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
