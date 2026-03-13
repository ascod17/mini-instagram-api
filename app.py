from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import timedelta, datetime

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
app.config["JWT_SECRET_KEY"] = "super-secret-key-123"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
jwt = JWTManager(app)

def get_db_connection():
    try:
        # Render-дегі DATABASE_URL-ді міндетті түрде бірінші тексереміз
        db_url = os.environ.get('DATABASE_URL')
        if db_url:
            # СІЛТЕМЕ БАР БОЛСА: Render базасына SSL арқылы қосылу
            return psycopg2.connect(db_url, sslmode='require', cursor_factory=RealDictCursor)
        else:
            # СІЛТЕМЕ ЖОҚ БОЛСА: Локальды база
            return psycopg2.connect(
                host="localhost", database="instagram_db",
                user="postgres", password="ascod", port="5432",
                cursor_factory=RealDictCursor
            )
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        return None

# --- ТІРКЕЛУ (REGISTER) ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cur = conn.cursor()
    try:
        # Базада 'email' бағаны бар-жоғына қарамастан қате бермеу үшін:
        if 'email' in data:
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                        (data['username'], data['email'], data['password']))
        else:
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)",
                        (data['username'], data['password']))
        conn.commit()
        return jsonify({"msg": "Сәтті тіркелдіңіз!"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

# --- RENDER ҮШІН МАҢЫЗДЫ ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)