# syntax=docker/dockerfile:1.7-labs

FROM node:20-alpine AS web-build

ENV PNPM_HOME=/root/.local/share/pnpm \
    PNPM_STORE_PATH=/root/.local/share/pnpm/store \
    PATH="${PNPM_HOME}:$PATH"

RUN corepack enable && corepack prepare pnpm@9.15.2 --activate

WORKDIR /app
COPY web/pnpm-lock.yaml web/package.json ./
RUN pnpm fetch
COPY web/ ./
RUN pnpm install --frozen-lockfile --offline
RUN pnpm run build

FROM caddy:2-alpine AS web
WORKDIR /srv
COPY --from=web-build /app/dist /usr/share/caddy
COPY web/Caddyfile /etc/caddy/Caddyfile
EXPOSE 4173

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
