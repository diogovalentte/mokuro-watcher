FROM python:3.11-slim

# opencv-python needs X11 libraries the slim image lacks; the headless build is the same API without them.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir mokuro==0.2.5 \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless \
    && python -c "import cv2, mokuro.manga_page_ocr"

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
EXPOSE 8000
ENTRYPOINT ["mokuro-watcher"]
CMD ["run"]
