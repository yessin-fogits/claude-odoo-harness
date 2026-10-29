# Layer 3 e2e: Playwright (Chromium) + pytest, pinned.
FROM python:3.12-slim
RUN pip install --no-cache-dir "playwright==1.63.0" "pytest-playwright==0.7.1" \
 && playwright install --with-deps chromium
WORKDIR /work
