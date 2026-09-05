FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_ENABLE_DEVELOPER_LAB=true
ENV VITE_ENABLE_DEVELOPER_LAB=${VITE_ENABLE_DEVELOPER_LAB}
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
