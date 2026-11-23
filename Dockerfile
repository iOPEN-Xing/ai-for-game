FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_DATA_DIR=/data \
    STUDIO_DEPLOYED=1
WORKDIR /app

COPY requirements.txt requirements-linux.lock ./
RUN pip install --no-cache-dir --only-binary=:all: -c requirements-linux.lock -r requirements.txt \
    && groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid studio --no-create-home studio \
    && install -d -o studio -g studio /data

COPY app.py ./
COPY studio/ studio/
COPY docs/PILOT.md docs/
# The team reference page uses these assets. Compose mounts the complete archive read-only.
COPY docs/original/index.html docs/original/
COPY docs/original/assets/img-19.png docs/original/assets/img-20.png docs/original/assets/img-21.png docs/original/assets/
USER 10001:10001
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--forwarded-allow-ips", "*", "--no-access-log"]
