FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY agent/ ./agent/

# Add src to Python path so agent can import from it
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

WORKDIR /app/agent

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
