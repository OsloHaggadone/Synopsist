# The listening API on its own (app/server.py), for its host (fly.toml; ROADMAP, Phase 4). The website
# and its songs stay on GitHub Pages, so only the API and the code it uses go in (.dockerignore).
FROM python:3.14-slim
WORKDIR /synopsist
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY src/ src/
COPY app/ app/
ENV SYNOPSIST_WEBSITE=0 \
    SYNOPSIST_DB=/data/synopsist.db \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app/server.py", "--host", "0.0.0.0", "--port", "8080"]
