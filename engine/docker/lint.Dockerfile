# Layer 1 lint: pylint-odoo, pinned so every machine lints the same way.
FROM python:3.12-slim
RUN pip install --no-cache-dir "pylint-odoo==10.0.12"
WORKDIR /work
