# CIH AI Banking — Frontend (React + Vite), build de production servi par Nginx.
#
# Build multi-etapes : compilation Vite dans un conteneur Node jetable, seul
# le resultat statique (dist/) est copie dans l'image finale Nginx — aucun
# outil Node ni node_modules dans l'image executee.
#
# VITE_API_BASE_URL (voir frontend/.env) est lu par Vite au moment du build et
# fige dans les fichiers JS generes (les variables VITE_* ne sont jamais lues
# a l'execution) : le navigateur (sur l'hote) continue de joindre le backend
# via le port publie par docker-compose (http://127.0.0.1:8000), inchange que
# le frontend tourne en conteneur ou non.

FROM node:24-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
