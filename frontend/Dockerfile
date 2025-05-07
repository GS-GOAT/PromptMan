# Stage 1: Build the React application
FROM node:18 AS build

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json ./
RUN npm install --silent

# Copy the rest of the frontend source code
COPY . .

# Set environment variables from build args
ARG REACT_APP_API_BASE_URL=/api
ENV REACT_APP_API_BASE_URL=$REACT_APP_API_BASE_URL

# Add GA4 build argument and environment variable
ARG REACT_APP_GA_MEASUREMENT_ID
ENV REACT_APP_GA_MEASUREMENT_ID=$REACT_APP_GA_MEASUREMENT_ID

# Build the static files
RUN npm run build

# Stage 2: Serve static files with Nginx
FROM nginx:1.25-alpine

# Copy the built static files from the build stage
COPY --from=build /app/build /usr/share/nginx/html

# Remove default Nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/templates/nginx.conf.template

# Expose port 80
EXPOSE 80

# Use envsubst to process the nginx configuration template at runtime
CMD /bin/sh -c "envsubst '\${BACKEND_SERVICE_URL} \${BACKEND_SERVICE_HOST}' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"