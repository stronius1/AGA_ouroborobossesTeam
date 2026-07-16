# syntax = docker/dockerfile:1.3
ARG NODE_IMAGE_VERSION=20.20.2-alpine3.23

# ------------------------ All dependencies -------------------------
FROM node:${NODE_IMAGE_VERSION} AS all-deps

WORKDIR /var/www

COPY package.json package-lock.json ./
COPY plugins ./plugins/
COPY libs ./libs/

ENV npm_config_audit=false
ENV npm_config_fund=false 
ENV npm_config_logs_max=0 

RUN npm ci

# ------------------ Only production-dependencies -------------------
FROM all-deps AS prod-deps

WORKDIR /var/www

ARG GITVERSE=false

RUN npm prune --production && \
    npm cache clean --force && \
    # The GitVerse Docker registry requires each layer to be no larger than 100 MB 
    if [ "$GITVERSE" = "true" ]; then \
        mkdir -p node_modules_1 && \
        find node_modules -maxdepth 1 -type d -name "[@a-k]*" -exec mv -t node_modules_1/ {} + ; \
    else \
        mkdir -p node_modules_1 ; \
    fi

# ------------------------------ Build ------------------------------
FROM node:${NODE_IMAGE_VERSION} AS build

WORKDIR /var/www

COPY . .
COPY --from=all-deps /var/www .

ENV NODE_ENV=production
ENV VUE_APP_DOCHUB_MODE=backend
ENV VUE_APP_PLANTUML_SERVER=ORIGIN
ENV NODE_OPTIONS="--max-old-space-size=4096"

RUN npm run build
RUN find . -name "node_modules" -type d -prune -exec rm -rf '{}' +

# -------------------------- Final output ---------------------------
FROM node:${NODE_IMAGE_VERSION} AS backend

WORKDIR /var/www

COPY --from=prod-deps --chown=1000:1000 --chmod=755 /var/www/node_modules/   ./node_modules/
COPY --from=prod-deps --chown=1000:1000 --chmod=755 /var/www/node_modules_1/ ./node_modules/
COPY --from=build     --chown=1000:1000 --chmod=755 /var/www/                ./

RUN VERSION=$(npm pkg get version --silent | tr -d '"') && \
    echo '#!/bin/sh' > /entrypoint.sh && \
    echo "export npm_package_version=${VERSION}" >> /entrypoint.sh && \
    echo 'exec /sbin/tini -- "$@"' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Remove npm, npx, etc.
RUN rm -rf /usr/local/lib/node_modules/npm \
           /usr/local/bin/npm \
           /usr/local/bin/npx \
           /usr/local/bin/corepack \
           /opt /root/.npm /tmp/*
RUN apk update && apk upgrade --no-cache && apk add --no-cache tini && rm -rf /var/cache/apk/*

USER 1000

ENV VUE_APP_PLANTUML_REQUEST_TYPE=POST_COMPRESSED
ENV VUE_APP_DOCHUB_APPEND_DOCHUB_DOCS=n

ENTRYPOINT ["/entrypoint.sh"]

# Directly run tsx (without npx)
CMD ["node_modules/.bin/tsx", "src/backend/main.mjs"]

EXPOSE 3030