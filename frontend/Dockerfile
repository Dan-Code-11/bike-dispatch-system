FROM node:18-alpine

WORKDIR /app

COPY frontend/package.json /app/package.json
COPY frontend/package-lock.json* /app/

RUN npm install || echo "no package-lock, continuing"

# /app source is mounted via docker-compose volumes for vite HMR (hot module reload).
# COPY kept as fallback (volumes override at runtime).
COPY frontend /app

EXPOSE 8080

# Vite will run in docker, proxying "/api" to the backend.
ENV VITE_BACKEND_URL=http://backend:8000

# --host + default vite dev HMR (auto-enabled in dev mode).
# Chokidar polling is required for volume-mounted files on Windows/WSL2.
CMD ["sh", "-c", "CHOKIDAR_USEPOLLING=true npm run dev -- --host 0.0.0.0 --port 8080 --strictPort"]

