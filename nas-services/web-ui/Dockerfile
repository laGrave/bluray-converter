FROM nginx:alpine

# Install curl for health checks
RUN apk add --no-cache curl

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy web UI files
COPY *.html *.css *.js /usr/share/nginx/html/

# Create directory for logs
RUN mkdir -p /var/log/nginx

# Set proper permissions
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chown -R nginx:nginx /var/log/nginx

# Expose HTTP port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

# Run nginx
CMD ["nginx", "-g", "daemon off;"]