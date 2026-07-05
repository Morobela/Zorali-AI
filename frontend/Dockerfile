# Multi-stage production image. Build context is the repository root (see
# docker-compose.prod.yml) so the shared infra/nginx/nginx.conf can be baked in.
#
#   docker build -f frontend/Dockerfile -t zorali-frontend .

# ---- Build stage: compile the Vite app to static assets ----
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Serve stage: nginx serving the built dist/ ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
