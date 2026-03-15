FROM python:3.11-slim

WORKDIR /app

# Install Poetry and configure it
RUN pip install poetry && poetry config virtualenvs.create false

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry install --no-dev --no-interaction --no-root

# Copy application code
COPY . .

# Install the package itself
RUN poetry install --no-dev --no-interaction

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Default command
CMD ["python", "-m", "src.main"]
