# syntax=docker/dockerfile:1
# Образ web: статика Web App + Caddy (TLS, заголовки безопасности, прокси к api).
# Версии закреплены; pnpm — версия из packageManager в webapp/package.json (corepack).
ARG NODE_IMAGE=node:24.21.0-trixie-slim
ARG CADDY_IMAGE=caddy:2.11.4-alpine

FROM ${NODE_IMAGE} AS build
RUN corepack enable
WORKDIR /src
COPY webapp/package.json webapp/pnpm-lock.yaml webapp/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY webapp/ ./
ARG VITE_MAX_BRIDGE_URL=""
ARG VITE_DEMO_LOGIN="false"
ARG VITE_MAX_BOT_USERNAME=""
ENV VITE_MAX_BRIDGE_URL=$VITE_MAX_BRIDGE_URL VITE_DEMO_LOGIN=$VITE_DEMO_LOGIN VITE_USE_MOCKS=false
ENV VITE_MAX_BOT_USERNAME=$VITE_MAX_BOT_USERNAME
# Карты исходников не публикуются: сборка с `sourcemap: 'hidden'` (webapp/vite.config.ts)
# не оставляет ссылок на них в бандле, сами .map удаляются до копирования в итоговый образ.
RUN pnpm exec tsc -b \
    && pnpm exec vite build \
    && find dist -name '*.map' -delete \
    && if find dist -name '*.map' | grep -q .; then echo "в dist остались .map" >&2; exit 1; fi

FROM ${CADDY_IMAGE}
# Caddy работает не от root: порты 80/443 открывает sysctl
# net.ipv4.ip_unprivileged_port_start (compose.prod.yaml), а не capability. File
# capability у бинарника снимается копированием: с ней при cap_drop: [ALL] ядро
# отказывает в запуске (EPERM).
RUN cp /usr/bin/caddy /usr/bin/caddy.nocap && mv /usr/bin/caddy.nocap /usr/bin/caddy \
    && addgroup -S -g 10002 caddy \
    && adduser -S -D -H -u 10002 -G caddy caddy \
    && mkdir -p /data/caddy /config/caddy \
    && chown -R caddy:caddy /data /config
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv/webapp
USER caddy
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD wget -q -O /dev/null http://127.0.0.1:8081/health || exit 1
