# run.py
from app import create_app
import os # Untuk mengecek path database

app = create_app()

if __name__ == '__main__':
    
    app.run(debug=True, port=5003)