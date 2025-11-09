#!/usr/bin/env python3
"""
Script to create cronjob.org jobs for election events.
Reads from CSV and creates jobs 2 days before and after each event date.
"""

import csv
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sys
import os
from pathlib import Path
import time


def load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from .env file."""
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value


class CronjobScheduler:
    def __init__(self, server_url: str = "http://localhost:5000"):
        self.server_url = server_url
        self.cronjob_api_url = "https://api.cron-job.org/jobs"

    def read_csv_events(self, csv_file_path: str) -> List[Dict]:
        """Read events from CSV file."""
        events = []
        try:
            with open(csv_file_path, "r", newline="", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    events.append(row)
        except FileNotFoundError:
            print(f"Error: CSV file '{csv_file_path}' not found.")
            sys.exit(1)
        except Exception as e:
            print(f"Error reading CSV file: {e}")
            sys.exit(1)

        return events

    def parse_date(self, year: str, mmdd: str) -> datetime:
        """Parse year and mmdd into datetime object."""
        try:
            month = mmdd[:2]
            day = mmdd[2:]
            date_str = f"{year}-{month}-{day}"
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            print(f"Error parsing date {year}/{mmdd}: {e}")
            return None

    def create_schedule(self, target_date: datetime) -> Dict:
        """Create schedule object for cronjob.org API."""
        return {
            "timezone": "UTC",
            "hours": [9],  # Run at 9 AM
            "mdays": [target_date.day],  # Specific day of month
            "minutes": [0],  # At minute 0
            "months": [target_date.month],  # Specific month
            "wdays": [-1],  # Any day of week (-1 means ignore)
        }

    def create_webhook_payload(self, event_data: Dict, is_pre_event: bool) -> Dict:
        """Create the webhook payload for the server."""
        payload = {
            "electionId": event_data.get("electionId", ""),
            "countryName": event_data.get("countryName", ""),
            "types": event_data.get("types", ""),
            "year": event_data.get("year", ""),
            "mmdd": event_data.get("mmdd", ""),
            "pre": is_pre_event,
        }
        return payload

    def create_cronjob(
        self, event_data: Dict, target_date: datetime, is_pre_event: bool, api_key: str
    ) -> bool:
        """Create a cronjob.org job using their correct API format."""
        schedule = self.create_schedule(target_date)
        webhook_payload = self.create_webhook_payload(event_data, is_pre_event)

        job_name = f"Election_{event_data.get('electionId', 'unknown')}_{event_data.get('countryName', 'unknown')}_{'pre' if is_pre_event else 'post'}"

        # Structure according to cronjob.org API format from official docs
        cronjob_data = {
            "job": {
                "url": f"{self.server_url}/runNelda",
                "enabled": True,
                "saveResponses": True,
                "schedule": schedule,
                "requestMethod": 1,  # 1 = POST
                "extendedData": {
                    "body": json.dumps(webhook_payload),
                    "headers": {"Content-Type": "application/json"},
                },
                "title": job_name,
            }
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        print(f"📡 Sending request to cronjob.org API...")
        print(f"URL: {self.cronjob_api_url}")
        print(f"Headers: {headers}")
        print(f"Payload: {json.dumps(cronjob_data, indent=2)}")

        try:
            response = requests.put(
                self.cronjob_api_url, json=cronjob_data, headers=headers
            )

            print(f"📥 API Response:")
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            print(f"Response Body: {response.text}")

            if response.status_code == 200:  # cronjob.org returns 200 for success
                print(
                    f"✓ Created job: {job_name} for {target_date.strftime('%Y-%m-%d')}"
                )
                return True
            else:
                print(f"✗ Failed to create job {job_name}: {response.status_code}")
                print(f"Error details: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"✗ Request failed for job {job_name}: {e}")
            return False

    def process_events(self, csv_file_path: str, api_key: str) -> None:
        """Process all events from CSV and create cronjobs."""
        events = self.read_csv_events(csv_file_path)

        if not events:
            print("No events found in CSV file.")
            return

        print(f"Processing {len(events)} events...")

        success_count = 0
        total_jobs = len(events) * 2  # 2 jobs per event

        # Collect all jobs to create
        jobs_to_create = []
        for event in events:
            event_date = self.parse_date(event.get("year", ""), event.get("mmdd", ""))

            if not event_date:
                print(f"Skipping event with invalid date: {event}")
                continue

            # Add job for 2 days before
            pre_date = event_date - timedelta(days=2)
            jobs_to_create.append((event, pre_date, True))

            # Add job for 2 days after
            post_date = event_date + timedelta(days=2)
            jobs_to_create.append((event, post_date, False))

        # Process jobs in batches of 5
        batch_size = 5
        for i in range(0, len(jobs_to_create), batch_size):
            batch = jobs_to_create[i : i + batch_size]
            print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} jobs)...")

            for j, (event, target_date, is_pre_event) in enumerate(batch):
                if self.create_cronjob(event, target_date, is_pre_event, api_key):
                    success_count += 1

                # Wait 1 second between requests within the batch (except after the last request in the batch)
                if j < len(batch) - 1:
                    print(f"⏳ Waiting 1 second before next request...")
                    time.sleep(1)

            # Wait 60 seconds before next batch (unless this is the last batch)
            if i + batch_size < len(jobs_to_create):
                print(f"⏳ Waiting 60 seconds before next batch...")
                time.sleep(60)

        print(f"\nCompleted: {success_count}/{total_jobs} jobs created successfully.")


def main():
    """Main function to run the cronjob scheduler."""
    # Load environment variables from .env file
    load_env_file()

    if len(sys.argv) < 2:
        print("Usage: python cronjob_scheduler.py <csv_file_path>")
        print("Example: python cronjob_scheduler.py events.csv")
        print("Make sure CRONJOB_API_KEY is set in .env file")
        sys.exit(1)

    csv_file_path = sys.argv[1]

    # Get API key from environment variable
    api_key = os.environ.get("CRONJOB_API_KEY")
    if not api_key:
        print("Error: CRONJOB_API_KEY not found in environment or .env file.")
        print("Create a .env file with: CRONJOB_API_KEY=your_api_key_here")
        sys.exit(1)

    # Optional: Get server URL from environment variable
    server_url = os.environ.get("SERVER_URL", "http://localhost:5000")
    if not server_url:
        print("Error: SERVER_URL not found in environment or .env file.")
        print("Create a .env file with: SERVER_URL=https://example.com")
        sys.exit(1)

    scheduler = CronjobScheduler(server_url)
    scheduler.process_events(csv_file_path, api_key)


if __name__ == "__main__":
    main()
