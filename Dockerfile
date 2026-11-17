FROM python:3.12-slim AS build
# git holt die Bot-Library diddybot (siehe pyproject.toml); matrix-nio[e2e] bringt vodozemac als Wheel mit
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY issuebot ./issuebot
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
LABEL org.opencontainers.image.title="IssueBotMatrix" \
      org.opencontainers.image.source="https://github.com/Lndr2501/issuebotmatrix" \
      org.opencontainers.image.description="Matrix-Bot: !issue Titel | Beschreibung legt ein GitHub-Issue an"
COPY --from=build /install /usr/local
RUN useradd --create-home --uid 10001 issuebot \
    && mkdir -p /data && chown issuebot:issuebot /data
USER issuebot
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "issuebot"]
