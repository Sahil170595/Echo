FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[slack,discord,telegram]" 2>/dev/null || pip install --no-cache-dir -e "."

COPY echo/ echo/

# Default to slack adapter; override with ECHO_ADAPTER env var
# Valid values: slack, discord, telegram, email, whatsapp
ENV ECHO_ADAPTER=slack
CMD ["sh", "-c", "python -m echo.${ECHO_ADAPTER}"]
