import os
import re
import psycopg
from datetime import date, datetime
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, abort, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from database import (
    init_db,
    get_db,
    seed_demo_data,
    seed_learning_data,
)
from analytics import calculate_performance


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "dev-only-change-this-secret-key"
)

# PostgreSQL connection is read from DATABASE_URL (Neon in production).


ROLES = {"student", "admin"}
ATTENDANCE_STATUSES = {"Present", "Absent", "Late", "Approved OD"}
APPLICATION_STATUSES = {"Pending", "Approved", "Rejected", "Cancelled"}
LEARNING_STATUSES = {"Active", "Paused", "Completed", "Cancelled"}


# ---------------------------------------------------------
# Database initialization
# ---------------------------------------------------------

with app.app_context():
    init_db()
    seed_demo_data()
    seed_learning_data()


# ---------------------------------------------------------
# Authentication and permissions
# ---------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))

            if session.get("role") not in allowed_roles:
                abort(403)

            return view(*args, **kwargs)
        return wrapped
    return decorator


admin_required = role_required("admin")


def current_user():
    if not session.get("user_id"):
        return None

    return get_db().execute(
        "SELECT id, name, email, role FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()


def require_valid_date(value):
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def safe_redirect_target(target, fallback):
    if not target:
        return fallback

    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return fallback

    return target


def audit_action(action, entity_type, entity_id=None, details=""):
    """Record an action when the audit table is available."""
    db = get_db()

    try:
        db.execute(
            """
            INSERT INTO audit_logs
                (actor_user_id, action, entity_type, entity_id,
                 details, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                session.get("user_id"),
                action,
                entity_type,
                str(entity_id) if entity_id is not None else None,
                details[:1000],
            ),
        )
    except psycopg.OperationalError:
        # The final database migration will create this table.
        # Do not pretend an audit record was saved.
        app.logger.warning("Audit table is not available yet.")

 
# ---------------------------------------------------------
# Public pages and authentication
# ---------------------------------------------------------

@app.route("/")
def index():
    """Public landing page for visitors; authenticated users go to their own workspace."""
    if session.get("user_id"):
        return redirect(url_for("role_home"))
    return render_template("index.html")


@app.route("/how-it-works")
def how_it_works():
    """Public explanation of how the performance prediction is calculated."""
    return render_template("how_it_works.html")


@app.route("/home")
@login_required
def role_home():
    """Role-aware Home destination used by all authenticated navigation."""
    role = str(session.get("role", "student")).strip().lower()
    destinations = {"student": "dashboard", "admin": "admin"}
    endpoint = destinations.get(role)
    if role not in {"student", "admin"}:
        session.clear()
        flash("Only Student and Admin accounts can sign in. Please contact the administrator.", "warning")
        return redirect(url_for("login"))
    if endpoint is None:
        session.clear()
        flash("Your account role is not recognized. Please sign in again.", "danger")
        return redirect(url_for("login"))
    return redirect(url_for(endpoint))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        college = request.form.get("college", "").strip()
        registration_no = request.form.get("registration_no", "").strip()

        if len(name) < 2:
            flash("Enter your full name.", "danger")
            return render_template("register.html")

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "danger")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return render_template("register.html")

        db = get_db()

        try:
            cursor = db.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, 'student')
                """,
                (name, email, generate_password_hash(password)),
            )

            student_id = cursor.lastrowid

            # Optional profile fields are stored only after the
            # profile table is created in the database migration.
            try:
                db.execute(
                    """
                    INSERT INTO student_profiles
                        (user_id, college, registration_no)
                    VALUES (?, ?, ?)
                    """,
                    (student_id, college, registration_no),
                )
            except psycopg.OperationalError:
                pass

            db.commit()

        except psycopg.IntegrityError:
            db.rollback()
            flash("That email is already registered.", "warning")
            return render_template("register.html")

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


def _login_for_roles(login_type, allowed_roles, default_endpoint):
    """Shared credential check with server-enforced portal role restrictions."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE lower(email) = ?",
            (email,),
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            role = str(user["role"] or "").strip().lower()
            if role not in allowed_roles:
                # Never trust a role selected in the browser. The database role is authoritative.
                if role == "admin":
                    message = "This is an administrator account. Please use the Admin Login page."
                    category = "warning"
                else:
                    message = "This account cannot access that portal. Use the login page for your account type."
                    category = "danger"
                flash(message, category)
                return render_template("login.html", login_type=login_type)

            # Clear any stale identity first, then establish a session from the database record.
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            session["role"] = role
            session["theme"] = user["theme"] if "theme" in user.keys() and user["theme"] in {"blue", "pink", "green", "purple", "black", "teal"} else "blue"

            destinations = {"student": "dashboard", "admin": "admin"}
            return redirect(url_for(destinations.get(role, default_endpoint)))

        flash("Email or password is incorrect.", "danger")

    return render_template("login.html", login_type=login_type)


@app.route("/login", methods=["GET", "POST"])
@app.route("/student/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("role_home"))
    return _login_for_roles("student", {"student"}, "dashboard")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("user_id"):
        if str(session.get("role", "")).lower() == "admin":
            return redirect(url_for("admin"))
        return redirect(url_for("role_home"))
    return _login_for_roles("admin", {"admin"}, "admin")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/student/theme", methods=["POST"])
@login_required
@role_required("student")
def save_student_theme():
    """Persist a student's accent theme without changing the white page background."""
    allowed_themes = {"blue", "pink", "green", "purple", "black", "teal"}
    payload = request.get_json(silent=True) or request.form
    theme = str(payload.get("theme", "")).strip().lower()
    if theme not in allowed_themes:
        return jsonify({"ok": False, "error": "Choose one of the available themes."}), 400

    db = get_db()
    db.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, session["user_id"]))
    db.commit()
    session["theme"] = theme
    return jsonify({"ok": True, "theme": theme})


