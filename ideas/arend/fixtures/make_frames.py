"""Builds fixtures/frames.json: what the Mac capture loop would see (OCR text
of the frontmost window every 2 seconds) during one real-looking task.

All names, numbers and accounts are made up. Raw frames include things that
must never be stored (an IBAN, an email, a password manager, a private window,
a bank) so the demo shows the same capture rules as live capture.
"""
import json
import os

EXCEL_ALL = """salary_export_oct.xlsx
Employee ID  Joint committee  Status  Gross monthly
E-1001  200  white-collar  3,412.00
E-1002  124  blue-collar  2,980.50
E-1003  200  white-collar  4,105.75
E-1004  302  blue-collar  2,711.20
E-1005  200  white-collar  3,690.00
Contact payroll: hr@bakkerij-janssens.be"""
EXCEL_FILTERED = EXCEL_ALL + """
Filter: Joint committee = 200
E-1001  200  white-collar  3,412.00
E-1003  200  white-collar  4,105.75
E-1005  200  white-collar  3,690.00"""
EXCEL_SUM = EXCEL_FILTERED + """
=SUM(D2:D41)
Total gross PC 200  48,213.50"""

MAIL = """Inbox
Subject: Indexation PC 200 per 1 November
From: Legal Watch <legalwatch@sdworx.example>
Salaries in joint committee 200 rise by 2.21% on 1 November.
Apply the new base to every PC 200 client before the November payroll run."""

PORTFOLIO = """mysdworx  Client portfolio
Bakkerij Janssens BV  PC 200  148 employees  Next payroll 25 Nov
Garage Peeters NV  PC 112  23 employees
Client account BE71 0961 2345 6769"""

INDEX_EMPTY = """mysdworx  Indexation PC 200
Client  Bakkerij Janssens BV
Indexation rate  2.21%
Total gross base  ______
Effective date  01/11/2026"""
INDEX_PASTED = INDEX_EMPTY.replace("______", "48213.50")
INDEX_SAVED = INDEX_PASTED + "\nSaved. Indexation of 2.21% scheduled for the November payroll."

REPORTS = """mysdworx  Reports
Period  October 2026
Report type  Payslips"""
REPORTS_FILTERED = REPORTS + "\nFilter: Period = October 2026"
REPORTS_DONE = REPORTS_FILTERED + "\nDownload complete: payslips_oct.zip"

frames = []
t = 0


def add(n, app, title, text, clipboard=None):
    global t
    for _ in range(n):
        f = {"t": t, "app": app, "title": title, "text": text}
        if clipboard:
            f["clipboard"] = clipboard
        frames.append(f)
        t += 2


CHROME = "Google Chrome"
add(3, "Microsoft Outlook", "Inbox - Indexation PC 200 per 1 November", MAIL)
add(2, "1Password", "1Password - mysdworx login", "mysdworx  user  ********")
add(2, "Microsoft Excel", "salary_export_oct.xlsx", EXCEL_ALL)
add(1, "Microsoft Excel", "Book2", "")  # a one-frame glance, dropped as noise
add(3, "Microsoft Excel", "salary_export_oct.xlsx", EXCEL_FILTERED)
add(2, "Microsoft Excel", "salary_export_oct.xlsx", EXCEL_SUM)
add(1, "Microsoft Excel", "salary_export_oct.xlsx", EXCEL_SUM, clipboard="48213.50")
add(2, CHROME, "Private Browsing - Gmail", "personal mail", clipboard="48213.50")
add(3, CHROME, "mysdworx - Client portfolio", PORTFOLIO, clipboard="48213.50")
add(2, CHROME, "mysdworx - Indexation PC 200", INDEX_EMPTY, clipboard="48213.50")
add(2, CHROME, "mysdworx - Indexation PC 200", INDEX_PASTED, clipboard="48213.50")
add(2, CHROME, "mysdworx - Indexation PC 200", INDEX_SAVED, clipboard="48213.50")
add(2, "Safari", "KBC Online Banking", "balance", clipboard="48213.50")
t += 900  # coffee: the next task is a separate procedure
add(2, CHROME, "mysdworx - Reports", REPORTS)
add(2, CHROME, "mysdworx - Reports", REPORTS_FILTERED)
add(2, CHROME, "mysdworx - Reports", REPORTS_DONE)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames.json")
with open(out, "w") as f:
    json.dump(frames, f, indent=1)
print(f"{len(frames)} frames -> {out}")
