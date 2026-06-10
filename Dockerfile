FROM node:20-slim AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app
ENV TDX_API_HOST=0.0.0.0
ENV TDX_API_PORT=8622
ENV TDX_API_RELOAD=0
ENV TDX_DATA_ROOT=/data/tdx-data
ENV TDX_TQCENTER_PATH=
ENV TDX_CORS_ORIGINS=*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY tdx_downloader ./tdx_downloader
COPY app.py ./app.py
COPY --from=web-build /web/dist ./web/dist

EXPOSE 8622
CMD ["python", "-m", "tdx_downloader.web_api"]
