# =============================================================
# EcoSim Frontend — Next.js 16 (App Router) production image
# =============================================================
# Multi-stage:
#   1. deps     — install npm deps with cache
#   2. builder  — `next build` → .next/standalone (self-contained server)
#   3. runner   — minimal Alpine Node, copy standalone output, run on :5173
#
# Build:  docker build -t ecosim-frontend ./apps/frontend
# Run:    docker run --rm -p 5173:5173 -e GATEWAY_UPSTREAM=http://host.docker.internal:5000 ecosim-frontend
#
# In docker-compose, GATEWAY_UPSTREAM=http://gateway:5000 (service name).
# =============================================================

# ─── Stage 1: deps ───────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app

# Faster, deterministic install
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ─── Stage 2: builder ────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ─── Stage 3: runner ─────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=5173
ENV HOSTNAME=0.0.0.0

# Non-root user for runtime
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001 -G nodejs

# Copy standalone server + static assets + public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 5173

CMD ["node", "server.js"]
