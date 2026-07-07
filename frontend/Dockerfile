# Multi-stage production image. Build context is the repository root (see
# docker-compose.prod.yml) so the shared infra/nginx/nginx.conf can be baked in.
#
#   docker build -f frontend/Dockerfile -t zorali-frontend .

# ---- Build stage: compile the Vite app to static assets ----
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Serve stage: nginx serving the built dist/ as a non-root user ----
FROM nginx:alpine@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
# Unprivileged nginx: the master runs as the nginx user, so it binds 8080
# (mapped to host 80 by docker-compose.prod.yml) and needs writable pid/cache
# paths (pid lives in /tmp — see nginx.conf).
RUN chown -R nginx:nginx /var/cache/nginx
USER nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
