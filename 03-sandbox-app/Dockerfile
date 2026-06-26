FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget jq git vim nano tree zip unzip \
    procps net-tools iputils-ping dnsutils \
    gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# OpenShift assigns a random UID in group 0 (root group).
# Make /app group-writable so uploaded files work under any UID.
RUN chown -R 1000:0 /app && chmod -R g=u /app
USER 1000

EXPOSE 8888

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888", "--log-level", "trace"]
