from flask import Flask, request, jsonify, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import timedelta
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-123")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
app.config['UPLOAD_FOLDER'] = 'uploads'  # Суреттер сақталатын папка

# Папка жоқ болса жасау
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

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

# Суреттерді браузер немесе телефон арқылы көру үшін жол
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

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

# --- FEED (Барлық посттар) ---
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

# --- CREATE POST (Әмбебап: Сурет файлы немесе JSON URL) ---
@app.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    user_id = get_jwt_identity()
    caption = request.form.get('caption') or (request.json.get('caption') if request.is_json else "")
    image_url = None

    # 1. Егер телефоннан файл келсе
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            # Сервердің мекен-жайын қосу керек (Render URL болса соны)
            image_url = f"/uploads/{filename}"
    
    # 2. Егер Postman-нан JSON келсе
    elif request.is_json and 'image_url' in request.json:
        image_url = request.json['image_url']

    if not image_url:
        return jsonify({"msg": "Сурет жүктелмеді!"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO posts (caption, author_id) VALUES (%s, %s) RETURNING id", 
                (caption, user_id))
    post_id = cur.fetchone()['id']
    
    cur.execute("INSERT INTO media (url, post_id, media_type) VALUES (%s, %s, %s)", 
                (image_url, post_id, 'image'))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": post_id, "msg": "Жарияланды", "image_url": image_url}), 201

# --- DELETE POST ---
@app.route('/posts/<int:post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM posts WHERE id = %s AND author_id = %s", (post_id, user_id))
    if cur.rowcount == 0:
        return jsonify({"msg": "Рұқсат жоқ немесе пост табылмады"}), 404
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Пост өшірілді"}), 200

# --- STORIES (GET) ---
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

# --- ADD STORY (Файл жүктеу мүмкіндігімен) ---
@app.route('/stories', methods=['POST'])
@jwt_required()
def add_story():
    user_id = get_jwt_identity()
    media_url = None

    if 'image' in request.files:
        file = request.files['image']
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        media_url = f"/uploads/{filename}"
    elif request.is_json:
        media_url = request.json.get('media_url')

    if not media_url:
        return jsonify({"msg": "Медиа файл қажет"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO stories (user_id, media_url) VALUES (%s, %s) RETURNING id", 
                (user_id, media_url))
    story_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": story_id, "msg": "Сторис қосылды"}), 201

# --- DELETE STORY ---
@app.route('/stories/<int:story_id>', methods=['DELETE'])
@jwt_required()
def delete_story(story_id):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM stories WHERE id = %s AND user_id = %s", (story_id, user_id))
    if cur.rowcount == 0:
        return jsonify({"msg": "Сторис табылмады"}), 404
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Сторис өшірілді"}), 200

# --- PROFILE (Тек менің деректерім) ---
@app.route('/profile', methods=['GET'])
@jwt_required()
def get_my_profile():
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Юзер статистикасы
    cur.execute("""
        SELECT username, 
               (SELECT COUNT(*) FROM posts WHERE author_id = %s) as posts_count,
               (SELECT COUNT(*) FROM follows WHERE followed_id = %s) as followers_count,
               (SELECT COUNT(*) FROM follows WHERE follower_id = %s) as following_count
        FROM users WHERE id = %s
    """, (user_id, user_id, user_id, user_id))
    user_info = cur.fetchone()

    # Юзердің өз посттары
    cur.execute("""
        SELECT p.id, m.url as image_url, p.caption 
        FROM posts p 
        LEFT JOIN media m ON p.id = m.post_id 
        WHERE p.author_id = %s 
        ORDER BY p.id DESC
    """, (user_id,))
    posts = cur.fetchall()
    
    cur.close()
    conn.close()
    return jsonify({"user": user_info, "posts": posts}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
