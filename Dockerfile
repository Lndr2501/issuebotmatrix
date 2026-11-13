FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY issuebot ./issuebot
# matrix-nio[e2e] bringt vodozemac als fertiges Wheel mit, kein Compiler noetig
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 issuebot \
    && mkdir -p /data && chown issuebot:issuebot /data
USER issuebot
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "issuebot"]
