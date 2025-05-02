# Stage 1: Build the React application
FROM node:18 AS build

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json ./
# RUN npm ci --silent
RUN npm install --silent

# Copy the rest of the frontend source code
COPY . .

# Set the production API URL build argument (will be passed by Docker Compose)
ARG REACT_APP_API_BASE_URL=/api
ENV REACT_APP_API_BASE_URL=$REACT_APP_API_BASE_URL

# Build the static files
RUN npm run build

# Stage 2: Serve static files with Nginx
FROM nginx:1.25-alpine

# Copy the built static files from the build stage
COPY --from=build /app/build /usr/share/nginx/html

# Remove default Nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/

# Expose port 80
EXPOSE 80

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]