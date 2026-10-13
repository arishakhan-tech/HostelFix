# HostelFix — Python edition

A Python/Flask + SQLite version of the original HostelFix project. The frontend uses familiar HTML, CSS and Jinja templates; no Node.js build step is required.

## Features
- Navy-sidebar dashboard UI with separate Maintenance, Laundry and Outpass pages for students and wardens
- Role-based Student, Warden and Gatekeeper dashboards
- Student maintenance complaints and urgent/normal priority
- Repeat-room flag when 3+ complaints are filed in the last 30 days
- Laundry pickup, status progression and student receipt confirmation
- Outpass request, demo OTP verification, warden approval/rejection
- Gate token scans for exit and entry, including automatic late-return flag
- Password hashing, session login and SQLite storage

## Run locally
Python 3.10+ recommended.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

Developed by Arisha Khan - built during internship at Talking Crooks IT Pvt. Ltd.

The database is created automatically on first run, with demo accounts (password for all: `password123`):
- `student@hostelfix.test`
- `warden@hostelfix.test`
- `gatekeeper@hostelfix.test`

## Project structure
```text
hostelfix_python/
  app.py                Flask routes, auth and SQLite data layer
  templates/
    base.html           App shell: navy sidebar, role-based nav, branding footer
    base_public.html    Logged-out shell (home, login, register, errors)
    _ui.html            Reusable macros: status pills, stat tiles, module tiles
    student_*.html      Student dashboard + Maintenance / Laundry / Outpass pages
    warden_*.html       Warden dashboard + Maintenance / Laundry / Outpass pages
    gatekeeper.html     Gate scan page with outpass log
  static/style.css      Theme (navy #1c3a63, orange #f5a13d) and responsive layout
  requirements.txt
  .env.example
```

## Notes before production
- Set a strong `SECRET_KEY` environment variable and disable Flask debug mode.
- The OTP is deliberately demo-only and shown in a flash message; it is not sent to a parent.
- The gatekeeper pastes the token rather than using a camera scanner.
- Add CSRF protection, rate limiting, audit logging, secure deployment settings and real SMS/WhatsApp integration before real-world use.
- The demo warden and gatekeeper accounts are seeded for local testing. Remove or replace these accounts before deployment.
