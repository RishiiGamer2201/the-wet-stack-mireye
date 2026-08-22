# The Wet Stack — Mireye API
#
# Docker rather than Render's native Python runtime for one reason: OCR needs the
# `tesseract` binary, which is an apt package, not a pip one. Everything else here
# matches what the native runtime did.
#
# Build context is `apps/api` (see render.yaml `dockerContext`).

FROM python:3.13.4-slim

# tesseract-ocr        the OCR engine PyMuPDF shells out to
# tesseract-ocr-eng    English language data (`eng.traineddata`)
# libgl1, libglib2.0-0 shared libraries PyMuPDF's rasteriser links against
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Debian puts the language data here. The application probes for it, but setting
# it explicitly means a Tesseract upgrade that moves the default cannot silently
# turn OCR off.
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source-only change does not reinstall them.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# Writable path for SQLite and uploads. Still ephemeral — see docs/deployment.md.
ENV DATA_DIR=/tmp/wetstack

EXPOSE 8000

# Single worker, deliberately: the impact-graph store is in-process memory and the
# SQLite store holds one guarded connection, so a second worker would serve a
# different graph depending on which process answered.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --no-access-log"]
