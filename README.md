# PromptMan

PromptMan is a web application that converts codebases into comprehensive LLM prompts using the `code2prompt` tool.

## Features

- Upload a code folder
- Process it using `code2prompt` via the FastAPI backend
- Track job status
- Download the resulting Markdown file

## Project Structure

```
PromptMan/
├── .gitignore
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── services/
│   │   └── code_service.py
│   ├── temp/
│   │   └── .gitkeep
│   └── results/
│       └── .gitkeep
└── frontend/
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

- Python 3.8+
- Node.js 14+
- `code2prompt` CLI tool installed in your environment

## Setup & Installation

### Backend

1. Navigate to the backend directory:
   ```
   cd backend
   ```

2. Create a Python virtual environment:
   ```
   python -m venv venv
   ```

3. Activate the virtual environment:
   - On Windows: `venv\Scripts\activate`
   - On macOS/Linux: `source venv/bin/activate`

4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

5. Ensure `code2prompt` is installed:
   ```
   pip install code2prompt
   ```

### Frontend

1. Navigate to the frontend directory:
   ```
   cd frontend
   ```

2. Install dependencies:
   ```
   npm install
   ```

## Running the Application

### Start the Backend

1. Navigate to the backend directory with the virtual environment activated
2. Run:
   ```
   uvicorn main:app --reload --port 8000
   ```

### Start the Frontend

1. Navigate to the frontend directory
2. Run:
   ```
   npm start
   ```

3. Open your browser to http://localhost:3000

## Usage

1. Upload a code folder using the drag & drop interface or the file browser
2. Wait for the processing to complete
3. Download the resulting Markdown file

## API Endpoints

- `POST /api/upload-codebase`: Upload code files
- `GET /api/job-status/{job_id}`: Check job status
- `GET /api/download/{job_id}`: Download processed result 