# ---------------------------------------------------------
# Student dashboard and academic analytics
# ---------------------------------------------------------

def get_student_metrics(student_id):
    db = get_db()

    records = db.execute(
        """
        SELECT * FROM academic_records
        WHERE student_id = ?
        ORDER BY subject
        """,
        (student_id,),
    ).fetchall()

    tasks = db.execute(
        """
        SELECT * FROM tasks
        WHERE student_id = ?
        ORDER BY completed, due_date
        """,
        (student_id,),
    ).fetchall()

    metrics = calculate_performance([dict(row) for row in records])
    metrics["tasks_total"] = len(tasks)
    metrics["tasks_pending"] = sum(not task["completed"] for task in tasks)
    metrics["tasks_completed"] = sum(bool(task["completed"]) for task in tasks)

    return metrics, records, tasks



@app.route("/dashboard")
@login_required
@role_required("student")
def dashboard():
    student_id = session["user_id"]
    metrics, records, tasks = get_student_metrics(student_id)
    db = get_db()

    try:
        paths = db.execute(
            """
            SELECT p.*, d.name AS domain_name, s.name AS skill_name
            FROM student_learning_paths p
            LEFT JOIN skill_domains d ON d.id = p.domain_id
            LEFT JOIN domain_skills s ON s.id = p.skill_id
            WHERE p.student_id = ?
            ORDER BY p.updated_at DESC
            LIMIT 5
            """,
            (student_id,),
        ).fetchall()
    except psycopg.OperationalError:
        paths = []

    try:
        notifications = db.execute(
            """
            SELECT * FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (student_id,),
        ).fetchall()
    except psycopg.OperationalError:
        notifications = []

    # Convert SQLite Row objects to ordinary dictionaries.
    records = [dict(row) for row in records]
    tasks = [dict(row) for row in tasks[:5]]
    paths = [dict(row) for row in paths]
    notifications = [dict(row) for row in notifications]

    return render_template(
        "dashboard.html",
        metrics=metrics,
        records=records,
        tasks=tasks,
        learning_paths=paths,
        notifications=notifications,
        average=metrics.get("average", 0),
        attendance=metrics.get("attendance", 0),
        assignment_rate=metrics.get("assignment_rate", 0),
        focus_areas=metrics.get("focus_areas", []),
    )



@app.route("/education-level")
@login_required
@role_required("student")
def education_level():
    metrics, records, _tasks = get_student_metrics(session["user_id"])
    average = float(metrics.get("average") or 0)
    attendance = float(metrics.get("attendance") or 0)
    assignments = float(metrics.get("assignment_rate") or 0)
    count = len(records)
    if count == 0:
        level, label, detail, confidence = "Not enough data", "Add academic records", "Your education level estimate will appear after marks are entered by the administrator.", "Low"
    else:
        score = average * 0.60 + attendance * 0.25 + assignments * 0.15
        if score >= 85: level, label, detail = "Advanced progress", "Strong academic progress", "Your recorded performance is currently in the advanced range. Keep your consistency and maintain subject balance."
        elif score >= 70: level, label, detail = "On track", "Good academic progress", "Your current records indicate steady progress. Strengthen the subjects with lower scores to move toward the advanced range."
        elif score >= 50: level, label, detail = "Developing", "Progress needs attention", "You are building your academic foundation. Focus on regular attendance, assignments, and targeted revision."
        else: level, label, detail = "Needs support", "A focused improvement plan is recommended", "Your current records suggest that additional academic support and a consistent study routine may help."
        confidence = "Moderate" if count >= 3 else "Limited"
    return render_template("education_level.html", metrics=metrics, level=level, label=label, detail=detail, confidence=confidence, record_count=count)


@app.route("/planner", methods=["GET", "POST"])
@login_required
@role_required("student")
def planner():
    db = get_db()
    student_id = session["user_id"]

    if request.method == "POST":
        action = request.form.get("action", "add")

        if action == "add":
            title = request.form.get("title", "").strip()
            due_date = request.form.get("due_date", "").strip() or None

            if not title:
                flash("Enter a task title.", "danger")
            elif due_date and not require_valid_date(due_date):
                flash("Enter a valid due date.", "danger")
            else:
                db.execute(
                    """
                    INSERT INTO tasks (student_id, title, due_date, completed)
                    VALUES (?, ?, ?, 0)
                    """,
                    (student_id, title[:120], due_date),
                )
                db.commit()
                flash("Study task added.", "success")

        elif action in {"toggle", "delete"}:
            task_id = request.form.get("task_id", type=int)

            if task_id:
                task = db.execute(
                    "SELECT * FROM tasks WHERE id = ? AND student_id = ?",
                    (task_id, student_id),
                ).fetchone()

                if task and action == "toggle":
                    db.execute(
                        "UPDATE tasks SET completed = ? WHERE id = ?",
                        (0 if task["completed"] else 1, task_id),
                    )
                    db.commit()
                    flash("Task updated.", "success")

                elif task and action == "delete":
                    db.execute(
                        "DELETE FROM tasks WHERE id = ? AND student_id = ?",
                        (task_id, student_id),
                    )
                    db.commit()
                    flash("Task deleted.", "info")

        return redirect(url_for("planner"))

    tasks = db.execute(
        """
        SELECT * FROM tasks
        WHERE student_id = ?
        ORDER BY completed, due_date IS NULL, due_date, id DESC
        """,
        (student_id,),
    ).fetchall()

    return render_template("planner.html", tasks=tasks)


# ---------------------------------------------------------
# Skills and career-domain learning tracker
# ---------------------------------------------------------

@app.route("/skills")
@login_required
@role_required("student")
def skills():
    # The Skills page has been removed from the student experience. Keep the
    # underlying learning data intact because learning paths may reference it.
    flash("The Skills page is no longer available.", "info")
    return redirect(url_for("dashboard"))


@app.route("/skills/domains/<int:domain_id>")
@login_required
@role_required("student")
def domain_detail(domain_id):
    # Keep old bookmarks safe without exposing the removed Skills experience.
    flash("The Skills pages are no longer available.", "info")
    return redirect(url_for("dashboard"))


@app.route("/skills/<int:skill_id>")
@login_required
@role_required("student")
def skill_detail(skill_id):
    # Keep old bookmarks safe without exposing the removed Skills experience.
    flash("The Skills pages are no longer available.", "info")
    return redirect(url_for("dashboard"))


@app.route("/learning-paths/create", methods=["POST"])
@login_required
@role_required("student")
def create_learning_path():
    db = get_db()
    student_id = session["user_id"]

    domain_id = request.form.get("domain_id", type=int)
    skill_id = request.form.get("skill_id", type=int)
    goal = request.form.get("goal", "").strip()
    current_level = request.form.get("current_level", "Beginner")
    target_level = request.form.get("target_level", "Intermediate")
    target_date = request.form.get("target_date", "").strip() or None

    levels = {"Beginner", "Intermediate", "Advanced"}

    if not goal:
        flash("Describe what you want to achieve.", "danger")
        return redirect(url_for("dashboard"))

    if current_level not in levels or target_level not in levels:
        abort(400)

    if not domain_id and not skill_id:
        flash("Select a domain or skill first.", "warning")
        return redirect(url_for("dashboard"))

    if target_date and not require_valid_date(target_date):
        flash("Enter a valid target date.", "danger")
        return redirect(url_for("dashboard"))

    if domain_id and not db.execute(
        "SELECT id FROM skill_domains WHERE id = ?", (domain_id,)
    ).fetchone():
        abort(404)

    if skill_id and not db.execute(
        "SELECT id FROM domain_skills WHERE id = ?", (skill_id,)
    ).fetchone():
        abort(404)

    cursor = db.execute(
        """
        INSERT INTO student_learning_paths
            (student_id, domain_id, skill_id, goal, current_level,
             target_level, target_date, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Active')
        """,
        (
            student_id, domain_id, skill_id, goal[:500],
            current_level, target_level, target_date,
        ),
    )

    db.commit()

    audit_action(
        "learning_path_created",
        "student_learning_paths",
        cursor.lastrowid,
        "Student created a learning goal.",
    )
    db.commit()

    flash("Your learning plan has been created.", "success")
    return redirect(url_for("learning_path_detail", path_id=cursor.lastrowid))


@app.route("/learning-paths/<int:path_id>")
@login_required
@role_required("student")
def learning_path_detail(path_id):
    db = get_db()

    path = db.execute(
        """
        SELECT p.*, d.name AS domain_name, s.name AS skill_name
        FROM student_learning_paths p
        LEFT JOIN skill_domains d ON d.id = p.domain_id
        LEFT JOIN domain_skills s ON s.id = p.skill_id
        WHERE p.id = ? AND p.student_id = ?
        """,
        (path_id, session["user_id"]),
    ).fetchone()

    if path is None:
        abort(404)

    milestones = db.execute(
        """
        SELECT * FROM learning_milestones
        WHERE learning_path_id = ?
        ORDER BY sort_order, id
        """,
        (path_id,),
    ).fetchall()

    progress_logs = db.execute(
        """
        SELECT * FROM learning_progress_logs
        WHERE learning_path_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (path_id,),
    ).fetchall()

    completed = sum(m["status"] == "Completed" for m in milestones)
    progress = round(completed / len(milestones) * 100) if milestones else 0

    return render_template(
        "learning_path_detail.html",
        path=path,
        milestones=milestones,
        progress_logs=progress_logs,
        progress=progress,
    )


@app.route("/learning-paths/<int:path_id>/milestones/add", methods=["POST"])
@login_required
@role_required("student")
def add_milestone(path_id):
    db = get_db()

    path = db.execute(
        "SELECT id FROM student_learning_paths WHERE id = ? AND student_id = ?",
        (path_id, session["user_id"]),
    ).fetchone()

    if path is None:
        abort(404)

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    due_date = request.form.get("due_date", "").strip() or None

    if not title:
        flash("Enter a milestone title.", "danger")
        return redirect(url_for("learning_path_detail", path_id=path_id))

    if due_date and not require_valid_date(due_date):
        flash("Enter a valid milestone date.", "danger")
        return redirect(url_for("learning_path_detail", path_id=path_id))

    db.execute(
        """
        INSERT INTO learning_milestones
            (learning_path_id, title, description, due_date, sort_order)
        VALUES (?, ?, ?, ?, (
            SELECT COALESCE(MAX(sort_order), 0) + 1
            FROM learning_milestones WHERE learning_path_id = ?
        ))
        """,
        (path_id, title[:200], description[:2000], due_date, path_id),
    )

    db.commit()
    flash("Milestone added.", "success")
    return redirect(url_for("learning_path_detail", path_id=path_id))


@app.route("/learning-paths/<int:path_id>/milestones/<int:milestone_id>/update",
           methods=["POST"])
@login_required
@role_required("student")
def update_milestone(path_id, milestone_id):
    db = get_db()

    milestone = db.execute(
        """
        SELECT m.*
        FROM learning_milestones m
        JOIN student_learning_paths p ON p.id = m.learning_path_id
        WHERE m.id = ? AND p.id = ? AND p.student_id = ?
        """,
        (milestone_id, path_id, session["user_id"]),
    ).fetchone()

    if milestone is None:
        abort(404)

    status = request.form.get("status", "")
    notes = request.form.get("completion_notes", "").strip()

    if status not in {"Not Started", "In Progress", "Completed"}:
        abort(400)

    completed_at = datetime.now().isoformat(timespec="seconds") if status == "Completed" else None

    db.execute(
        """
        UPDATE learning_milestones
        SET status = ?, completion_notes = ?, completed_at = ?
        WHERE id = ?
        """,
        (status, notes[:2000], completed_at, milestone_id),
    )

    db.execute(
        """
        UPDATE student_learning_paths
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (path_id,),
    )

    db.commit()
    flash("Milestone progress updated.", "success")
    return redirect(url_for("learning_path_detail", path_id=path_id))


@app.route("/learning-paths/<int:path_id>/progress", methods=["POST"])
@login_required
@role_required("student")
def log_learning_progress(path_id):
    db = get_db()

    path = db.execute(
        "SELECT id FROM student_learning_paths WHERE id = ? AND student_id = ?",
        (path_id, session["user_id"]),
    ).fetchone()

    if path is None:
        abort(404)

    activity = request.form.get("activity", "").strip()
    learned_items = request.form.get("learned_items", "").strip()
    reflection = request.form.get("reflection", "").strip()
    milestone_id = request.form.get("milestone_id", type=int)
    progress_percent = request.form.get("progress_percent", type=int)

    try:
        hours_spent = float(request.form.get("hours_spent", "0"))
    except ValueError:
        hours_spent = -1

    if not activity or hours_spent < 0 or hours_spent > 24:
        flash("Enter an activity and valid learning hours.", "danger")
        return redirect(url_for("learning_path_detail", path_id=path_id))

    if progress_percent is not None and not 0 <= progress_percent <= 100:
        abort(400)

    if milestone_id:
        valid_milestone = db.execute(
            """
            SELECT id FROM learning_milestones
            WHERE id = ? AND learning_path_id = ?
            """,
            (milestone_id, path_id),
        ).fetchone()

        if valid_milestone is None:
            abort(404)

    db.execute(
        """
        INSERT INTO learning_progress_logs
            (learning_path_id, milestone_id, activity, hours_spent,
             progress_percent, reflection, learned_items)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            path_id, milestone_id, activity[:300], hours_spent,
            progress_percent, reflection[:2000], learned_items[:2000],
        ),
    )

    db.execute(
        """
        UPDATE student_learning_paths
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (path_id,),
    )

    db.commit()
    flash("Learning progress saved.", "success")
    return redirect(url_for("learning_path_detail", path_id=path_id))


@app.route("/learning-paths/<int:path_id>/status", methods=["POST"])
@login_required
@role_required("student")
def update_learning_path_status(path_id):
    db = get_db()
    status = request.form.get("status", "")

    if status not in LEARNING_STATUSES:
        abort(400)

    path = db.execute(
        """
        SELECT id FROM student_learning_paths
        WHERE id = ? AND student_id = ?
        """,
        (path_id, session["user_id"]),
    ).fetchone()

    if path is None:
        abort(404)

    completed_at = datetime.now().isoformat(timespec="seconds") if status == "Completed" else None

    db.execute(
        """
        UPDATE student_learning_paths
        SET status = ?, completed_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND student_id = ?
        """,
        (status, completed_at, path_id, session["user_id"]),
    )
    db.commit()

    flash("Learning plan status updated.", "success")
    return redirect(url_for("learning_path_detail", path_id=path_id))


# ---------------------------------------------------------
# Student feedback
# ---------------------------------------------------------

@app.route("/feedback", methods=["GET", "POST"])
@login_required
@role_required("student")
def feedback():
    db = get_db()

    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        message = request.form.get("message", "").strip()
        career_goal = request.form.get("career_goal", "").strip()
        skills_requested = request.form.get("skills_requested", "").strip()

        if not topic or not message:
            flash("Enter a topic and your feedback.", "danger")
        else:
            db.execute(
                """
                INSERT INTO student_feedback
                    (student_id, topic, message, career_goal,
                     skills_requested, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'Received', CURRENT_TIMESTAMP)
                """,
                (
                    session["user_id"], topic[:200], message[:5000],
                    career_goal[:1000], skills_requested[:2000],
                ),
            )
            db.commit()
            flash("Your feedback has been submitted privately.", "success")
            return redirect(url_for("feedback"))

    items = db.execute(
        """
        SELECT f.*, r.name AS responder_name
        FROM student_feedback f
        LEFT JOIN users r ON r.id = f.responded_by
        WHERE f.student_id = ?
        ORDER BY f.created_at DESC
        """,
        (session["user_id"],),
    ).fetchall()

    return render_template("feedback.html", feedback_items=items)


# ---------------------------------------------------------
# Student attendance and correction requests
# ---------------------------------------------------------

@app.route("/attendance")
@login_required
@role_required("student")
def student_attendance():
    records = get_db().execute(
        """
        SELECT a.*, s.session_date, s.subject, s.class_id
        FROM student_attendance a
        JOIN class_sessions s ON s.id = a.session_id
        WHERE a.student_id = ?
        ORDER BY s.session_date DESC
        """,
        (session["user_id"],),
    ).fetchall()

    subject_summary = get_db().execute(
        """
        SELECT s.subject,
               COUNT(*) AS total_sessions,
               SUM(CASE WHEN a.status IN ('Present', 'Late', 'Approved OD') THEN 1 ELSE 0 END) AS attended_sessions,
               SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END) AS absent_sessions
        FROM student_attendance a
        JOIN class_sessions s ON s.id = a.session_id
        WHERE a.student_id = ?
        GROUP BY s.subject
        ORDER BY s.subject
        """,
        (session["user_id"],),
    ).fetchall()

    return render_template(
        "attendance.html",
        attendance_records=records,
        attendance_by_subject=subject_summary,
    )


@app.route("/attendance/correction", methods=["POST"])
@login_required
@role_required("student")
def attendance_correction():
    db = get_db()
    session_id = request.form.get("session_id", type=int)
    reason = request.form.get("reason", "").strip()

    record = db.execute(
        """
        SELECT id FROM student_attendance
        WHERE student_id = ? AND session_id = ?
        """,
        (session["user_id"], session_id),
    ).fetchone()

    if record is None or not reason:
        flash("Select a valid attendance record and explain the request.", "danger")
        return redirect(url_for("student_attendance"))

    db.execute(
        """
        INSERT INTO attendance_correction_requests
            (attendance_id, student_id, reason, status, created_at)
        VALUES (?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
        """,
        (record["id"], session["user_id"], reason[:2000]),
    )
    db.commit()

    flash("Your correction request was submitted.", "success")
    return redirect(url_for("student_attendance"))


# ---------------------------------------------------------
# Admin dashboard and student academics
# ---------------------------------------------------------

@app.route("/admin", methods=["GET", "POST"])
@login_required
@admin_required
def admin():
    db = get_db()

    if request.method == "POST":
        record_id = request.form.get("record_id", type=int)
        student_id = request.form.get("student_id", type=int)
        marks = request.form.get("marks", type=float)
        attended = request.form.get("attended_classes", type=int)
        total = request.form.get("total_classes", type=int)

        if (
            record_id and student_id and marks is not None
            and attended is not None and total is not None
            and total > 0 and 0 <= marks <= 100
            and 0 <= attended <= total
        ):
            old = db.execute(
                """
                SELECT * FROM academic_records
                WHERE id = ? AND student_id = ?
                """,
                (record_id, student_id),
            ).fetchone()

            if old is None:
                abort(404)

            db.execute(
                """
                UPDATE academic_records
                SET marks = ?, attended_classes = ?, total_classes = ?
                WHERE id = ? AND student_id = ?
                """,
                (marks, attended, total, record_id, student_id),
            )

            audit_action(
                "academic_record_updated",
                "academic_records",
                record_id,
                f"Marks {old['marks']} -> {marks}; "
                f"attendance {old['attended_classes']}/{old['total_classes']} "
                f"-> {attended}/{total}",
            )

            db.commit()
            flash("Academic record updated.", "success")
        else:
            flash("Check the marks and attendance values.", "danger")

        return redirect(url_for("admin"))

    students = db.execute(
        """
        SELECT id, name, email FROM users
        WHERE role = 'student' ORDER BY name
        """
    ).fetchall()

    records = db.execute(
        """
        SELECT ar.*, u.name AS student_name
        FROM academic_records ar
        JOIN users u ON u.id = ar.student_id
        WHERE u.role = 'student'
        ORDER BY u.name, ar.subject
        """
    ).fetchall()

    summary = []

    for student in students:
        rows = db.execute(
            "SELECT * FROM academic_records WHERE student_id = ?",
            (student["id"],),
        ).fetchall()

        metrics = calculate_performance([dict(row) for row in rows])

        summary.append({
            "id": student["id"],
            "name": student["name"],
            "email": student["email"],
            "average": metrics["average"],
            "attendance": metrics["attendance"],
        })

    counts = {"students": len(students)}

    return render_template(
        "admin.html",
        students=students,
        records=records,
        summary=summary,
        counts=counts,
    )


# ---------------------------------------------------------
# Admin: manage student and administrator accounts
# ---------------------------------------------------------

@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def admin_users():
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        if role not in ROLES or len(name) < 2:
            flash("Check the name and role.", "danger")
            return redirect(url_for("admin_users"))

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "danger")
            return redirect(url_for("admin_users"))

        if len(password) < 8:
            flash("The initial password must contain at least 8 characters.", "danger")
            return redirect(url_for("admin_users"))
        try:
            cursor = db.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, generate_password_hash(password), role),
            )

            user_id = cursor.lastrowid

            db.commit()

            audit_action(
                "user_created",
                "users",
                user_id,
                f"Role: {role}",
            )
            db.commit()
            flash("User account created.", "success")

        except psycopg.IntegrityError:
            db.rollback()
            flash("That email is already registered.", "warning")

    users = db.execute(
        """
        SELECT id, name, email, role, created_at
        FROM users WHERE role IN ('student', 'admin') ORDER BY role, name
        """
    ).fetchall()

    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@login_required
@admin_required
def admin_update_user_role(user_id):
    db = get_db()

    role = request.form.get("role", "").strip().lower()

    if role not in ROLES:
        flash("Only Student and Admin accounts are supported.", "danger")
        return redirect(url_for("admin_users"))

    user = db.execute(
        "SELECT id, name, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if user is None:
        flash("User account not found.", "warning")
        return redirect(url_for("admin_users"))

    # Prevent an administrator from accidentally removing their own access.
    if user_id == session.get("user_id") and role != "admin":
        flash("You cannot remove your own administrator role.", "danger")
        return redirect(url_for("admin_users"))

    db.execute(
        "UPDATE users SET role = ? WHERE id = ?",
        (role, user_id),
    )
    db.commit()

    audit_action(
        "user_role_updated",
        "users",
        user_id,
        f"Role changed from {user['role']} to {role}",
    )
    db.commit()

    flash("User role updated successfully.", "success")
    return redirect(url_for("admin_users"))



# ---------------------------------------------------------
# Admin: feedback review and response
# ---------------------------------------------------------

@app.route("/admin/feedback")
@login_required
@admin_required
def admin_feedback():
    db = get_db()

    items = db.execute(
        """
        SELECT f.*, u.name AS student_name, u.email AS student_email
        FROM student_feedback f
        JOIN users u ON u.id = f.student_id
        ORDER BY
            CASE f.status
                WHEN 'Received' THEN 0
                WHEN 'Under Review' THEN 1
                ELSE 2
            END,
            f.created_at DESC
        """
    ).fetchall()

    return render_template("admin_feedback.html", feedback_items=items)



@app.route("/admin/feedback/<int:feedback_id>/respond", methods=["POST"])
@login_required
@admin_required
def respond_to_feedback(feedback_id):
    db = get_db()

    item = db.execute(
        "SELECT id FROM student_feedback WHERE id = ?",
        (feedback_id,),
    ).fetchone()

    if item is None:
        abort(404)

    response = request.form.get("response", "").strip()
    status = request.form.get("status", "Under Review")

    if status not in {"Received", "Under Review", "Resolved"}:
        abort(400)

    db.execute(
        """
        UPDATE student_feedback
        SET admin_response = ?, status = ?, responded_by = ?,
            responded_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (response[:5000], status, session["user_id"], feedback_id),
    )
    db.commit()

    audit_action(
        "feedback_responded",
        "student_feedback",
        feedback_id,
        f"Status: {status}",
    )
    db.commit()

    flash("Feedback response saved.", "success")
    return redirect(url_for("admin_feedback"))


