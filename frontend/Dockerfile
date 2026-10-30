# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CartScope frontend.
#
# Two targets:
#   dev     - the Next.js dev server, for working on the UI
#   runner  - the default: a standalone production bundle on a slim runtime
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
# Install against the lockfile alone, so editing a component does not
# re-resolve the dependency tree.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- Development ------------------------------------------------------------
FROM node:22-alpine AS dev
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# --- Build ------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* values are inlined at build time, so the browser-facing API
# base URL has to be supplied here rather than at run time.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN npm run build

# --- Production runtime -----------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S -u 1001 -G nodejs nextjs

# The standalone output carries only the server and the modules it actually
# imports, so the runtime image does not need node_modules at all.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
