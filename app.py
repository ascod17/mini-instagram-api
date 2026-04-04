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

# --- AUTH ---
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE username=%s AND password=%s", 
                (data['username'], data['password']))
    user = cur.fetchone()
    if user:
        access_token = create_access_token(identity=str(user['id']))
        return jsonify({"access_token": access_token, "username": user['username']}), 200
    return jsonify({"msg": "Қате!"}), 401

# --- FEED ---
@app.route('/posts', methods=['GET'])
@jwt_required(optional=True)
def get_posts():
    current_user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*, u.username, m.url as image_url,
               CASE WHEN p.author_id = %s THEN true ELSE false END as is_my_post
        FROM posts p 
        JOIN users u ON p.author_id = u.id 
        LEFT JOIN media m ON p.id = m.post_id 
        ORDER BY p.id DESC
    """, (current_user_id,))
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(posts), 200

# --- STORIES (Есімдерді дұрыстау үшін JOIN қосылды) ---
@app.route('/stories', methods=['GET'])
@jwt_required(optional=True)
def get_stories():
    current_user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.*, u.username,
               CASE WHEN s.user_id = %s THEN true ELSE false END as is_my_story
        FROM stories s 
        JOIN users u ON s.user_id = u.id 
        ORDER BY s.created_at DESC
    """, (current_user_id,))
    stories = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(stories), 200

@app.route('/stories', methods=['POST'])
@jwt_required()
def add_story():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO stories (user_id, media_url) VALUES (%s, %s) RETURNING id", 
                (user_id, data['media_url']))
    story_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": story_id, "msg": "Сторис қосылды"}), 201

# --- PROFILE ---
@app.route('/profile', methods=['GET'])
@jwt_required()
def get_my_profile():
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, 
               (SELECT COUNT(*) FROM posts WHERE author_id = %s) as posts_count,
               (SELECT COUNT(*) FROM follows WHERE followed_id = %s) as followers_count,
               (SELECT COUNT(*) FROM follows WHERE follower_id = %s) as following_count
        FROM users WHERE id = %s
    """, (user_id, user_id, user_id, user_id))
    user_info = cur.fetchone()

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
    return jsonify({"user": user_info, "posts": posts}), 200

# --- CREATE POST ---
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
