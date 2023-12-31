import os
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import subprocess
from datetime import datetime
import requests
import time
import json
import pytz
import re

load_dotenv()

API_KEY = os.getenv('AIRTABLE_API_KEY')
BASE_ID = os.getenv('SPRIG_BASE_ID')
TABLE_NAME = os.getenv('SPRIG_TABLE_NAME')
TIMEZONE = "America/New_York"
JSON_DB_PATH = 'processed_records.json'
POLL_INTERVAL = 30
AIRTABLE_ENDPOINT = f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}'

headers = {
    'Authorization': f'Bearer {API_KEY}'
}

def format_str_datetime(value):
  print(value)
  tz = pytz.timezone(TIMEZONE)
  dt = datetime.fromisoformat(value)
  dt = dt.astimezone(tz)
  return dt.strftime("%m/%d/%Y – %I:%M%p")

def generate_pdf(data, filename="receipt.pdf"):
  env = Environment(loader=FileSystemLoader('.'))
  env.filters['format_str_datetime'] = format_str_datetime
  template = env.get_template('receipt_template.jinja')

  html_out = template.render(grant=data)

  HTML(string=html_out, base_url=".").write_pdf(filename)

def print_pdf(filename):
  printer_name = os.environ.get('DEST_RECEIPT_PRINTER')

  subprocess.run(["lp", "-d", printer_name, filename])

def load_processed_records():
  try:
    with open(JSON_DB_PATH, 'r') as file:
      return json.load(file)
  except FileNotFoundError:
    return {}

def save_processed_records(records):
  with open(JSON_DB_PATH, 'w') as file:
    json.dump(records, file)

def get_pull_request_files(pr_url):
  # Extract owner, repo, and pull request number from the URL
  match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_url)
  if not match:
    raise ValueError("Invalid GitHub pull request URL")

  owner, repo, pull_number = match.groups()

  # GitHub API endpoint to get files of a pull request
  api_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/files'

  # Make a GET request to the GitHub API
  response = requests.get(api_url)
  if response.status_code != 200:
    raise Exception(f"GitHub API responded with status code {response.status_code}")

  # Extract the file names from the response
  file_names = [file_info['filename'] for file_info in response.json()]
  return file_names

# converts ['games/DoNotConsumeEmptyBowls.js', 'games/img/Do Not Consume Empty Bowls (1).png', 'games/img/DoNotConsumeEmptyBowls.png']
# into "DoNotConsumeEmptyBowls"
def extract_sprig_game_name(pr_files):
  for path in pr_files:
    if path.startswith('games/') and path.endswith('.js'):
      # Split the path and get the last part (file name with extension)
      file_name_with_extension = path.split('/')[-1]
      # Remove the .js extension to get the game name
      game_name = file_name_with_extension[:-3]
      return game_name
  return None

def prepare_record(record):
  fields = record.get('fields', {})

  pr_url = fields.get("Pull Request", "")
  pr_files = get_pull_request_files(pr_url)

  game_name = extract_sprig_game_name(pr_files)

  project_info = {
    "name": game_name,
    "image_url": f"https://github.com/hackclub/sprig/blob/main/games/img/{game_name}.png?raw=true",
    "qr_codes": {
      "Play Game": f"https://sprig.hackclub.com/gallery/{game_name}",
      "Pull Request": pr_url,
      "Email": f"mailto:{fields.get('Email', '')}"
    }
  }

  gh = fields.get("GitHub Username")
  tz = pytz.timezone(TIMEZONE)

  formatted_record = {
    "grant_type": "sprig",
    "datetime": record.get("createdTime", ""),
    "name": fields.get("Name", ""),
    "avatar_url": f"https://github.com/{gh}.png",  # Replace with actual field name for avatar URL
    "city": fields.get("City", ""),
    "state": fields.get("State or Province", ""),
    "country": fields.get("Country", ""),
    "age": fields.get("Age (years)", ""),
    "q_a": {
      "How did you hear about Sprig?": fields.get("How did you hear about Sprig?", ""),
      "Is this the first video game you’ve made?": fields.get("Is this the first video game you've made?", ""),
      "What are we doing well?": fields.get("What are we doing well?", ""),
      "How can we improve?": fields.get("How can we improve?", ""),
      "Are you in a club?": fields.get("In a club?", "")
    },
    "project_info": project_info
  }

  return formatted_record

def process_new_records():
  processed_records = load_processed_records()
  response = requests.get(AIRTABLE_ENDPOINT, headers=headers)
  data = response.json()

  for record in data.get('records', []):
    record_id = record['id']
    if record_id not in processed_records.get(f'{BASE_ID}/{TABLE_NAME}', {}):
      print("New Record Found! Printing")
      generate_pdf(prepare_record(record), "receipt.pdf")
      print_pdf("receipt.pdf")

      processed_records.setdefault(f'{BASE_ID}/{TABLE_NAME}', {})[record_id] = True

  save_processed_records(processed_records)

if __name__ == "__main__":
   while True:
      print("Polling for new records...")
      process_new_records()
      time.sleep(POLL_INTERVAL)