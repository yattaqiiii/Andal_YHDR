# app/__init__.py
import os
from flask import Flask, g # g dibutuhkan jika make_current_year_available di sini
import datetime # Untuk make_current_year_available

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    
    # Load configuration from config.py
    app.config.from_object('app.config.Config')

    if test_config is None:
        # load the instance config, if it exists, when not testing
        # Ini bisa digunakan untuk menimpa config default, misal SECRET_KEY dari file di instance folder
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass # already exists or other error

    # Initialize database
    from . import database
    database.init_app(app)

    # Register Blueprints
    from . import routes
    app.register_blueprint(routes.bp)
    # Jika Anda ingin URL tanpa prefix '/main', Anda bisa set url_prefix=None atau '/' saat mendaftarkan blueprint
    # app.add_url_rule('/', endpoint='index') # Jika Anda ingin index tetap di root jika blueprint punya prefix

    # Context processor untuk tahun (jika tidak di blueprint)
    @app.context_processor
    def inject_current_year():
        return {'current_year': datetime.datetime.now().year}
    
    # Jika Anda memindahkan `make_current_year_available` ke sini dari routes.py:
    # @app.before_request
    # def make_current_year_available():
    # g.current_year = datetime.datetime.now().year

    return app