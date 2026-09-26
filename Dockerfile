FROM python:3.11-slim

RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir mokuro==0.2.5

# The OCR models (~900 MB) are downloaded on the first run into this volume, not baked into the image.
ENV HOME=/cache \
    XDG_CACHE_HOME=/cache \
    HF_HOME=/cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY mokuro_watcher ./mokuro_watcher
RUN pip install --no-cache-dir --no-deps .

VOLUME ["/cache", "/state"]
ENTRYPOINT ["mokuro-watcher"]
CMD ["run"]
