FROM node:18 AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:alpine
# Copy built assets from build stage to nginx serve directory
COPY --from=build /app/dist /usr/share/nginx/html

# Expose port 80 inside the container
EXPOSE 80

# Nginx config or default startup
CMD ["nginx", "-g", "daemon off;"]