# ---------------------------------------------------------
# Admin: events
# ---------------------------------------------------------

@app.route("/events")
@login_required
def events():
    items = get_db().execute(
        """
        SELECT * FROM college_events
        WHERE status != 'Cancelled'
        ORDER BY event_date, start_time
        """
    ).fetchall()

    return render_template("events.html", events=items)


@app.route("/admin/events", methods=["GET", "POST"])
@login_required
@admin_required
def admin_events():
    db = get_db()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        event_date = request.form.get("event_date", "")
        start_time = request.form.get("start_time", "")
        venue = request.form.get("venue", "").strip()

        if not title or not require_valid_date(event_date) or not start_time:
            flash("Enter a title, valid date, and start time.", "danger")
        else:
            db.execute(
                """
                INSERT INTO college_events
                    (title, description, event_date, start_time, venue,
                     created_by, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'Scheduled', CURRENT_TIMESTAMP)
                """,
                (
                    title[:200], description[:3000], event_date,
                    start_time, venue[:200], session["user_id"],
                ),
            )
            db.commit()
            flash("Event created.", "success")

        return redirect(url_for("admin_events"))

    items = db.execute(
        "SELECT * FROM college_events ORDER BY event_date DESC, id DESC"
    ).fetchall()

    return render_template("admin_events.html", events=items)


