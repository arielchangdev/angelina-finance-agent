# Configuration

## Google Service Account Setup

1. Go to https://console.cloud.google.com/
2. Create a project (or use existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to "APIs & Services" > "Credentials"
5. Create a Service Account, download the JSON key
6. Save it as `config/service-account.json`

## Required Permissions

Share your Google Sheets spreadsheet and Drive folder with the service account email (found in the JSON file as `client_email`).

## File Structure

```
config/
  service-account.json    # Your GCP service account key (DO NOT commit)
  README.md               # This file
```
