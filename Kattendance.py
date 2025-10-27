import datetime
import gspread
import re
import asyncio
from oauth2client.service_account import ServiceAccountCredentials
from dateutil import parser as date_parser  
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Google Sheet Setup ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

attendance_sheet = client.open("Kids_Attendance").worksheet("Attendance")
kids_sheet = client.open("Kids_Attendance").worksheet("Kids")


async def auto_delete(context, message, seconds=60):
    await asyncio.sleep(seconds)
    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
    except Exception as e:
        print(f"Delete failed: {e}")



def find_kid_by_id(kid_id):
    kids_data = kids_sheet.get_all_records()
    for kid in kids_data:
        if str(kid["ID"]) == str(kid_id):
            return kid
    return None

def find_attendance_row(kid_id, date_today):
    records = attendance_sheet.get_all_records()
    for i, record in enumerate(records, start=2):  # start=2 because row 1 is headers
        if str(record["ID"]) == str(kid_id) and record["Date"] == date_today:
            return i
    return None

# --- /in Command ---
async def in_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Please enter kido ID. Example: /in 1023")
        return
    
    kid_id = context.args[0]
    kid = find_kid_by_id(kid_id)
    if not kid:
        await update.message.reply_text("ID not found.")
        return

    now = datetime.datetime.now().strftime("%H:%M:%S")
    date_today = datetime.datetime.now().strftime("%Y-%m-%d")

    existing_row = find_attendance_row(kid_id, date_today)
    if existing_row:
        await update.message.reply_text(f"{kid['Name']} already clocked in today.")
        return

    attendance_sheet.append_row([kid_id, kid["Name"], date_today, now, ""])
    sent_msg = await update.message.reply_text(f"{kid['Name']} clocked IN at {now}")
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

    now = datetime.datetime.now().strftime("%H:%M:%S")
    date_today = datetime.datetime.now().strftime("%Y-%m-%d")

    row_num = find_attendance_row(kid_id, date_today)
    if not row_num:
        await update.message.reply_text(f"No IN record found today for {kid['Name']}.")
        return
    

# Column 5 = Time Out
    timeout_value = attendance_sheet.cell(row_num, 5).value

    if timeout_value and timeout_value.strip() != "":
        await update.message.reply_text(f"{kid['Name']} already clocked OUT at {timeout_value}.")
        return

    attendance_sheet.update_cell(row_num, 5, now)
    sent_msg = await update.message.reply_text(f"{kid['Name']} clocked OUT at {now}")
    asyncio.create_task(auto_delete(context, update.message, 60))  # delete user’s /in command
    asyncio.create_task(auto_delete(context, sent_msg, 60))        # delete bot’s reply



# --- /summary Command ---
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
        except:
            await update.message.reply_text(
                "Sorry, I couldn’t understand that date. Try `/summary today`, `/summary yesterday`, or `/summary 23 April`."
            )
            return

    date_str = target_date.strftime("%Y-%m-%d")

    # --- Step 2: Fetch and filter records ---
    records = attendance_sheet.get_all_records()
    day_records = [r for r in records if r["Date"] == date_str]

    # --- Step 3: No records case ---
    if not day_records:
        await update.message.reply_text(f"No attendance records found for {target_date.strftime('%d %B %Y')}.")
        return

    # --- Step 4: Format summary ---
    summary_lines = [f"📅 *Attendance Summary for {target_date.strftime('%A, %d %B %Y')}*"]
    for record in day_records:
        kid_id = record["ID"]
        name = record["Name"]
        time_in = record["Time In"]
        time_out = record.get("Time Out", "")

        if time_out.strip():
            status = "✅"
            summary_lines.append(f"{status} {kid_id} — {name}\n IN: {time_in} | OUT: {time_out}")
        else:
            status = "⚠️"
            summary_lines.append(f"{status} {kid_id} — {name}\n IN: {time_in} | OUT: ❌ Not clocked out yet")

    summary_text = "\n\n".join(summary_lines)
    sent_msg = await update.message.reply_text(summary_text, parse_mode="Markdown")
    asyncio.create_task(auto_delete(context, update.message, 180))  # delete user’s /in command
    asyncio.create_task(auto_delete(context, sent_msg, 60)        # delete bot’s reply
)
    

# --- Run Bot ---
app = ApplicationBuilder().token("8280183811:AAE3bBbVLI0TLHFyHSlVAntaqVPCuvRaVKE").build()
app.add_handler(CommandHandler("in", in_command))
app.add_handler(CommandHandler("out", out_command))
app.add_handler(CommandHandler("summary", summary_command))


print("Bot is running...")
app.run_polling()
