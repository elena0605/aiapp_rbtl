FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY backend/requirements.txt requirements.txt
# Install CyVer from GitLab first (requires Python >= 3.10, Docker uses 3.13)
RUN pip install --no-cache-dir git+https://gitlab.com/netmode/CyVer.git || echo "Warning: CyVer installation failed, read-only validation will still work"
# Install other requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy project root (for imports)
COPY . /app

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

