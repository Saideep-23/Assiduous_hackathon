FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Rewrites in next.config.js read this at build time. In Compose, proxy /api → FastAPI service.
ENV BACKEND_INTERNAL_URL=http://backend:8000
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
