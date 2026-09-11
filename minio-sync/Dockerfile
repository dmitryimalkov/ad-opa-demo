FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libldap2-dev libsasl2-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir python-ldap httpx

RUN curl -sSL -o /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc \
    && chmod +x /usr/local/bin/mc

WORKDIR /app
COPY sync_minio_policies.py .

CMD ["python3", "sync_minio_policies.py"]
