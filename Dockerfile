FROM node:22-bookworm-slim AS frontend

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY public ./public
COPY src ./src
RUN npm run build


FROM debian:bookworm-slim AS stockfish

ARG STOCKFISH_VERSION=sf_18
ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /stockfish
RUN curl -fsSL \
        "https://github.com/official-stockfish/Stockfish/archive/refs/tags/${STOCKFISH_VERSION}.tar.gz" \
        | tar -xz --strip-components=1 \
    && case "${TARGETARCH}" in \
        amd64) stockfish_arch="x86-64" ;; \
        arm64) stockfish_arch="armv8" ;; \
        *) stockfish_arch="general-64" ;; \
       esac \
    && make -C src -j2 build ARCH="${stockfish_arch}" \
    && install -m 0755 src/stockfish /usr/local/bin/stockfish


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    TRUST_PROXY=true \
    STOCKFISH_PATH=/usr/local/bin/stockfish \
    STOCKFISH_DEPTH=24 \
    STOCKFISH_MAX_SECONDS=1.25 \
    STOCKFISH_MULTIPV=1 \
    STOCKFISH_CRITICAL_MULTIPV=4 \
    STOCKFISH_CRITICAL_MAX_POSITIONS=4 \
    STOCKFISH_CRITICAL_MAX_SECONDS=0.3 \
    STOCKFISH_THREADS=1 \
    STOCKFISH_HASH_MB=64 \
    STOCKFISH_TOTAL_SECONDS=14 \
    LICHESS_WORKERS=2 \
    MAX_ANALYSIS_PLIES=20 \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=stockfish /usr/local/bin/stockfish /usr/local/bin/stockfish
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY --from=frontend /app/build ./build

EXPOSE 8080

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 2 --timeout 120 --access-logfile - --error-logfile - backend.app:app"]
