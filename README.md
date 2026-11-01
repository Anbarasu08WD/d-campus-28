# D-campus — Student Success Platform

D-campus is a Flask and SQLite student success platform with two supported account types: **Student** and **Admin**. This version retains the existing Stitch-inspired interface, student theme customizer, academic tools and student attendance workflows with staff, mentor and advisor features removed entirely.

## Account workflow

- Student login: `/login` or `/student/login` → student dashboard.
- Admin login: `/admin/login` → administrator dashboard.
- The database role is authoritative; only `student` and `admin` roles exist.
- Admin can create and manage only Student and Admin accounts.

## Admin workspace

The administrator can manage student accounts, review academic performance, update marks, create class sessions, mark student attendance, review attendance, process student leave/OD applications, publish events and respond to feedback.

## Student workspace

Students retain the dashboard, attendance history, subject-wise attendance, attendance correction requests, education-level estimate, study planner, events, feedback and other existing student learning features.

## Attendance details

The student attendance page displays counts for Present, Absent, Late and Approved OD, an overall attendance rate, a 75% recommended target indicator, subject-wise attendance percentages, session history and a correction-request form. Present, Late and Approved OD count as attended for the overall rate. The target is a guidance indicator, not an institutional rule; adjust it to match your institution's policy if needed.

Administrators can use **Mark attendance** to create a class session and mark each student as Present, Absent, Late or Approved OD. The Attendance Overview page shows recorded sessions and attendance data.

## Student theme customizer

Students can select six accent palettes: **Blue, Light Pink, Light Green, Light Purple, Black and Teal**. The page background remains white. The preference is saved in the `users.theme` SQLite column and restored on the next login. Admin pages retain the default blue styling.

## Run on Windows / VS Code

Use Python 3.10+ (Python 3.12 is recommended where available).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-long-random-secret"
python app.py
```

Open `http://127.0.0.1:5000` in your browser. Back up `student_success.db` before replacing an existing project folder. Do not expose demo credentials or the database publicly.

## Demo accounts

Only the administrator account `admin@demo.com` is created automatically (if missing). Students register through the Create account page. To wipe all non-admin users from a database, run `python remove_non_admin_users.py`.

## Main files

- `app.py` — routes, authentication, role checks and workflows.
- `database.py` / `init_db.py` — SQLite schema and initialization.
- `analytics.py` / `recommendations.py` — academic calculations and recommendations.
- `templates/` — Flask/Jinja pages.
- `static/css/` and `static/js/` — Stitch-inspired UI, responsive styles and interactions.
- `templates/how_it_works.html` — public page explaining the prediction formula, with a live calculator that uses the same weights and bands as the backend.
- `tests/` — existing analytics tests.

## Notes

The education-level estimate is an indicative performance-based estimate, not an official qualification or guaranteed prediction. The application is a development project, not a production-ready student information system. Before deployment, configure a strong secret key, HTTPS, CSRF protection, secure hosting, database backups and institution-approved access policies. Respect reduced-motion preferences; the UI animations are intentionally subtle.
