# NELDA Election Coding Project

This project contains tools for automated NELDA (National Elections Across Democracy and Autocracy) dataset coding using AI analysis.

## Files

- `server.py` - Flask server that processes election data using Google's Gemini API
- `cronjob_scheduler.py` - Script to create automated cronjobs for election events
- `sample_events.csv` - Example CSV file showing the required format for election data
- `NELDA_Codebook_V5.pdf` - NELDA dataset codebook for reference

## Setup

### 1. Environment Variables

Create a `.env` file in this directory with the following variables:

```env
CRONJOB_API_KEY=your_cronjob_org_api_key_here
GEMINI_API_KEY=your_google_gemini_api_key_here
SERVER_URL=http://localhost:5000
```

**Required variables:**
- `CRONJOB_API_KEY` - Your API key from cronjob.org for scheduling jobs
- `GEMINI_API_KEY` - Your Google Gemini API key for AI analysis

**Optional variables:**
- `SERVER_URL` - URL where your server is running (defaults to http://localhost:5000)

### 2. CSV Format

Your CSV file should contain the following columns:
- `electionId` - Unique identifier for the election
- `countryName` - Name of the country
- `types` - Type of election (e.g., Presidential, Parliamentary, Federal)
- `year` - Year of the election
- `mmdd` - Month and day in MMDD format (e.g., 1105 for November 5th)

Example CSV:
```csv
electionId,countryName,types,year,mmdd
USA2024001,United States,Presidential,2024,1105
FRA2024001,France,Parliamentary,2024,0630
```

## Usage

### Running the Server

Start the Flask server:
```bash
python server.py
```

The server will be available at `http://localhost:5000` and accepts POST requests to `/runNelda`.

### Scheduling Cronjobs

Use the cronjob scheduler to create automated jobs:
```bash
python cronjob_scheduler.py your_events.csv
```

This will:
1. Read election events from the CSV file
2. Create two cronjobs for each event:
   - One job scheduled 2 days **before** the election date
   - One job scheduled 2 days **after** the election date
3. Each job will call your server's `/runNelda` endpoint with the appropriate parameters

### Manual API Testing

You can manually test the server with curl:
```bash
curl -X POST http://localhost:5000/runNelda \
  -H "Content-Type: application/json" \
  -d '{
    "electionId": "USA2024001",
    "countryName": "United States",
    "types": "Presidential",
    "year": "2024",
    "mmdd": "1105",
    "pre": true
  }'
```

## Security Notes

- The `.env` file is git-ignored to keep your API keys secure
- Never commit API keys to version control
- Keep your API keys private and rotate them regularly

## Dependencies

- Flask
- google-genai
- requests
- Standard Python libraries (csv, json, datetime, etc.)