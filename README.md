# PartSelect AI Assistant - Shreyas Rana

An AI-powered chat assistant for finding refrigerator and dishwasher parts from PartSelect.com.

## Project Structure

```
InstalilyAITakehome/
├── backend/
│   ├── agent.py          # AI agent and tools
│   ├── main.py           # Database API (FastAPI)
│   ├── scraper.py        # Web scraper for PartSelect
│   ├── requirements.txt  # Python dependencies
│   ├── Dockerfile        # Backend container
│   └── output/           # Scraped JSON files
├── frontend/
│   ├── app/
│   │   ├── page.js       # Chat interface
│   │   ├── layout.js     # App layout
│   │   └── globals.css   # Styles
│   └── package.json
├── docker-compose.yml    # Container orchestration
├── init.sql              # Database schema
├── .env                  # Environment variables (create this)
└── README.md
```


## Architecture

backend/scraper.py:
- recursively scrapes the parselect website, noting models and parts relationships
- ingests data into PosgreSQL tables, indexed forn maximum efficiency by primary keys

backend/main.py:
- provides API endpoints for reading from SQL tables

backend/agent.py:
- wraps functions around these functions for the AI Agent to call
- initializes AI Agent with chain of thought, tool calling, and carefully system prompted for safety usability, and patience. 


### Components

| Component | Description | Port |
|-----------|-------------|------|
| **Frontend** | Next.js chat interface | 3000 |
| **Agent API** | AI agent with GPT-5-nano tool calling | 8001 |
| **Database API** | FastAPI REST API for parts/models | 8000 |
| **PostgreSQL** | Database storing parts and models | 5432 |
| **Scraper** | Selenium-based web scraper for PartSelect.com | - |

## Tech Stack

- **Frontend:** Next.js, React, Tailwind CSS
- **Backend:** FastAPI, SQLAlchemy, Uvicorn
- **AI:** OpenAI GPT-5-nano with function/tool calling
- **Database:** PostgreSQL
- **Scraping:** Selenium, BeautifulSoup, WebDriver Manager
- **Containerization:** Docker, Docker Compose

## Setup

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for frontend development)
- OpenAI API key

### 1. Clone and Configure

```bash
cd InstalilyAITakehome
echo "OPENAI_API_KEY=sk-your-key-here" > .env
```

### 2. Start Backend Services

```bash
docker compose up --build
```

This starts:
- PostgreSQL on `localhost:5432`
- Database API on `localhost:8000`
- Agent API on `localhost:8001`

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `localhost:3000`

### 4. Populate Database

If the database is empty, run the scraper to fetch parts from PartSelect.com:

```bash
# Scrape dishwasher parts
python backend/scraper.py --type refrigerator --max-models 50 --max-parts-per-model 50 --db --workers 

# Scrape dishwasher parts
python backend/scraper.py --type dishwasher --max-models 50 --max-parts-per-model 50 --db --workers 10

# Or scrape both at once
python backend/scraper.py --type all --max-models 50 --max-parts-per-model 50 --db --workers 10
```

### Scraper Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--type` | refrigerator | `refrigerator`, `dishwasher`, or `all` |
| `--max-models` | 3 | Max models to scrape per appliance type |
| `--max-parts-per-model` | 10 | Max parts per model |
| `--workers` | 1 | Parallel workers (2-4 recommended) |
| `--db` | false | Save to PostgreSQL database |
| `--no-json` | false | Skip JSON file output |


## API Documentation

### Interactive Docs (Swagger UI)

- **Database API:** http://localhost:8000/docs
- **Agent API:** http://localhost:8001/docs

### Database API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/parts` | GET | Fuzzy search parts by name/description |
| `/parts/{part_number}` | GET | Get specific part by PS number |
| `/parts/by-price` | GET | Search parts by price range |
| `/parts/by-appliance-brand` | GET | Get parts for an appliance brand |
| `/parts/{part_number}/models` | GET | Get models compatible with a part |
| `/models` | GET | Search models by brand/type |
| `/models/{model_number}` | GET | Get specific model |
| `/models/{model_number}/parts` | GET | Get all parts for a model |
| `/brands` | GET | List all brands |
| `/health` | GET | Health check |

### Agent API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Send chat message to AI agent |
| `/health` | GET | Health check |

## Testing Examples

### Test Database API with curl

```bash
# Health check
curl http://localhost:8000/health

# Search parts by name (fuzzy search)
curl "http://localhost:8000/parts?name=water%20filter"

# Search dishwasher parts
curl "http://localhost:8000/parts?name=utensil%20basket&appliance_type=Dishwasher"

# Get parts by price range
curl "http://localhost:8000/parts/by-price?min_price=10&max_price=50"

# Get parts for a brand
curl "http://localhost:8000/parts/by-appliance-brand?brand=Bosch&appliance_type=Dishwasher"

# Get a specific part
curl http://localhost:8000/parts/PS11752778

# Get all parts for a model
curl http://localhost:8000/models/SHE3AR75UC/parts

# List all brands
curl http://localhost:8000/brands
```

### Test Agent API with curl

```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "I need a water filter for my Whirlpool refrigerator"}]}'

curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Tell me about part PS11752778"}]}'

curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What parts do you have for model WDT780SAEM?"}]}'
```

### Test on chat interface

```
# multiturn queries
- The ice maker on my kenmore fridge is not working. How can I fix it?
- 1061068131
- are there more parts?

# search by part number
- How can I install part number PS4132510

# search by part name
- Is Spacer 12131000002856 compatible with my Samsung Fridge?

# fuzzy search
- I'm looking for a dishwasher utensil basket
- 1266C
```

### SQL Queries (via Docker)

```bash
docker exec -it postgres_db psql -U admin -d searchdb

\d #list tables

SELECT COUNT(*) FROM parts;
SELECT COUNT(*) FROM models;

# Search parts by name
SELECT name, price FROM parts WHERE LOWER(name) LIKE '%filter%' LIMIT 10;

# model + parts mappings, with models with the most parts at the top
SELECT mp.*, counts.parts_count
FROM model_parts mp
JOIN (
    SELECT model_number, COUNT(*) as parts_count
    FROM model_parts
    GROUP BY model_number
) counts ON mp.model_number = counts.model_number
ORDER BY counts.parts_count DESC, mp.model_number;
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | Your OpenAI API key |
| `DATABASE_URL` | Auto | PostgreSQL connection string |
| `DATABASE_API_URL` | Auto | Internal API URL for agent |