# ---------- 1) 前端构建 ----------
FROM node:24-alpine AS web
WORKDIR /app/web
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN npm install -g pnpm@10
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ---------- 2) Python 运行时 ----------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY src ./src
COPY data ./data
COPY evals ./evals
COPY --from=web /app/web/dist ./web/dist

RUN mkdir -p var/traces && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["python", "-m", "src.app.api", "--host", "0.0.0.0", "--port", "8000"]
