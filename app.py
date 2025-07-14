from flask import Flask, render_template, request, redirect, flash, send_file, session
import sqlite3
import matplotlib.pyplot as plt
import io
import zipfile
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "secret"

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_number TEXT UNIQUE NOT NULL,
            owner TEXT NOT NULL,
            product TEXT NOT NULL,
            sub_product TEXT,
            category TEXT,
            status TEXT,
            date TEXT
        );
    """)
    conn.commit()
    conn.close()

@app.route("/", methods=["GET", "POST"])
def index():
    conn = get_db_connection()
    if request.method == "POST":
        form = request.form
        case_number = form["case_number"]
        cur = conn.cursor()
        cur.execute("SELECT * FROM cases WHERE case_number = ?", (case_number,))
        existing = cur.fetchone()
        if existing:
            flash("Case number exists. Please update details.", "warning")
            return redirect(f"/update/{case_number}")
        cur.execute("""
            INSERT INTO cases 
            (case_number, owner, product, sub_product, category, status, date) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            form["case_number"], form["owner"], form["product"],
            form["sub_product"], form["category"], form["status"], form["date"]
        ))
        conn.commit()
        flash("Case submitted successfully!", "success")
    cases = conn.execute("SELECT * FROM cases").fetchall()
    conn.close()
    return render_template("index.html", cases=cases)

@app.route("/report", methods=["GET", "POST"])
def report():
    report_data = []
    summary = {}
    grouped = {}

    if request.method == "POST":
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]

        conn = get_db_connection()
        report_data = conn.execute(
            "SELECT * FROM cases WHERE date BETWEEN ? AND ?", (start_date, end_date)
        ).fetchall()
        conn.close()

        status_counts = {}
        product_counts = {"stat": 0, "up": 0}

        for row in report_data:
            status = row["status"].strip().lower()
            status_title = status.title()

            # Status count
            status_counts[status_title] = status_counts.get(status_title, 0) + 1

            # Product count
            product_key = row["product"].strip().lower()
            if product_key in product_counts:
                product_counts[product_key] += 1

            # Grouped data
            product = row["product"]
            sub_product = row["sub_product"] or "N/A"
            grouped.setdefault(product, {})
            grouped[product].setdefault(sub_product, {"closed": 0, "total": 0})
            grouped[product][sub_product]["total"] += 1
            if status in ["closed", "customer validation"]:
                grouped[product][sub_product]["closed"] += 1

        # Final summary
        summary = {
            "total": len(report_data),
            "status_counts": status_counts,
            "product_counts": product_counts
        }

        session["summary"] = summary
        session["grouped"] = grouped

    return render_template("report.html", data=report_data, summary=summary, grouped=grouped)

@app.route("/download-report", methods=["GET"])
def download_report():
    summary = session.get("summary", {})
    grouped = session.get("grouped", {})

    if not summary or not grouped:
        flash("Please generate a report first before downloading.", "error")
        return redirect("/report")

    # === PIE CHART 1: Product Cases (Stat vs Up) ===
    product_buf = io.BytesIO()
    product_labels = ["Stat", "Up"]
    product_values = [
        summary.get("product_counts", {}).get("stat", 0),
        summary.get("product_counts", {}).get("up", 0)
    ]
    plt.figure(figsize=(5, 5))
    plt.pie(product_values, labels=product_labels, autopct="%1.1f%%", startangle=90, colors=["#4CAF50", "#2196F3"])
    plt.title("Product Case Distribution")
    plt.tight_layout()
    plt.savefig(product_buf, format="png")
    product_buf.seek(0)
    plt.close()

    # === PIE CHART 2: Status Distribution ===
    status_buf = io.BytesIO()
    statuses = summary.get("status_counts", {})
    statuses = {k: v for k, v in statuses.items() if v > 0}
    plt.figure(figsize=(6, 6))
    plt.pie(statuses.values(), labels=statuses.keys(), autopct="%1.1f%%", startangle=140)
    plt.title("Case Status Distribution")
    plt.tight_layout()
    plt.savefig(status_buf, format="png")
    status_buf.seek(0)
    plt.close()

    # === PDF SUMMARY ===
    pdf_buf = io.BytesIO()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Case Report Summary", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, f"Total Cases: {summary.get('total', 0)}", ln=True)
    pdf.ln(5)
    pdf.cell(0, 10, "Product Breakdown:", ln=True)
    pdf.cell(0, 10, f" - Stat: {summary.get('product_counts', {}).get('stat', 0)}", ln=True)
    pdf.cell(0, 10, f" - Up: {summary.get('product_counts', {}).get('up', 0)}", ln=True)

    pdf.ln(5)
    pdf.cell(0, 10, "Status Breakdown:", ln=True)
    for status, count in statuses.items():
        pdf.cell(0, 10, f" - {status}: {count}", ln=True)

    pdf_output = pdf.output(dest='S').encode('latin1')
    pdf_buf.write(pdf_output)
    pdf_buf.seek(0)

    # === ZIP the report ===
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zipf:
        zipf.writestr("product_distribution_pie.png", product_buf.read())
        zipf.writestr("status_distribution_pie.png", status_buf.read())
        zipf.writestr("report_summary.pdf", pdf_buf.read())
    zip_buf.seek(0)

    return send_file(zip_buf, as_attachment=True, download_name="case_report_bundle.zip", mimetype="application/zip")

@app.route("/update/<case_number>", methods=["GET", "POST"])
def update_case(case_number):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        new_status = request.form["status"]
        new_date = request.form["date"]
        cur.execute("UPDATE cases SET status = ?, date = ? WHERE case_number = ?", (new_status, new_date, case_number))
        conn.commit()
        conn.close()
        flash("Case updated successfully!", "success")
        return redirect("/")

    cur.execute("SELECT * FROM cases WHERE case_number = ?", (case_number,))
    case = cur.fetchone()
    conn.close()

    if not case:
        flash("Case not found!", "error")
        return redirect("/")

    return render_template("update.html", case=case)


@app.route("/delete/<case_number>", methods=["POST"])
def delete_case(case_number):
    conn = get_db_connection()
    conn.execute("DELETE FROM cases WHERE case_number = ?", (case_number,))
    conn.commit()
    conn.close()
    flash("Case deleted successfully!", "success")
    return redirect("/")






if __name__ == "__main__":
    init_db()
  app.run(host='0.0.0.0', debug=True)

