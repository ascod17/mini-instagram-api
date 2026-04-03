from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import timedelta

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-123")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
jwt = JWTManager(app)

def get_db_connection():
    try:
        return psycopg2.connect(
            "postgresql://instagram_db_c97l_user:0jBH2Iicx4Oc97mb5uIbsCK8M651q8xg@dpg-d6q4b0450q8c73abn2jg-a/instagram_db_c97l?sslmode=require",
            cursor_factory=RealDictCursor
        )
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        return None

# --- AUTH (Өзгеріссіз қалды) ---
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB failed"}), 500
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE username=%s AND password=%s", 
                (data['username'], data['password']))
    user = cur.fetchone()
    if user:
        access_token = create_access_token(identity=str(user['id']))
        return jsonify({"access_token": access_token, "username": user['username']}), 200
    return jsonify({"msg": "Қате!"}), 401

# --- FEED (ЖӨНДЕЛДІ: Енді әр посттың иесінің аты бірге келеді) ---
@app.route('/posts', methods=['GET'])
def get_posts():
    conn = get_db_connection()
    cur = conn.cursor()
    # JOIN арқылы users кестесінен username-ді қосып аламыз
    cur.execute("""
        SELECT p.*, u.username, m.url as image_url 
        FROM posts p 
        JOIN users u ON p.author_id = u.id 
        LEFT JOIN media m ON p.id = m.post_id 
        ORDER BY p.id DESC
    """)
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(posts), 200

# --- PROFILE (ЖӨНДЕЛДІ: Статистика мен суреттер форматы Котлинге ыңғайланды) ---
@app.route('/profile', methods=['GET'])
@jwt_required()
def get_my_profile():
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Қолданушы мәліметтері
    cur.execute("""
        SELECT username, 
               (SELECT COUNT(*) FROM posts WHERE author_id = %s) as posts_count,
               (SELECT COUNT(*) FROM follows WHERE followed_id = %s) as followers_count,
               (SELECT COUNT(*) FROM follows WHERE follower_id = %s) as following_count
        FROM users WHERE id = %s
    """, (user_id, user_id, user_id, user_id))
    user_info = cur.fetchone()

    # Посттар (суреттерімен)
    cur.execute("""
        SELECT p.id, m.url as image_url 
        FROM posts p 
        LEFT JOIN media m ON p.id = m.post_id 
        WHERE p.author_id = %s 
        ORDER BY p.id DESC
    """, (user_id,))
    posts = cur.fetchall()

    cur.close()
    conn.close()
    return jsonify({
        "user": user_info,
        "posts": posts
    }), 200

# --- POSTS КӨШІРУ (Create Post бөлімі) ---
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
    if data.get('image_url'):
        cur.execute("INSERT INTO media (url, post_id, media_type) VALUES (%s, %s, %s)", 
                    (data['image_url'], post_id, 'image'))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": post_id, "msg": "Жарияланды"}), 201

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
