import datetime
import json
import os
import gspread
import re
import asyncio
from oauth2client.service_account import ServiceAccountCredentials
from dateutil import parser as date_parser  
from telegram import Credentials, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Google Sheet Setup ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

if os.getenv("GOOGLE_CREDENTIALS"):  # Running on Render
    creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
else:  # Running locally
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)

client = gspread.authorize(creds)


def get_attendance_sheet():
    workbook = client.open("PG-WF attendance")
    current_month_sheet = f"{datetime.datetime.now():%B} Attendance"
    
    try:
        sheet = workbook.worksheet(current_month_sheet)
    except gspread.exceptions.WorksheetNotFound:
        try:
            previous_month_sheet = f"{(datetime.datetime.now() - datetime.timedelta(days=30)):%B} Attendance"
            template_sheet = workbook.worksheet(previous_month_sheet)
        except:
            template_sheet = workbook.worksheet("Template")

        new_sheet = template_sheet.duplicate(new_sheet_name=current_month_sheet)
        new_sheet.clear()
        sheet = new_sheet

    return sheet

attendance_sheet = get_attendance_sheet()
kids_sheet = client.open("PG-WF attendance").worksheet("StudentList")


async def auto_delete(context, message, seconds=60):
    await asyncio.sleep(seconds)
    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
    except Exception as e:
        print(f"Delete failed: {e}")



def find_kid_by_id(kid_id):
    # Automatically add the 'kido' prefix if missing
    if not str(kid_id).startswith("kido"):
        kid_id = "kido" + str(kid_id)

    kids_data = kids_sheet.get_all_records()
    for kid in kids_data:
        if str(kid["ID"]).lower() == str(kid_id).lower():
            return kid
    return None


def find_attendance_row(kid_id, date_today):
    if not str(kid_id).startswith("kido"):
        kid_id = "kido" + str(kid_id)

    records = attendance_sheet.get_all_records()
    today_str = datetime.datetime.now().strftime("%B %d, %Y")  # "October 27, 2025"

    for i, record in enumerate(records, start=2):
        if str(record["ID"]).lower() == str(kid_id).lower():
            time_in_value = str(record.get("Time In", "")).strip()
            
            # check if today's date is inside the time-in value
            if today_str in time_in_value:
                return i

    return None



def get_next_available_row(sheet):
    # Only check column A (IDs). filter(None, ...) removes empty strings.
    col_a = list(filter(None, sheet.col_values(1)))
    return len(col_a) + 1




# --- /in Command ---
async def in_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Please enter kido ID. Example: /in 1023")
        return
    
    kid_id = context.args[0]
    # Force prefix early so it’s consistent everywhere
    if not kid_id.startswith("kido"):
        kid_id = "kido" + kid_id

    kid = find_kid_by_id(kid_id)
    if not kid:
        await update.message.reply_text("ID not found.")
        return

    # Format time as: Sunday, 26 October 2025, 15:00:00
    now = datetime.datetime.now()
    formatted_time_in = now.strftime("%A, %d %B %Y, %H:%M:%S")
    date_today = now.strftime("%Y-%m-%d")

    existing_row = find_attendance_row(kid_id, date_today)
    if existing_row:
        await update.message.reply_text(f"{kid['Name']} already clocked in today.")
        return

    next_row = get_next_available_row(attendance_sheet)
    attendance_sheet.insert_row([kid_id, kid["Name"], formatted_time_in, "", "", "", ""], next_row)



    sent_msg = await update.message.reply_text(f"{kid['Name']} clocked IN at {formatted_time_in}")
    asyncio.create_task(auto_delete(context, update.message, 60))  # delete user’s /in command
    asyncio.create_task(auto_delete(context, sent_msg, 60))        # delete bot’s reply




# --- /out Command ---
async def out_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Please enter an ID. Example: /out 1023")
        return
    
    kid_id = context.args[0]
    kid = find_kid_by_id(kid_id)
    if not kid:
        await update.message.reply_text("ID not found.")
        return

    # Add 'kido' prefix to match stored sheet format
    full_kid_id = f"kido{kid_id}"

    now = datetime.datetime.now().strftime("%H:%M:%S")
    date_today = datetime.datetime.now().date()


    row_num = find_attendance_row(full_kid_id, date_today)
    if not row_num:
        await update.message.reply_text(f"No IN record found today for {kid['Name']}.")
        return

    # Column 7 = Time Out
    timeout_value = attendance_sheet.cell(row_num, 7).value

    if timeout_value and timeout_value.strip() != "":
        await update.message.reply_text(f"{kid['Name']} already clocked OUT at {timeout_value}.")
        return

    attendance_sheet.update_cell(row_num, 7, now)
    sent_msg = await update.message.reply_text(f"{kid['Name']} clocked OUT at {now}")
    asyncio.create_task(auto_delete(context, update.message, 60))  # delete user’s /out command
    asyncio.create_task(auto_delete(context, sent_msg, 60))        # delete bot’s reply



