# StepSpotter — the phone-first web UI in a container.
#
# Port 8080 is the App Runner / Bedrock AgentCore Runtime convention. Build for the
# platform you deploy to: App Runner takes x86_64 or arm64; AgentCore Runtime takes
# ARM64 ONLY, so use --platform linux/arm64 for that path (see docs/DEPLOY.md).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    STEPSPOTTER_DATA=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && mkdir -p /data/jobs \
 && useradd --create-home --uid 10001 spotter \
 && chown -R spotter:spotter /data /app
USER spotter

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "stepspotter.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
