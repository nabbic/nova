FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 1000 --create-home --shell /bin/false nova

WORKDIR /app

COPY --from=builder /root/.local /home/nova/.local
ENV PATH=/home/nova/.local/bin:$PATH

COPY app/ ./app/

USER nova

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
