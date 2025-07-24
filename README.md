# PromptMan

PromptMan is a web application that converts codebases into comprehensive LLM prompts.

## Features

- Upload a code folder
- Process it via the FastAPI backend
- Track job status
- Download the resulting Markdown file

## Project Structure

```
PromptMan/
├── .env                  # Environment configuration
├── .gitignore
├── docker-compose.yml    # Docker services orchestration
├── backend/
│   ├── Dockerfile       # Backend multi-stage build
│   ├── main.py         # FastAPI application
│   ├── requirements.txt
│   ├── services/
│   │   └── code_service.py
│   ├── temp/
│   │   └── .gitkeep
│   └── results/
│       └── .gitkeep
└── frontend/
    ├── Dockerfile      # Frontend build + Nginx
    ├── nginx.conf      # Nginx reverse proxy config
    ├── public/
    │   └── index.html
    ├── src/
    │   ├── App.css
    │   ├── App.js
    │   ├── index.css
    │   └── index.js
    └── package.json
```

## Prerequisites

- Docker
- Docker Compose

## Configuration

1. Copy `.env.example` to `.env` if it exists, or create a new `.env` file:
   ```
   # Backend Configuration
   PORT=8000
   REDIS_HOST=redis
   REDIS_PORT=6379
   ALLOWED_ORIGINS=http://localhost,http://localhost:80
   PYTHONUNBUFFERED=1

   # Frontend/Nginx Configuration
   NGINX_PORT=80
   ```

2. Adjust values in `.env` as needed:
   - `NGINX_PORT`: Change if port 80 is already in use
   - `ALLOWED_ORIGINS`: Add your domain in production

## Building and Running

1. Build the containers:
   ```bash
   docker-compose build
   ```

2. Start the services:
   ```bash
   docker-compose up -d
   ```

3. Access the application:
   - Development: http://localhost (or http://localhost:${NGINX_PORT} if you changed it)
   - Production: https://your-domain.com

4. View logs (optional):
   ```bash
   docker-compose logs -f
   ```

5. Stop the services:
   ```bash
   docker-compose down
   ```

## Architecture

- Frontend: React application served by Nginx
- Backend: FastAPI + Gunicorn/Uvicorn workers
- Storage: Redis for job data, local filesystem for results
- Proxy: Nginx reverse proxy for API requests

## Development

To develop locally without Docker:

1. Backend:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```

2. Frontend:
   ```bash
   cd frontend
   npm install
   npm start
   ```

## Production Deployment

For production deployment:

1. Update `.env` with production settings:
   - Set `ALLOWED_ORIGINS` to your domain
   - Consider using different ports if needed

2. Setup HTTPS (recommended):
   - Install Certbot
   - Obtain SSL certificate
   - Update Nginx configuration
   - Mount SSL certificates into the frontend container

3. Enable firewall rules:
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   ```

4. Deploy:
   ```bash
   docker-compose -f docker-compose.yml up -d
   ```

5. Monitor:
   ```bash
   docker-compose logs -f
   ```

## Maintenance

- **Backups**: Regularly back up the Redis volume (`redis_data`)
- **Updates**: 
  1. Pull latest code changes
  2. Rebuild images: `docker-compose build`
  3. Restart services: `docker-compose up -d`
- **Cleanup**: 
  - Old results: Automatically cleaned up after 24 hours
  - Containers: `docker-compose down` to stop and remove
  - Volumes: Add `-v` to remove persistent data: `docker-compose down -v`

## License

[Your license here]