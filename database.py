import sqlite3
from werkzeug.security import generate_password_hash
from flask import current_app, g


# ---------------------------------------------------------
# Database connection
# ---------------------------------------------------------

def get_db():
    if "db" not in g:
        database_path = current_app.config["DATABASE"]
        g.db = sqlite3.connect(database_path, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 30000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    """Register database connection cleanup with Flask."""
    app.teardown_appcontext(close_db)


# ---------------------------------------------------------
# Schema helpers and safe additive migrations
# ---------------------------------------------------------

def _table_columns(db, table_name):
    return {
        row["name"]
        for row in db.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }


def _add_column_if_missing(db, table_name, column_name, definition):
    columns = _table_columns(db, table_name)
    if columns and column_name not in columns:
        db.execute(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
        )


def _create_tables(db):
    """
    Create any missing tables. Index creation is deliberately handled after
    migrations so old tables can first receive columns used by those indexes.
    """
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student'
            CHECK (role IN ('student', 'admin')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS academic_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        marks REAL NOT NULL DEFAULT 0,
        max_marks REAL NOT NULL DEFAULT 100,
        attended_classes INTEGER NOT NULL DEFAULT 0,
        total_classes INTEGER NOT NULL DEFAULT 0,
        assignments_completed INTEGER NOT NULL DEFAULT 0,
        assignments_total INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE (student_id, subject)
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        due_date TEXT,
        completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS student_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        college TEXT NOT NULL DEFAULT '',
        registration_no TEXT NOT NULL DEFAULT '',
        roll_number TEXT NOT NULL DEFAULT '',
        department TEXT NOT NULL DEFAULT '',
        academic_year TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'General',
        is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS student_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        topic TEXT NOT NULL,
        message TEXT NOT NULL,
        career_goal TEXT NOT NULL DEFAULT '',
        skills_requested TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Received',
        admin_response TEXT NOT NULL DEFAULT '',
        responded_by INTEGER,
        responded_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (responded_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS class_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_date TEXT NOT NULL,
        subject TEXT NOT NULL,
        class_id TEXT NOT NULL DEFAULT '',
        start_time TEXT,
        end_time TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS student_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'Absent',
        remarks TEXT NOT NULL DEFAULT '',
        marked_by INTEGER,
        marked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (session_id) REFERENCES class_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (marked_by) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE (student_id, session_id)
    );

    CREATE TABLE IF NOT EXISTS attendance_correction_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attendance_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        decision_remarks TEXT NOT NULL DEFAULT '',
        decided_by INTEGER,
        decided_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (attendance_id) REFERENCES student_attendance(id) ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (decided_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS student_leave_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_user_id INTEGER NOT NULL,
        leave_type TEXT NOT NULL DEFAULT 'Other',
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending'
            CHECK (status IN ('Pending', 'Approved', 'Rejected')),
        decision_remarks TEXT NOT NULL DEFAULT '',
        decided_by INTEGER,
        decided_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_user_id)
            REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (decided_by)
            REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS student_od_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_user_id INTEGER NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'Official Duty',
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending'
            CHECK (status IN ('Pending', 'Approved', 'Rejected')),
        decision_remarks TEXT NOT NULL DEFAULT '',
        decided_by INTEGER,
        decided_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_user_id)
            REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (decided_by)
            REFERENCES users(id) ON DELETE SET NULL
    );


    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        details TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS college_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        event_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        venue TEXT NOT NULL DEFAULT '',
        created_by INTEGER,
        status TEXT NOT NULL DEFAULT 'Scheduled',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS skill_domains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'Technology',
        icon TEXT NOT NULL DEFAULT 'book',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS domain_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        skill_type TEXT NOT NULL DEFAULT 'Core',
        level TEXT NOT NULL DEFAULT 'Beginner',
        FOREIGN KEY (domain_id) REFERENCES skill_domains(id) ON DELETE CASCADE,
        UNIQUE (domain_id, name)
    );

    CREATE TABLE IF NOT EXISTS learning_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_id INTEGER,
        skill_id INTEGER,
        title TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT '',
        resource_type TEXT NOT NULL DEFAULT 'Course',
        url TEXT NOT NULL,
        level TEXT NOT NULL DEFAULT 'Beginner',
        description TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (domain_id) REFERENCES skill_domains(id) ON DELETE CASCADE,
        FOREIGN KEY (skill_id) REFERENCES domain_skills(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS student_learning_paths (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        domain_id INTEGER,
        skill_id INTEGER,
        goal TEXT NOT NULL,
        current_level TEXT NOT NULL DEFAULT 'Beginner',
        target_level TEXT NOT NULL DEFAULT 'Intermediate',
        target_date TEXT,
        status TEXT NOT NULL DEFAULT 'Active',
        completed_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (domain_id) REFERENCES skill_domains(id) ON DELETE SET NULL,
        FOREIGN KEY (skill_id) REFERENCES domain_skills(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS learning_milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learning_path_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'Not Started',
        completion_notes TEXT NOT NULL DEFAULT '',
        completed_at TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (learning_path_id) REFERENCES student_learning_paths(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS learning_progress_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learning_path_id INTEGER NOT NULL,
        milestone_id INTEGER,
        activity TEXT NOT NULL,
        hours_spent REAL NOT NULL DEFAULT 0,
        progress_percent INTEGER,
        reflection TEXT NOT NULL DEFAULT '',
        learned_items TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (learning_path_id) REFERENCES student_learning_paths(id) ON DELETE CASCADE,
        FOREIGN KEY (milestone_id) REFERENCES learning_milestones(id) ON DELETE SET NULL
    );
    """)


def _migrate_existing_tables(db):
    """
    Add missing columns to legacy tables without dropping tables or rows.
    ALTER TABLE defaults must be constant expressions, so timestamps added
    during migration use an empty string rather than CURRENT_TIMESTAMP.
    """
    # Legacy databases stored the creating admin as teacher_user_id; rename in place.
    legacy_cols = _table_columns(db, "class_sessions")
    if "teacher_user_id" in legacy_cols and "created_by" not in legacy_cols:
        db.execute('ALTER TABLE class_sessions RENAME COLUMN teacher_user_id TO created_by')

    additions = {
        "users": [
            ("name", "TEXT NOT NULL DEFAULT ''"),
            ("email", "TEXT NOT NULL DEFAULT ''"),
            ("password_hash", "TEXT NOT NULL DEFAULT ''"),
            ("role", "TEXT NOT NULL DEFAULT 'student'"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ("theme", "TEXT NOT NULL DEFAULT 'blue'"),
        ],
        "academic_records": [
            ("student_id", "INTEGER"),
            ("subject", "TEXT NOT NULL DEFAULT ''"),
            ("marks", "REAL NOT NULL DEFAULT 0"),
            ("max_marks", "REAL NOT NULL DEFAULT 100"),
            ("attended_classes", "INTEGER NOT NULL DEFAULT 0"),
            ("total_classes", "INTEGER NOT NULL DEFAULT 0"),
            ("assignments_completed", "INTEGER NOT NULL DEFAULT 0"),
            ("assignments_total", "INTEGER NOT NULL DEFAULT 0"),
        ],
        "tasks": [
            ("student_id", "INTEGER"),
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("due_date", "TEXT"),
            ("completed", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "student_profiles": [
            ("user_id", "INTEGER"),
            ("college", "TEXT NOT NULL DEFAULT ''"),
            ("registration_no", "TEXT NOT NULL DEFAULT ''"),
            ("roll_number", "TEXT NOT NULL DEFAULT ''"),
            ("department", "TEXT NOT NULL DEFAULT ''"),
            ("academic_year", "TEXT NOT NULL DEFAULT ''"),
            ("phone", "TEXT NOT NULL DEFAULT ''"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "notifications": [
            ("user_id", "INTEGER"),
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("message", "TEXT NOT NULL DEFAULT ''"),
            ("category", "TEXT NOT NULL DEFAULT 'General'"),
            ("is_read", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "student_feedback": [
            ("student_id", "INTEGER"),
            ("topic", "TEXT NOT NULL DEFAULT ''"),
            ("message", "TEXT NOT NULL DEFAULT ''"),
            ("career_goal", "TEXT NOT NULL DEFAULT ''"),
            ("skills_requested", "TEXT NOT NULL DEFAULT ''"),
            ("status", "TEXT NOT NULL DEFAULT 'Received'"),
            ("admin_response", "TEXT NOT NULL DEFAULT ''"),
            ("responded_by", "INTEGER"),
            ("responded_at", "TEXT"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "class_sessions": [
            ("session_date", "TEXT NOT NULL DEFAULT ''"),
            ("subject", "TEXT NOT NULL DEFAULT ''"),
            ("class_id", "TEXT NOT NULL DEFAULT ''"),
            ("start_time", "TEXT"),
            ("end_time", "TEXT"),
            ("created_by", "INTEGER"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "student_attendance": [
            ("student_id", "INTEGER"),
            ("session_id", "INTEGER"),
            ("status", "TEXT NOT NULL DEFAULT 'Absent'"),
            ("remarks", "TEXT NOT NULL DEFAULT ''"),
            ("marked_by", "INTEGER"),
            ("marked_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "attendance_correction_requests": [
            ("attendance_id", "INTEGER"),
            ("student_id", "INTEGER"),
            ("reason", "TEXT NOT NULL DEFAULT ''"),
            ("status", "TEXT NOT NULL DEFAULT 'Pending'"),
            ("decision_remarks", "TEXT NOT NULL DEFAULT ''"),
            ("decided_by", "INTEGER"),
            ("decided_at", "TEXT"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "audit_logs": [
            ("actor_user_id", "INTEGER"),
            ("action", "TEXT NOT NULL DEFAULT ''"),
            ("entity_type", "TEXT NOT NULL DEFAULT ''"),
            ("entity_id", "TEXT"),
            ("details", "TEXT NOT NULL DEFAULT ''"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "college_events": [
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("event_date", "TEXT NOT NULL DEFAULT ''"),
            ("start_time", "TEXT NOT NULL DEFAULT ''"),
            ("end_time", "TEXT"),
            ("venue", "TEXT NOT NULL DEFAULT ''"),
            ("created_by", "INTEGER"),
            ("status", "TEXT NOT NULL DEFAULT 'Scheduled'"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "skill_domains": [
            ("name", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("category", "TEXT NOT NULL DEFAULT 'Technology'"),
            ("icon", "TEXT NOT NULL DEFAULT 'book'"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "domain_skills": [
            ("domain_id", "INTEGER"),
            ("name", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("skill_type", "TEXT NOT NULL DEFAULT 'Core'"),
            ("level", "TEXT NOT NULL DEFAULT 'Beginner'"),
        ],
        "learning_resources": [
            ("domain_id", "INTEGER"),
            ("skill_id", "INTEGER"),
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("provider", "TEXT NOT NULL DEFAULT ''"),
            ("resource_type", "TEXT NOT NULL DEFAULT 'Course'"),
            ("url", "TEXT NOT NULL DEFAULT ''"),
            ("level", "TEXT NOT NULL DEFAULT 'Beginner'"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
        ],
        "student_learning_paths": [
            ("student_id", "INTEGER"),
            ("domain_id", "INTEGER"),
            ("skill_id", "INTEGER"),
            ("goal", "TEXT NOT NULL DEFAULT ''"),
            ("current_level", "TEXT NOT NULL DEFAULT 'Beginner'"),
            ("target_level", "TEXT NOT NULL DEFAULT 'Intermediate'"),
            ("target_date", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'Active'"),
            ("completed_at", "TEXT"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "learning_milestones": [
            ("learning_path_id", "INTEGER"),
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("due_date", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'Not Started'"),
            ("completion_notes", "TEXT NOT NULL DEFAULT ''"),
            ("completed_at", "TEXT"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
        "learning_progress_logs": [
            ("learning_path_id", "INTEGER"),
            ("milestone_id", "INTEGER"),
            ("activity", "TEXT NOT NULL DEFAULT ''"),
            ("hours_spent", "REAL NOT NULL DEFAULT 0"),
            ("progress_percent", "INTEGER"),
            ("reflection", "TEXT NOT NULL DEFAULT ''"),
            ("learned_items", "TEXT NOT NULL DEFAULT ''"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ],
    }

    for table_name, columns in additions.items():
        existing_columns = _table_columns(db, table_name)
        if not existing_columns:
            continue
        for column_name, definition in columns:
            if column_name not in existing_columns:
                db.execute(
                    f'ALTER TABLE "{table_name}" '
                    f'ADD COLUMN "{column_name}" {definition}'
                )
                existing_columns.add(column_name)


def _create_indexes(db):
    """Create indexes only after the columns they need have been migrated."""
    indexes = [
        ("idx_academic_student", "academic_records", "student_id"),
        ("idx_tasks_student", "tasks", "student_id"),
        ("idx_learning_paths_student", "student_learning_paths", "student_id"),
        ("idx_learning_paths_status", "student_learning_paths", "status"),
        ("idx_milestones_path", "learning_milestones", "learning_path_id"),
        ("idx_progress_path", "learning_progress_logs", "learning_path_id"),
        ("idx_notifications_user", "notifications", "user_id, created_at"),
        ("idx_feedback_student", "student_feedback", "student_id, created_at"),
        ("idx_attendance_student", "student_attendance", "student_id"),
        ("idx_audit_created", "audit_logs", "created_at"),
    ]
    for index_name, table_name, columns in indexes:
        if _table_columns(db, table_name):
            db.execute(
                f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                f'ON "{table_name}" ({columns})'
            )


# ---------------------------------------------------------
# Database setup
# ---------------------------------------------------------

def init_db():
    db = get_db()
    _create_tables(db)
    _migrate_existing_tables(db)
    _create_indexes(db)
    db.commit()


# ---------------------------------------------------------
# Demo data
# ---------------------------------------------------------

def seed_demo_data():
    """
    Create demo accounts only when they do not already exist.
    Never delete or reset existing user accounts or academic data.
    """
    db = get_db()
    demo_users = [
        ("Demo Administrator", "admin@demo.com", "AdminDemo123!", "admin"),
        ("Demo Student", "student@demo.com", "StudentDemo123!", "student"),
    ]

    for name, email, password, role in demo_users:
        existing = db.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing is None:
            db.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, generate_password_hash(password), role),
            )
    db.commit()

    student = db.execute(
        "SELECT id FROM users WHERE email = ? AND role = 'student'",
        ("student@demo.com",),
    ).fetchone()

    if student is not None:
        student_id = student["id"]
        sample_records = [
            ("Python Programming", 82, 100, 18, 20, 8, 10),
            ("Database Management", 74, 100, 16, 20, 7, 10),
            ("Mathematics", 61, 100, 15, 20, 6, 10),
        ]
        for (
            subject, marks, max_marks, attended, total,
            assignments_completed, assignments_total
        ) in sample_records:
            db.execute(
                """
                INSERT OR IGNORE INTO academic_records
                    (student_id, subject, marks, max_marks,
                     attended_classes, total_classes,
                     assignments_completed, assignments_total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id, subject, marks, max_marks, attended, total,
                    assignments_completed, assignments_total,
                ),
            )

        sample_tasks = [
            ("Revise Python functions", "2026-12-01"),
            ("Practise SQL queries", "2026-12-03"),
            ("Review mathematics notes", "2026-12-05"),
        ]
        for title, due_date in sample_tasks:
            db.execute(
                """
                INSERT INTO tasks (student_id, title, due_date, completed)
                SELECT ?, ?, ?, 0
                WHERE NOT EXISTS (
                    SELECT 1 FROM tasks
                    WHERE student_id = ? AND title = ?
                )
                """,
                (student_id, title, due_date, student_id, title),
            )
        db.commit()


# ---------------------------------------------------------
# Skills and learning resources seed data
# ---------------------------------------------------------

def seed_learning_data():
    db = get_db()

    domains = [
        ("Web Development", "Build responsive websites and web applications.",
         "Software Development", "globe"),
        ("AI and Machine Learning",
         "Learn data-driven models and intelligent applications.",
         "Artificial Intelligence", "brain"),
        ("Data Science", "Analyse data and communicate useful insights.",
         "Data and Analytics", "chart"),
        ("Cybersecurity", "Understand security principles and defensive practices.",
         "Security", "shield"),
        ("Cloud Computing", "Learn cloud infrastructure, services and deployment.",
         "Cloud and Infrastructure", "cloud"),
        ("Mobile App Development", "Create applications for mobile devices.",
         "Software Development", "smartphone"),
        ("UI and UX Design", "Design usable, accessible and consistent interfaces.",
         "Design", "palette"),
    ]

    for name, description, category, icon in domains:
        db.execute(
            """
            INSERT OR IGNORE INTO skill_domains
                (name, description, category, icon)
            VALUES (?, ?, ?, ?)
            """,
            (name, description, category, icon),
        )
    db.commit()

    skills_by_domain = {
        "Web Development": [
            ("HTML", "Structure web pages.", "Core", "Beginner"),
            ("CSS", "Style responsive interfaces.", "Core", "Beginner"),
            ("JavaScript", "Build interactive browser experiences.", "Core", "Beginner"),
            ("Flask", "Build web applications using Python.", "Framework", "Intermediate"),
            ("SQL", "Store and query structured data.", "Database", "Beginner"),
        ],
        "AI and Machine Learning": [
            ("Python for AI", "Use Python for data and AI workflows.", "Core", "Beginner"),
            ("Statistics", "Understand probability and statistical reasoning.", "Core", "Beginner"),
            ("Data Preparation", "Clean and prepare datasets.", "Core", "Intermediate"),
            ("Machine Learning", "Train and evaluate predictive models.", "Core", "Intermediate"),
        ],
        "Data Science": [
            ("Python Data Analysis", "Analyse datasets with Python.", "Core", "Beginner"),
            ("Pandas", "Transform and inspect tabular data.", "Library", "Beginner"),
            ("Data Visualisation", "Communicate findings with charts.", "Core", "Intermediate"),
            ("SQL Analytics", "Query data for analysis.", "Database", "Beginner"),
        ],
        "Cybersecurity": [
            ("Networking Basics", "Understand networks and protocols.", "Core", "Beginner"),
            ("Linux Basics", "Use Linux tools and commands.", "Core", "Beginner"),
            ("Security Fundamentals", "Learn authentication and defensive security.", "Core", "Beginner"),
            ("Web Security", "Understand common web vulnerabilities.", "Core", "Intermediate"),
        ],
        "Cloud Computing": [
            ("Cloud Fundamentals", "Learn cloud service models.", "Core", "Beginner"),
            ("Linux Administration", "Manage Linux systems.", "Core", "Intermediate"),
            ("Deployment", "Deploy and maintain applications.", "Core", "Intermediate"),
            ("Cloud Security", "Apply cloud access and security controls.", "Core", "Intermediate"),
        ],
        "Mobile App Development": [
            ("Programming Fundamentals", "Practise core programming concepts.", "Core", "Beginner"),
            ("Android Development", "Build Android applications.", "Platform", "Intermediate"),
            ("App UI Design", "Design clear mobile interfaces.", "Design", "Beginner"),
            ("API Integration", "Connect apps to web services.", "Core", "Intermediate"),
        ],
        "UI and UX Design": [
            ("Design Principles", "Apply layout, hierarchy and contrast.", "Core", "Beginner"),
            ("Wireframing", "Plan screens and user flows.", "Core", "Beginner"),
            ("Prototyping", "Create interactive design prototypes.", "Core", "Intermediate"),
            ("Usability Testing", "Evaluate designs with user feedback.", "Core", "Intermediate"),
        ],
    }

    for domain_name, domain_skills in skills_by_domain.items():
        domain = db.execute(
            "SELECT id FROM skill_domains WHERE name = ?", (domain_name,)
        ).fetchone()
        if domain is None:
            continue
        for skill_name, description, skill_type, level in domain_skills:
            db.execute(
                """
                INSERT OR IGNORE INTO domain_skills
                    (domain_id, name, description, skill_type, level)
                VALUES (?, ?, ?, ?, ?)
                """,
                (domain["id"], skill_name, description, skill_type, level),
            )
    db.commit()

    resources = [
        ("Web Development", "HTML", "MDN HTML Guide", "MDN Web Docs",
         "Documentation",
         "https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Structuring_content",
         "Beginner"),
        ("Web Development", "CSS", "MDN CSS Guide", "MDN Web Docs",
         "Documentation",
         "https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Styling_basics",
         "Beginner"),
        ("Web Development", "JavaScript", "JavaScript Guide", "MDN Web Docs",
         "Documentation",
         "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
         "Beginner"),
        ("AI and Machine Learning", "Machine Learning",
         "Google Machine Learning Crash Course", "Google", "Course",
         "https://developers.google.com/machine-learning/crash-course",
         "Intermediate"),
        ("Data Science", "Pandas", "Pandas Getting Started", "Pandas",
         "Documentation",
         "https://pandas.pydata.org/docs/getting_started/index.html",
         "Beginner"),
        ("Cybersecurity", "Security Fundamentals", "Cisco Networking Academy",
         "Cisco", "Course", "https://www.netacad.com/", "Beginner"),
        ("Cloud Computing", "Cloud Fundamentals", "Microsoft Learn",
         "Microsoft", "Learning Path", "https://learn.microsoft.com/training/",
         "Beginner"),
        ("Mobile App Development", "Android Development",
         "Android Developers Training", "Google", "Documentation",
         "https://developer.android.com/courses", "Beginner"),
        ("UI and UX Design", "Prototyping", "Figma Learn", "Figma", "Tutorial",
         "https://help.figma.com/hc/en-us/categories/360002051613-Learn-design",
         "Beginner"),
    ]

    for domain_name, skill_name, title, provider, resource_type, url, level in resources:
        domain = db.execute(
            "SELECT id FROM skill_domains WHERE name = ?", (domain_name,)
        ).fetchone()
        skill = None
        if domain is not None:
            skill = db.execute(
                """
                SELECT id FROM domain_skills
                WHERE domain_id = ? AND name = ?
                """,
                (domain["id"], skill_name),
            ).fetchone()
        if domain is None:
            continue
        db.execute(
            """
            INSERT INTO learning_resources
                (domain_id, skill_id, title, provider, resource_type,
                 url, level, description)
            SELECT ?, ?, ?, ?, ?, ?, ?, ''
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE domain_id = ? AND title = ?
            )
            """,
            (
                domain["id"], skill["id"] if skill else None,
                title, provider, resource_type, url, level,
                domain["id"], title,
            ),
        )
    db.commit()
