FROM node:22-slim

# The host user's ids. The app runs as this user and owns /app, node_modules included.
ARG UID=1000
ARG GID=1000

# Ids without a passwd entry get HOME=/, which they cannot write to.
ENV npm_config_cache=/tmp/npm-cache

WORKDIR /app
RUN chown "$UID:$GID" /app
USER $UID:$GID

COPY --chown=$UID:$GID package.json package-lock.json ./
RUN npm ci

COPY --chown=$UID:$GID . .

CMD ["npm", "run", "dev"]
