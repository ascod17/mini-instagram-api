from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import timedelta, datetime


import os # Файлды ең жоғарғы жағына қосуды ұмытпа

def get_db_connection():
    # Render-дегі DATABASE_URL айнымалысын алады
    db_url = os.environ.get('DATABASE_URL')
    
    if db_url:
        # Егер интернетте (Render-де) болсақ
        return psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    
    # Егер өз компьютеріңде (Localhost) болсаң
    return psycopg2.connect(
        host="localhost",
        database="instagram_db",
        user="postgres",
        password="asco",
        cursor_factory=RealDictCursor
    )


app = Flask(__name__)

# --- 1. CONFIGURATION ---
app.config["JWT_SECRET_KEY"] = "super-secret-key-asco"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=30)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
jwt = JWTManager(app)



# --- 2. ERROR HANDLING ---
@app.errorhandler(401)
def unauthorized(error):
    return jsonify({"error": "Рұқсат жоқ (Unauthorized)", "message": str(error)}), 401

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Ресурс табылмады", "message": "Бұл URL мекенжайы жоқ"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Серверлік қате", "message": "Ішкі серверлік ақау шықты"}), 500

# --- 3. AUTHENTICATION (Login, Register, Refresh) ---

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"error": "Логин мен пароль толтырылуы тиіс"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                    (data['username'], data['email'], data['password']))
        conn.commit()
        return jsonify({"msg": "Пайдаланушы сәтті тіркелді!"}), 201
    except Exception as e:
        return jsonify({"error": "Мұндай пайдаланушы бар немесе дерек қате"}), 400
    finally:
        cur.close()
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s AND password=%s", 
                (data.get('username'), data.get('password')))
    user = cur.fetchone()
    
    if user:
        user_id = user['id']
        access_token = create_access_token(identity=str(user_id))
        refresh_token = create_refresh_token(identity=str(user_id))
        
        # Refresh токенді базаға сақтау
        cur.execute("INSERT INTO refresh_tokens (token, user_id, expires_at) VALUES (%s, %s, %s)",
                    (refresh_token, user_id, datetime.now() + timedelta(days=30)))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(access_token=access_token, refresh_token=refresh_token), 200
    
    return jsonify({"msg": "Қате логин немесе пароль"}), 401

@app.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    new_access_token = create_access_token(identity=identity)
    return jsonify(access_token=new_access_token), 200

# --- 4. CRUD WITH PAGINATION ---

@app.route('/posts', methods=['GET'])
def get_posts():
    # Пагинация: ?page=1&limit=5
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 5, type=int)
    offset = (page - 1) * limit

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM posts ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset))
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(posts), 200

@app.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO posts (caption, author_id) VALUES (%s, %s) RETURNING id", 
                (data['caption'], user_id))
    post_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": post_id, "msg": "Пост салынды"}), 201

# --- БАСҚА CRUD ОПЕРАЦИЯЛАРЫ (Қысқаша) ---

@app.route('/comments', methods=['POST'])
@jwt_required()
def add_comment():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO comments (text, post_id, author_id) VALUES (%s, %s, %s)", 
                (data['text'], data['post_id'], user_id))
    conn.commit()
    return jsonify({"msg": "Пікір қосылды"}), 201

@app.route('/like', methods=['POST'])
@jwt_required()
def like_post():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO likes (user_id, post_id) VALUES (%s, %s)", (user_id, data['post_id']))
    conn.commit()
    return jsonify({"msg": "Лайк басылды"}), 201

@app.route('/users', methods=['GET'])
def get_users():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    offset = (page - 1) * limit
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email FROM users LIMIT %s OFFSET %s", (limit, offset))
    users = cur.fetchall()
    return jsonify(users), 200

# --- 5. START SERVER ---
if __name__ == '__main__':
    app.run(debug=True)