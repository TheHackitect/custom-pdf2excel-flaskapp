from flask import Flask, render_template, request, send_file, jsonify
from flask_socketio import SocketIO
import tabula
import pandas as pd
import re
import fitz
import os
import logging
import uuid
from threading import Thread

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



def remove_pdf_and_excel_files(pdf_path):
    # Get a list of all files in the current directory
    files = os.listdir()

    # Filter out PDF and Excel files
    pdf_and_excel_files = filter(lambda filename: filename.endswith(('.pdf', '.xlsx')), files)

    # Delete each PDF and Excel file
    for filename in pdf_and_excel_files:
        if filename == pdf_path:
            pass
        else:
            try:
                os.remove(filename)
            except:
                pass

def emit_log(log_message):
    socketio.emit('log', {'data': log_message})


def extract_address(address):
    if isinstance(address, str):
        match = re.search(r'"([^"]*)"', address)
        if match:
            return match.group(1)
        else:
            return "Failed to extract address."
    else:
        return "Invalid address format: {}".format(address)

def extract_date_and_run(page_text):
    match = re.search(r'(\d{4}/\d{2}/\d{2}) \/ Run: (\w+)', page_text)
    if match:
        return match.group(1).replace('/', '-'), match.group(2)
    else:
        return None, None

def extract_mileage(page_text):
    match = re.search(r'Mileage:\s+(\d+\.\d+)\s+km', page_text)
    if match:
        return match.group(1)
    else:
        return None

def parse_customer_info(text):
    # Extract comments starting from "Note:/"
    note_match = re.search(r'Note:/\s*(.*)', text)
    comments = note_match.group(1).strip() if note_match else ''

    # Remove leading slashes from comments
    comments = comments.lstrip('/')

    # Define regex pattern to extract customer name, ID, and address
    pattern = r"([^0-9*]+)\*?(\d{5,6})?\s*(.*)"
    match = re.match(pattern, text)

    if match:
        customer_name = match.group(1).strip()
        customer_id = match.group(2)

        return customer_name, customer_id, comments
    else:
        return None, None, None

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def test_connect():
    emit_log("Server is ready!.... You can upload Customers PDFs now.")

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        emit_log("No file part")
        return "No file part"
    file = request.files['file']
    if file.filename == '':
        emit_log("No selected file")
        return 'No selected file'
    else:
        filename = str(uuid.uuid4()) + '.pdf'
        file.save(filename)
        process_pdf(filename)
        return 'File uploaded successfully and processed'

def process_pdf(pdf_path):
    remove_pdf_and_excel_files(pdf_path)
    emit_log("Now Processing..... [ Please wait ]")
    # Open the PDF
    with fitz.open(pdf_path) as doc:
        # Extract text from all pages
        all_text = [page.get_text() for page in doc]
        emit_log("Extracted Text Content.......")

    # Initialize an empty list to store rows
    rows = []

    # Iterate over each page
    page_num = 0
    for page_num, page_text in enumerate(all_text):
        # Extract date, run number, and mileage from page text
        date, run_number = extract_date_and_run(page_text)
        mileage = extract_mileage(page_text)

        # Extract tables from current page of PDF
        tables = tabula.read_pdf(pdf_path, pages=page_num + 1, multiple_tables=True)

        # If there are no tables found
        if not tables:
            emit_log("Table not found on page {}".format(page_num + 1))
            continue
        else:
            page_num += 1
            emit_log(f"\n\n=============== PAGE {page_num}  ===============\n\n")

        table = tables[0]

        # Process each row of the table
        for _, row in table.iterrows():
            pick_up_time = row[0]
            customer_info = row[5]  # Assuming the customer info is in the 5th column
            address = row[3]

            # Check if customer_info is a string
            if isinstance(customer_info, str):
                # Parse customer info to extract name, ID, address, and comments
                customer_name, customer_id, comments = parse_customer_info(customer_info)

                # Append data to rows list
                rows.append([date, run_number, pick_up_time, customer_name, customer_id, address, comments, mileage])
                emit_log(f"User Data: {customer_name}....................{customer_id}")

    # Create DataFrame from rows
    df = pd.DataFrame(rows, columns=['Date', 'Run_Number', 'Pick_Up_Time', 'Customer_Name', 'Customer_ID', 'Address', 'Comments', 'Mileage'])

    # Write DataFrame to Excel (ensure file is closed after writing)
    file_id = str(uuid.uuid4())
    output_filename = file_id + '.xlsx'
    try:
        df.to_excel(output_filename, index=False)
        emit_log("Successfully Extracted Table!")
        download_data = {
            "download_link" : f"/download/{file_id}"  # Corrected the download link format
        }
        socketio.emit('download_link', download_data)  # Emitting the download link correctly
        emit_log(download_data)
        
    except Exception as e:
        emit_log("An error occurred while writing to Excel: {}".format(e))

@app.route('/download/<fileid>')
def download_file(fileid):
    filename = f"{fileid}.xlsx"
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        socketio.emit(f'An error occured!\n\n{e}')
        return render_template("index.html")

if __name__ == '__main__':
    socketio.run(app, port=8000, host="0.0.0.0", debug=True)
