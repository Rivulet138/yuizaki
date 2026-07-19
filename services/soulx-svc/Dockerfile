FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG SOULX_REPO=https://github.com/Soul-AILab/SoulX-Singer.git
ARG SOULX_REF=main

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        git \
        libsndfile1 \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone "${SOULX_REPO}" SoulX-Singer \
    && cd SoulX-Singer \
    && git checkout "${SOULX_REF}"

WORKDIR /opt/SoulX-Singer
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir -r requirements.txt \
    && python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart

COPY server.py /opt/soulx-service/server.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/SoulX-Singer \
    SOULX_ROOT=/opt/SoulX-Singer \
    SOULX_MODEL_DIR=/models/SoulX-Singer \
    SOULX_PREPROCESS_DIR=/models/SoulX-Singer-Preprocess \
    SOULX_REFERENCE_DIR=/models/references \
    SOULX_HOST=0.0.0.0 \
    SOULX_PORT=7861

EXPOSE 7861
CMD ["python3", "/opt/soulx-service/server.py"]
