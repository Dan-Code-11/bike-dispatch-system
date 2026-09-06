FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV BIKE_DATA_DIR=/app/data

# watchfiles is required by uvicorn --reload
RUN pip install --no-cache-dir --upgrade pip

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install CPU-only PyTorch for stable demo environments.
# (Avoids pulling CUDA-related huge wheels in non-GPU machines.)
RUN pip install --no-cache-dir "torch==2.2.2+cpu" -f https://download.pytorch.org/whl/torch_stable.html

# /app/app and /app/data are mounted via docker-compose volumes for hot-reload.
# Source files only copied as fallback (volumes override at runtime).
COPY backend/app /app/app
COPY data /app/data

EXPOSE 8000

# --reload enables hot-reload on code changes (requires watchfiles).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app/app"]

