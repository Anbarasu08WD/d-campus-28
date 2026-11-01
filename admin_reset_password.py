import sqlite3, getpass
from werkzeug.security import generate_password_hash

email = input("Admin email [admin@demo.com]: ").strip() or "admin@demo.com"
password = getpass.getpass("New password (8+ characters): ")
db = sqlite3.connect("student_success.db")
db.execute("UPDATE users SET password_hash = ? WHERE email = ? AND role = 'admin'", (generate_password_hash(password), email))
db.commit()
print("Password updated." if db.total_changes else "No admin found with that email. Nothing changed.")