@app.route("/admin/events/<int:event_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_event(event_id):
    db = get_db()
    event = db.execute(
        "SELECT id, title FROM college_events WHERE id = ?", (event_id,)
    ).fetchone()

    if event is None:
        flash("That event no longer exists.", "warning")
        return redirect(url_for("admin_events"))

    db.execute("DELETE FROM college_events WHERE id = ?", (event_id,))
    audit_action("delete", "college_event", event_id, f"Deleted event: {event['title']}")
    db.commit()
    flash("Event deleted.", "success")
    return redirect(url_for("admin_events"))


# ---------------------------------------------------------
# Admin: student workflows
# ---------------------------------------------------------

@app.route("/student/applications", methods=["GET", "POST"])
@login_required
@role_required("student")
def student_applications():
    db = get_db()
    student_id = session["user_id"]

    if request.method == "POST":
        application_type = request.form.get(
            "application_type", ""
        ).strip().lower()

        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        reason = request.form.get("reason", "").strip()

        start = require_valid_date(start_date)
        end = require_valid_date(end_date)

        if application_type not in {"leave", "od"}:
            flash("Select a valid application type.", "danger")
            return redirect(url_for("student_applications"))

        if not start or not end or end < start:
            flash("Enter valid application dates.", "danger")
            return redirect(url_for("student_applications"))

        if not reason:
            flash("Please enter the reason for your application.", "danger")
            return redirect(url_for("student_applications"))

        if application_type == "leave":
            leave_type = (
                request.form.get("leave_type", "Other").strip()
                or "Other"
            )

            db.execute(
                """
                INSERT INTO student_leave_applications
                    (student_user_id, leave_type, start_date,
                     end_date, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
                """,
                (
                    student_id,
                    leave_type[:100],
                    start.isoformat(),
                    end.isoformat(),
                    reason[:2000],
                ),
            )

        else:
            category = (
                request.form.get("category", "Official Duty").strip()
                or "Official Duty"
            )

            db.execute(
                """
                INSERT INTO student_od_applications
                    (student_user_id, start_date, end_date,
                     category, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
                """,
                (
                    student_id,
                    start.isoformat(),
                    end.isoformat(),
                    category[:100],
                    reason[:2000],
                ),
            )

        db.commit()
        flash("Your application has been submitted successfully.", "success")
        return redirect(url_for("student_applications"))

    leave_requests = db.execute(
        """
        SELECT *
        FROM student_leave_applications
        WHERE student_user_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (student_id,),
    ).fetchall()

    od_requests = db.execute(
        """
        SELECT *
        FROM student_od_applications
        WHERE student_user_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (student_id,),
    ).fetchall()

    return render_template(
        "student_applications.html",
        leave_requests=leave_requests,
        od_requests=od_requests,
    )


# ---------------------------------------------------------
# Admin: View Student Leave and OD Applications
# ---------------------------------------------------------

@app.route("/admin/student-applications")
@login_required
@admin_required
def admin_student_applications():
    db = get_db()

    leave_requests = db.execute(
        """
        SELECT
            l.*,
            u.name AS student_name,
            u.email AS student_email
        FROM student_leave_applications l
        JOIN users u ON u.id = l.student_user_id
        ORDER BY
            CASE WHEN l.status = 'Pending' THEN 0 ELSE 1 END,
            l.created_at DESC
        """
    ).fetchall()

    od_requests = db.execute(
        """
        SELECT
            o.*,
            u.name AS student_name,
            u.email AS student_email
        FROM student_od_applications o
        JOIN users u ON u.id = o.student_user_id
        ORDER BY
            CASE WHEN o.status = 'Pending' THEN 0 ELSE 1 END,
            o.created_at DESC
        """
    ).fetchall()

    return render_template(
        "admin_student_applications.html",
        leave_requests=leave_requests,
        od_requests=od_requests,
    )


# ---------------------------------------------------------
# Admin: Approve or Reject Student Applications
# ---------------------------------------------------------

@app.route(
    "/admin/student-applications/<kind>/<int:application_id>/review",
    methods=["POST"],
)
@login_required
@admin_required
def review_student_application(kind, application_id):
    tables = {
        "leave": "student_leave_applications",
        "od": "student_od_applications",
    }

    table = tables.get(kind)

    if table is None:
        abort(404)

    status = request.form.get("status", "").strip()
    remarks = request.form.get("remarks", "").strip()

    if status not in {"Approved", "Rejected"}:
        abort(400)

    db = get_db()

    application = db.execute(
        f"""
        SELECT id, status
        FROM {table}
        WHERE id = ?
        """,
        (application_id,),
    ).fetchone()

    if application is None:
        abort(404)

    if application["status"] != "Pending":
        flash(
            "This application has already been reviewed.",
            "warning",
        )
        return redirect(url_for("admin_student_applications"))

    db.execute(
        f"""
        UPDATE {table}
        SET status = ?,
            decision_remarks = ?,
            decided_by = ?,
            decided_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'Pending'
        """,
        (
            status,
            remarks[:2000],
            session["user_id"],
            application_id,
        ),
    )

    db.commit()

    audit_action(
        "student_application_reviewed",
        table,
        application_id,
        f"Status: {status}",
    )
    db.commit()

    flash(
        f"Student application {status.lower()} successfully.",
        "success",
    )

    return redirect(url_for("admin_student_applications"))


# ---------------------------------------------------------

@app.route("/admin/attendance/mark", methods=["GET", "POST"])
@login_required
@admin_required
def admin_mark_attendance():
    db = get_db()
    allowed_statuses = ATTENDANCE_STATUSES

    if request.method == "POST":
        action = request.form.get("action", "mark").strip()

        if action == "create_session":
            session_date = request.form.get("session_date", "").strip()
            subject = request.form.get("subject", "").strip()
            class_id = request.form.get("class_id", "").strip()
            start_time = request.form.get("start_time", "").strip() or None
            end_time = request.form.get("end_time", "").strip() or None

            parsed_date = require_valid_date(session_date)
            if not parsed_date or not subject or len(subject) > 120 or len(class_id) > 80:
                flash("Enter a valid date and subject. Class/group is optional.", "danger")
                return redirect(url_for("admin_mark_attendance"))

            # Avoid accidentally creating a duplicate session for the same class,
            # subject, date, and start time.
            existing = db.execute(
                """SELECT id FROM class_sessions
                   WHERE session_date = ? AND subject = ? AND class_id = ?
                     AND COALESCE(start_time, '') = COALESCE(?, '')""",
                (session_date, subject, class_id, start_time),
            ).fetchone()
            if existing:
                flash("That class session already exists. Select it below to mark attendance.", "warning")
                return redirect(url_for("admin_mark_attendance", session_id=existing["id"]))

            if start_time and end_time and end_time <= start_time:
                flash("End time must be later than start time.", "danger")
                return redirect(url_for("admin_mark_attendance"))

            cursor = db.execute(
                """INSERT INTO class_sessions
                   (session_date, subject, class_id, start_time, end_time, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_date, subject, class_id, start_time, end_time, session["user_id"]),
            )
            db.commit()
            flash("Class session created. You can now mark each student's attendance.", "success")
            return redirect(url_for("admin_mark_attendance", session_id=cursor.lastrowid))

        if action == "save_attendance":
            session_id = request.form.get("session_id", type=int)
            class_session = db.execute(
                "SELECT id FROM class_sessions WHERE id = ?", (session_id,)
            ).fetchone() if session_id else None
            if class_session is None:
                flash("Select a valid class session.", "danger")
                return redirect(url_for("admin_mark_attendance"))

            students = db.execute(
                "SELECT id FROM users WHERE role = 'student' ORDER BY id"
            ).fetchall()
            saved = 0
            for student in students:
                student_id = student["id"]
                status = request.form.get(f"status_{student_id}", "").strip()
                remarks = request.form.get(f"remarks_{student_id}", "").strip()
                if status not in allowed_statuses:
                    continue

                existing = db.execute(
                    "SELECT id FROM student_attendance WHERE student_id = ? AND session_id = ?",
                    (student_id, session_id),
                ).fetchone()
                if existing:
                    db.execute(
                        """UPDATE student_attendance
                           SET status = ?, remarks = ?, marked_by = ?,
                               marked_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (status, remarks[:500], session["user_id"], existing["id"]),
                    )
                else:
                    db.execute(
                        """INSERT INTO student_attendance
                           (student_id, session_id, status, remarks, marked_by)
                           VALUES (?, ?, ?, ?, ?)""",
                        (student_id, session_id, status, remarks[:500], session["user_id"]),
                    )
                saved += 1

            db.commit()
            flash(f"Attendance saved for {saved} student(s). Existing entries were updated safely.", "success")
            return redirect(url_for("admin_mark_attendance", session_id=session_id))

        flash("Unknown attendance action.", "danger")
        return redirect(url_for("admin_mark_attendance"))

    sessions = db.execute(
        """SELECT id, session_date, subject, class_id, start_time, end_time
           FROM class_sessions ORDER BY session_date DESC, id DESC LIMIT 100"""
    ).fetchall()
    selected_id = request.args.get("session_id", type=int)
    selected_session = None
    students = []
    if selected_id:
        selected_session = db.execute(
            "SELECT * FROM class_sessions WHERE id = ?", (selected_id,)
        ).fetchone()
        if selected_session:
            students = db.execute(
                """SELECT u.id, u.name, u.email, a.status, a.remarks
                   FROM users u
                   LEFT JOIN student_attendance a
                     ON a.student_id = u.id AND a.session_id = ?
                   WHERE u.role = 'student'
                   ORDER BY lower(u.name)""",
                (selected_id,),
            ).fetchall()

    return render_template(
        "admin_mark_attendance.html",
        sessions=sessions,
        selected_session=selected_session,
        students=students,
        attendance_statuses=sorted(allowed_statuses),
        today=date.today().isoformat(),
    )


# ---------------------------------------------------------
# Admin: attendance overview and reports
# ---------------------------------------------------------

@app.route("/admin/attendance")
@login_required
@admin_required
def admin_attendance():
    db = get_db()

    records = db.execute(
        """
        SELECT a.*, u.name AS student_name, s.session_date,
               s.subject, s.class_id
        FROM student_attendance a
        JOIN users u ON u.id = a.student_id
        JOIN class_sessions s ON s.id = a.session_id
        ORDER BY s.session_date DESC, u.name
        """
    ).fetchall()

    return render_template("admin_attendance.html", attendance_records=records)


# ---------------------------------------------------------
# Errors
# ---------------------------------------------------------

@app.errorhandler(400)
def bad_request(_error):
    return render_template(
        "error.html",
        code=400,
        message="The submitted information could not be accepted. Check the form and try again.",
    ), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template(
        "error.html",
        code=403,
        message="You do not have permission to view this page.",
    ), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template(
        "error.html",
        code=404,
        message="The page you requested could not be found.",
    ), 404


@app.errorhandler(413)
def upload_too_large(_error):
    return render_template(
        "error.html",
        code=413,
        message="The uploaded file is too large. The maximum allowed size is 10 MB.",
    ), 413


@app.errorhandler(500)
def internal_error(_error):
    get_db().rollback()
    app.logger.exception("An unexpected application error occurred.")
    return render_template(
        "error.html",
        code=500,
        message="Something went wrong. Please try again later.",
    ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)