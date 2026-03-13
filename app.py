from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import timedelta, datetime

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-123")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
jwt = JWTManager(app)

def get_db_connection():
    try:
        # Render-дегі DATABASE_URL-ді алу
        db_url = os.environ.get('DATABASE_URL')
        if db_url:
            # СІЛТЕМЕ БАР: Render базасына SSL арқылы қосылу (МІНДЕТТІ)
            return psycopg2.connect(db_url, sslmode='require', cursor_factory=RealDictCursor)
        else:
            # СІЛТЕМЕ ЖОҚ: Локальды база
            return psycopg2.connect(
                host="localhost", database="instagram_db",
                user="postgres", password="ascod", port="5432",
                cursor_factory=RealDictCursor
            )
    except Exception as e:
        print(f"DATABASE CONNECTION ERROR: {e}")
        return None

# --- 1. AUTH & REFRESH TOKENS ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cur = conn.cursor()
    try:
        # Email бағаны бар-жоғын тексеріп енгізу
        email = data.get('email', None)
        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (data['username'], email, data['password'])
        )
        conn.commit()
        return jsonify({"msg": "Пайдаланушы сәтті тіркелді!"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB failed"}), 500
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s AND password=%s", 
                (data['username'], data['password']))
    user = cur.fetchone()
    if user:
        user_id = str(user['id'])
        access_token = create_access_token(identity=user_id)
        refresh_token = create_refresh_token(identity=user_id)
        expires_at = datetime.now() + timedelta(days=30)
        
        cur.execute(
            "INSERT INTO refresh_tokens (token, user_id, expires_at) VALUES (%s, %s, %s)",
            (refresh_token, int(user_id), expires_at)
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"access_token": access_token, "refresh_token": refresh_token}), 200
    return jsonify({"msg": "Логин немесе пароль қате!"}), 401

@app.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    new_access_token = create_access_token(identity=identity)
    return jsonify(access_token=new_access_token), 200

# --- 2. POSTS & 3. MEDIA ---
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
    return jsonify({"id": post_id, "msg": "Пост жарияланды"}), 201

@app.route('/posts', methods=['GET'])
def get_posts():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM posts")
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(posts), 200

@app.route('/media', methods=['POST'])
@jwt_required()
def add_media():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO media (url, post_id, media_type) VALUES (%s, %s, %s)", 
                (data['url'], data['post_id'], data['media_type']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Медиа қосылды"}), 201

# --- 4. COMMENTS & 5. LIKES ---
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
    cur.close()
    conn.close()
    return jsonify({"msg": "Пікір қалдырылды"}), 201

@app.route('/like', methods=['POST'])
@jwt_required()
def like_post():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO likes (user_id, post_id) VALUES (%s, %s)", (user_id, data['post_id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Лайк басылды"}), 201

# --- 6. FOLLOWS ---
@app.route('/follow', methods=['POST'])
@jwt_required()
def follow_user():
    follower_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO follows (follower_id, followed_id) VALUES (%s, %s)", 
                (follower_id, data['followed_id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Жазылдыңыз"}), 201

# --- 7. RENDER INFRASTRUCTURE ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)