
# ==========================================
# Stage 0: Fetch node modules for flag icons
# ==========================================
FROM node:18-alpine AS node-build
WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

# ==========================================
# Stage 1: Build dependencies
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Prevent Python from writing .pyc files and enable buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system build dependencies if your packages need them (e.g., gcc, psycopg2)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*

# Install python dependencies into a local directory
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ==========================================
# Stage 2: Final runtime image
# ==========================================
FROM python:3.11-slim AS runner

# Install system dependencies for Cairo
RUN apt-get update && apt-get install -y \
    libcairo2 \
    libgirepository1.0-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH

# Create a non-root system user and group for security
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -m -s /sbin/nologin appuser

# Copy installed dependencies from the builder stage
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

COPY --from=node-build /app/node_modules/flag-icons/flags ./flags

# Copy application source code and set correct ownership
COPY --chown=appuser:appuser ./main.py ./app/

# Tell Docker to run everything below this line as the non-root user
USER appuser

# Expose the port FastAPI will run on
EXPOSE 8000

# Production-configured startup command
CMD ["python", "/app/main.py"]