# Replace your existing summary_command with this full function
async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = " ".join(context.args).lower().strip()

    # --- Step 1: Interpret user input ---
    if user_input in ["", "today"]:
        target_date = datetime.datetime.now().date()
    elif user_input == "yesterday":
        target_date = (datetime.datetime.now() - datetime.timedelta(days=1)).date()
    elif re.match(r"^\d{1,2}[/-]\d{1,2}$", user_input):  # e.g. 23/4 or 23-04
        day, month = re.split(r"[/-]", user_input)
        year = datetime.datetime.now().year
        target_date = datetime.date(year, int(month), int(day))
    else:
        try:
            target_date = date_parser.parse(user_input, fuzzy=True).date()
        except Exception:
            await update.message.reply_text(
                "Sorry, I couldn’t understand that date. Try `/summary today`, `/summary yesterday`, or `/summary 23 April`."
            )
            return

    # --- Step 2: Dynamically open sheet for the month of target_date ---
    sheet_name = target_date.strftime("%B Attendance")  # e.g. "September Attendance"
    try:
        month_sheet = client.open("PG-WF attendance").worksheet(sheet_name)
    except Exception:
        await update.message.reply_text(f"No sheet found for {sheet_name}.")
        return

    # --- Step 3: Fetch records and attempt robust parsing ---
    records = month_sheet.get_all_records()
    day_records = []

    # Debug lists to print if nothing matches
    debug_samples = []
    parsed_info = []

    for idx, r in enumerate(records):
        time_in_raw = str(r.get("Time In", "")).strip()
        debug_samples.append(time_in_raw)

        if not time_in_raw:
            parsed_info.append((idx, None))
            continue

        # Normalize Unicode whitespace and weird separators
        time_in_norm = (
            time_in_raw
            .replace("\u202f", " ")
            .replace("\xa0", " ")
            .replace("\u200b", "")   # zero-width
            .strip()
        )

        parsed_dt = None
        # 1) Try dateutil (best effort)
        try:
            parsed_dt = date_parser.parse(time_in_norm, fuzzy=True)
        except Exception:
            parsed_dt = None

        # 2) If parse failed, try a regex to extract "Month Day, Year" then parse
        if parsed_dt is None:
            # Example matches: "October 1, 2025" or "Oct 1 2025"
            m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", time_in_norm)
            if m:
                month_name, day_str, year_str = m.group(1), m.group(2), m.group(3)
                try:
                    parsed_dt = datetime.datetime.strptime(f"{month_name} {day_str} {year_str}", "%B %d %Y")
                except Exception:
                    try:
                        parsed_dt = datetime.datetime.strptime(f"{month_name} {day_str} {year_str}", "%b %d %Y")
                    except Exception:
                        parsed_dt = None

        parsed_info.append((idx, parsed_dt.isoformat() if parsed_dt else None))

        # If parsed and date matches target_date, include it
        if parsed_dt and parsed_dt.date() == target_date:
            day_records.append(r)

    # --- Debug: if nothing matched, print sample and parsed results to console ---
    if not day_records:
        print("DEBUG month_sheet sample Time In (first 10):", debug_samples[:10])
        print("DEBUG parsed results (index, parsed_iso_or_None):", parsed_info[:10])
        await update.message.reply_text(f"No attendance records found for {target_date.strftime('%A, %d %B %Y')}. (Debug printed to server logs)")
        return

    # --- Step 4: Format summary ---
    summary_lines = [f"📅 *Attendance Summary for {target_date.strftime('%A, %d %B %Y')}*"]
    for record in day_records:
        kid_id = record.get("ID", record.get("id", record.get("Id", "Unknown")))
        name = record.get("Name", "Unknown")
        time_in = record.get("Time In", "")
        time_out = record.get("Time Out", "")

        if str(time_out).strip():
            status = "✅"
            summary_lines.append(f"{status} {kid_id} — {name}\n IN: {time_in} | OUT: {time_out}")
        else:
            status = "⚠️"
            summary_lines.append(f"{status} {kid_id} — {name}\n IN: {time_in} | OUT: ❌ Not clocked out yet")

    summary_text = "\n\n".join(summary_lines)
    sent_msg = await update.message.reply_text(summary_text, parse_mode="Markdown")

    asyncio.create_task(auto_delete(context, update.message, 180))
    asyncio.create_task(auto_delete(context, sent_msg, 60)
)

    

# --- Run Bot ---
app = ApplicationBuilder().token("8280183811:AAE3bBbVLI0TLHFyHSlVAntaqVPCuvRaVKE").build()
app.add_handler(CommandHandler("in", in_command))
app.add_handler(CommandHandler("out", out_command))
app.add_handler(CommandHandler("summary", summary_command))


print("Bot is running...")
app.run_polling()
