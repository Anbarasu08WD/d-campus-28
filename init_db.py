from app import app
from database import init_db, seed_demo_data

with app.app_context():
    init_db()
    seed_demo_data()
    print('Database initialized and demo data checked.')
