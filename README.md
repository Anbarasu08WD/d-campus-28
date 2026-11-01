# D-Campus — Student Management System

D-Campus is a web-based student management system designed to help educational institutions manage student information, academic records, attendance, and student activities through separate administrator and student portals.

## Live Demo

- **Website:** [Add your Vercel URL]
- **GitHub Repository:** [Add your GitHub repository URL]

## Features

### Administrator
- Admin authentication and dashboard
- Student account and academic record management
- Attendance session creation and attendance marking
- Attendance reports and correction request review
- Leave and On-Duty (OD) application review
- Student feedback management
- College event and notification management

### Student
- Student registration and authentication
- Dashboard with academic and attendance information
- Attendance history and correction requests
- Leave and OD applications
- Academic performance tracking
- Feedback submission
- College events and notifications

## Technology Stack

- **Backend:** Python, Flask
- **Database:** PostgreSQL (Neon)
- **Database Driver:** Psycopg 3
- **Frontend:** HTML, CSS, JavaScript, Jinja2
- **Authentication:** Flask sessions and Werkzeug password hashing
- **Deployment:** Vercel
- **Version Control:** Git and GitHub

## Project Structure

```text
D-campus/
├── app.py
├── database.py
├── analytics.py
├── migrate_sqlite_to_neon.py
├── requirements.txt
├── templates/
├── static/
├── .env
└── README.md
```

## Local Setup

### Requirements

- Python 3.10 or newer
- PostgreSQL database (Neon recommended)
- Git

### 1. Clone the repository

```bash
git clone <your-github-repository-url>
cd D-campus
```

### 2. Create and activate a virtual environment

**Windows PowerShell:**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL="your_neon_postgresql_connection_string"
SECRET_KEY="your_secret_key"
```

Keep `.env` private. Do not commit it to GitHub.

### 5. Run the application

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

## Database

D-Campus uses PostgreSQL hosted on Neon for persistent data storage. The application initializes its database schema and seeds required learning data when it starts.

The project also includes a migration script for transferring existing SQLite application data into Neon:

```bash
python migrate_sqlite_to_neon.py
```

**Warning:** The migration script replaces matching application tables in Neon. Back up your database before running it.

## Deployment

The application is deployed on Vercel.

Configure the following environment variables in your Vercel project settings:

- `DATABASE_URL`
- `SECRET_KEY`

Set them for the Production environment, then deploy the project.

## Security Notes

- Never commit `.env` files, database credentials, or private keys.
- Use a strong, unique `SECRET_KEY` in production.
- Use secure passwords for administrator and student accounts.
- Keep database backups before performing migrations.

## License

Add the license applicable to your project here.
