# FireBridge on Hugging Face Spaces (Docker, free CPU). Also runs anywhere Docker runs:
#   docker build -t firebridge .
#   docker run -p 7860:7860 -e APP_DATA_URL=... -e FIRMS_MAP_KEY=... firebridge
# The data is NOT in the image: at startup the app downloads the 4 data files from
# APP_DATA_URL (our Hugging Face dataset, URL ending in /resolve/main/) into APP_DATA_DIR,
# and refreshes the live FIRMS feed hourly if FIRMS_MAP_KEY is set. See docs/DEPLOY.md.
FROM python:3.12-slim

# Hugging Face runs the container as user 1000; give that user a home it can write to.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/home/user/app/data/app \
    LIVE_CACHE_DIR=/home/user/app/data/cache
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .
# If the deploy bundled the data (scripts/deploy_space.py --with-data), move it into place so a
# waking Space doesn't re-download 530 MB; otherwise the app downloads it from APP_DATA_URL.
RUN mkdir -p "$APP_DATA_DIR" "$LIVE_CACHE_DIR" &&     if [ -d appdata ]; then mv appdata/* "$APP_DATA_DIR"/ && rmdir appdata; fi

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
