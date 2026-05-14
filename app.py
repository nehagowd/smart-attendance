# app.py — Flask application entry point (registers blueprints and initializes DB)
import os

from flask import Flask

from config import Config
from models.db import init_db
from routes.admin import admin_bp
from routes.api import api_bp
from routes.auth import auth_bp
from routes.student import student_bp


def create_app():
    """Application factory: configure Flask, ensure folders exist, register routes."""
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(Config.DATASET_FOLDER, exist_ok=True)
    os.makedirs(Config.EXPORT_FOLDER, exist_ok=True)

    init_db(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(api_bp)

    return app


app = create_app()

if __name__ == "__main__":
    # debug=True suitable for college demo; disable in real deployment
    app.run(host="0.0.0.0", port=5000, debug=True)
