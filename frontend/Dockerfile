FROM nginxinc/nginx-unprivileged:stable-alpine

USER root
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY index.html /usr/share/nginx/html/
COPY admin.html /usr/share/nginx/html/
COPY admin.js /usr/share/nginx/html/
COPY styles.css /usr/share/nginx/html/
COPY status.js /usr/share/nginx/html/

# Ask app
COPY ask/ /usr/share/nginx/html/ask/

RUN chown -R 101:101 /usr/share/nginx/html

USER 101

EXPOSE 8080
