FROM python:3.12-slim

LABEL org.opencontainers.image.title="HomeLabStats" \
      org.opencontainers.image.description="Self-hosted health dashboard for Linux home servers" \
      org.opencontainers.image.source="https://github.com/bhxuk/HomeLabStats" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt \
 && sha256sum requirements.txt | cut -d' ' -f1 > /usr/local/.homelabstats-req

# The compose file mounts the git checkout over /app so in-app updates work.
# The copy below lets the image also run on its own (without self-update).
COPY app ./app
COPY CHANGELOG.md ./
COPY scripts/docker-entrypoint.sh /usr/local/bin/homelabstats-entrypoint
RUN chmod +x /usr/local/bin/homelabstats-entrypoint

ENV DATA_DIR=/data \
    PORT=8090 \
    INSTALL_METHOD=docker \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request,base64;r=urllib.request.Request('http://127.0.0.1:'+os.environ.get('PORT','8090')+'/api/health');p=os.environ.get('DASH_PASSWORD');p and r.add_header('Authorization','Basic '+base64.b64encode((os.environ.get('DASH_USER','admin')+':'+p).encode()).decode());urllib.request.urlopen(r,timeout=4)"

ENTRYPOINT ["homelabstats-entrypoint"]
