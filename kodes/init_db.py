#!/usr/bin/env python3
"""
Database initialization script for Kodes
"""
import sys
import argparse

def init_db(force=False):
    """
    Initialize the database for Kodes using the Flask application's schema.

    Args:
        force: Force reinitialization (drop all tables and recreate)

    Returns:
        bool: True if successful
    """
    try:
        from src.server.app import create_app
        from src.server.models import db

        app = create_app()
        with app.app_context():
            if force:
                print("Dropping all tables...")
                db.drop_all()
            print("Creating database tables...")
            db.create_all()

        print("Database initialized successfully")
        return True

    except Exception as e:
        print(f"Error initializing database: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize Kodes database")
    parser.add_argument("--force", action="store_true", help="Drop and recreate all tables")
    args = parser.parse_args()

    if init_db(args.force):
        sys.exit(0)
    else:
        sys.exit(1)