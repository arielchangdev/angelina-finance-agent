"""
Google Sheets Daily Market Tracker
寫入每日市場分析數據到 Google Sheets 試算表
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# Configuration
SERVICE_ACCOUNT_PATH = '/opt/angelina/config/service-account.json'
SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID'
WORKSHEET_NAME = 'Daily Tracker'
SCOPES = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]

HEADERS = [
    '日期', '加權指數', '漲跌幅(%)', '成交量(億)',
    'S&P 500', 'NASDAQ', '道瓊',
    '三大法人淨買賣(億)', 'AI方向', '推撥狀態', '分析摘要'
]


def init_sheet():
    """
    Initialize gspread client with service account credentials.
    If the worksheet "Daily Tracker" doesn't exist, create it.
    Set up headers if the sheet is empty.
    
    Returns:
        gspread.Worksheet: The initialized worksheet object
    """
    try:
        credentials = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_PATH, scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        # Try to get existing worksheet, or create if not found
        try:
            worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            print(f"[SheetsTracker] Worksheet '{WORKSHEET_NAME}' not found, creating...")
            worksheet = spreadsheet.add_worksheet(
                title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS)
            )

        # Always ensure row 1 has headers
        all_vals = worksheet.get_all_values()
        if not all_vals:
            worksheet.append_row(HEADERS)
            print(f"[SheetsTracker] Headers initialized.")
        elif all_vals[0] != HEADERS:
            # First row is data, not headers - insert headers at top
            worksheet.insert_row(HEADERS, 1)
            print(f"[SheetsTracker] Headers inserted at row 1.")

        print("[SheetsTracker] Sheet initialized successfully.")
        return worksheet

    except Exception as e:
        print(f"[SheetsTracker] Error initializing sheet: {e}")
        return None


def record_daily_data(data: dict):
    """
    Append a row with today's data to the Daily Tracker sheet.
    
    Args:
        data: Dictionary with keys matching the HEADERS columns.
    """
    try:
        sheet = init_sheet()
        if sheet is None:
            print("[SheetsTracker] Cannot record data - sheet initialization failed.")
            return

        # Build row in header order, using empty string for missing keys
        row = [str(data.get(header, '')) for header in HEADERS]
        sheet.append_row(row)
        print(f"[SheetsTracker] Daily data recorded for {data.get('日期', 'unknown date')}.")

    except Exception as e:
        print(f"[SheetsTracker] Error recording daily data: {e}")


def update_prediction_accuracy(date_str: str, actual_result: str):
    """
    Find the row for the given date and update the "實際結果" column.
    For future use in tracking prediction accuracy.
    
    Args:
        date_str: Date string to search for (e.g., '2026-07-21')
        actual_result: The actual market result to record
    """
    try:
        sheet = init_sheet()
        if sheet is None:
            print("[SheetsTracker] Cannot update prediction - sheet initialization failed.")
            return

        # Find the row with the matching date
        all_values = sheet.get_all_values()
        headers_row = all_values[0] if all_values else []

        # Find or create the "實際結果" column
        if '實際結果' in headers_row:
            result_col = headers_row.index('實際結果') + 1  # gspread is 1-indexed
        else:
            # Add the column header
            result_col = len(headers_row) + 1
            sheet.update_cell(1, result_col, '實際結果')
            print("[SheetsTracker] Added '實際結果' column.")

        # Search for the date in the first column
        date_col_values = sheet.col_values(1)
        if date_str in date_col_values:
            row_index = date_col_values.index(date_str) + 1  # 1-indexed
            sheet.update_cell(row_index, result_col, actual_result)
            print(f"[SheetsTracker] Updated prediction accuracy for {date_str}: {actual_result}")
        else:
            print(f"[SheetsTracker] Date '{date_str}' not found in sheet.")

    except Exception as e:
        print(f"[SheetsTracker] Error updating prediction accuracy: {e}")
