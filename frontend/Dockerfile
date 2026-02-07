FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY index.html /usr/share/nginx/html/
COPY admin.html /usr/share/nginx/html/
COPY admin.js /usr/share/nginx/html/
COPY styles.css /usr/share/nginx/html/
COPY status.js /usr/share/nginx/html/

EXPOSE 80
