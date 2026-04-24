from flask import Flask, request, jsonify, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, decode_token
from flask_sock import Sock
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import timedelta, datetime
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
sock = Sock(app)

app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "super-secret-key-123")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
app.config["UPLOAD_FOLDER"] = "uploads"

BASE_URL = "https://mini-instagram-api-8ucb.onrender.com"

if not os.path.exists(app.config["UPLOAD_FOLDER"]):
    os.makedirs(app.config["UPLOAD_FOLDER"])

jwt = JWTManager(app)
active_connections = {}


def get_db_connection():
    try:
        return psycopg2.connect(
            "postgresql://postgre:W9qgpjrkJHxKKa7HJuSH38iExfAV1Zx6@dpg-d7h1gej7uimc73d2irgg-a/instagram_db_lota?sslmode=require",
            cursor_factory=RealDictCursor
        )
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        return None


def to_int_or_none(value):
    if value is None:
        return None
    return int(value)


def build_chat_id(user_a: int, user_b: int) -> str:
    first, second = sorted([int(user_a), int(user_b)])
    return f"{first}_{second}"


def ensure_chat_tables(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_rooms (
            chat_id TEXT PRIMARY KEY,
            user_one_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_two_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_one_id, user_two_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL REFERENCES chat_rooms(chat_id) ON DELETE CASCADE,
            sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    cur.close()


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (data["username"], data["email"], data["password"])
        )
        conn.commit()
        return jsonify({"msg": "Тіркелу сәтті өтті!"}), 201
    except Exception:
        conn.rollback()
        return jsonify({"msg": "Қате: Мұндай қолданушы бар болуы мүмкін"}), 400
    finally:
        cur.close()
        conn.close()


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        "SELECT id, username FROM users WHERE username = %s AND password = %s",
        (data["username"], data["password"])
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user:
        access_token = create_access_token(identity=str(user["id"]))
        return jsonify({
            "access_token": access_token,
            "username": user["username"],
            "id": user["id"]
        }), 200

    return jsonify({"msg": "Логин немесе пароль қате!"}), 401


@app.route("/posts", methods=["GET"])
@jwt_required(optional=True)
def get_posts():
    current_user_id = to_int_or_none(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.id,
            p.caption,
            p.author_id,
            u.username,
            u.avatar_url,
            m.url AS image_url,
            CASE WHEN p.author_id = %s THEN true ELSE false END AS is_my_post,
            COALESCE(lc.likes_count, 0) AS likes_count,
            CASE
                WHEN %s IS NOT NULL AND ul.user_id IS NOT NULL THEN true
                ELSE false
            END AS is_liked,
            CASE
                WHEN %s IS NOT NULL AND f.follower_id IS NOT NULL THEN true
                ELSE false
            END AS is_following_author
        FROM posts p
        JOIN users u ON p.author_id = u.id
        LEFT JOIN media m ON p.id = m.post_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS likes_count
            FROM likes
            GROUP BY post_id
        ) lc ON lc.post_id = p.id
        LEFT JOIN likes ul ON ul.post_id = p.id AND ul.user_id = %s
        LEFT JOIN follows f ON f.followed_id = p.author_id AND f.follower_id = %s
        ORDER BY p.id DESC
        """,
        (current_user_id, current_user_id, current_user_id, current_user_id, current_user_id)
    )
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(posts), 200


@app.route("/posts", methods=["POST"])
@jwt_required()
def create_post():
    user_id = int(get_jwt_identity())
    caption = request.form.get("caption") or ((request.get_json() or {}).get("caption") if request.is_json else "")
    image_url = None

    if "image" in request.files:
        file = request.files["image"]
        if file.filename != "":
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image_url = f"{BASE_URL}/uploads/{filename}"
    elif request.is_json:
        image_url = (request.get_json() or {}).get("image_url")

    if not image_url:
        return jsonify({"msg": "Сурет жүктелмеді!"}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO posts (caption, author_id) VALUES (%s, %s) RETURNING id",
        (caption, user_id)
    )
    post_id = cur.fetchone()["id"]

    cur.execute(
        "INSERT INTO media (url, post_id, media_type) VALUES (%s, %s, %s)",
        (image_url, post_id, "image")
    )

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": post_id, "msg": "Жарияланды", "image_url": image_url}), 201


@app.route("/posts/<int:post_id>", methods=["DELETE"])
@jwt_required()
def delete_post(post_id):
    user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute("DELETE FROM posts WHERE id = %s AND author_id = %s", (post_id, user_id))
    if cur.rowcount == 0:
        cur.close()
        conn.close()
        return jsonify({"msg": "Рұқсат жоқ немесе пост табылмады"}), 404

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Пост өшірілді"}), 200


@app.route("/posts/<int:post_id>/like", methods=["POST"])
@jwt_required()
def like_post(post_id):
    current_user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute("SELECT id FROM posts WHERE id = %s", (post_id,))
    if cur.fetchone() is None:
        cur.close()
        conn.close()
        return jsonify({"status": "error", "message": "Post not found"}), 404

    cur.execute(
        """
        INSERT INTO likes (post_id, user_id)
        VALUES (%s, %s)
        ON CONFLICT (post_id, user_id) DO NOTHING
        """,
        (post_id, current_user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success", "message": "Liked"}), 200


@app.route("/posts/<int:post_id>/like", methods=["DELETE"])
@jwt_required()
def unlike_post(post_id):
    current_user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute("DELETE FROM likes WHERE post_id = %s AND user_id = %s", (post_id, current_user_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success", "message": "Unliked"}), 200


@app.route("/stories", methods=["GET"])
@jwt_required(optional=True)
def get_stories():
    current_user_id = to_int_or_none(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.id,
            s.user_id,
            s.media_url,
            s.created_at,
            u.username,
            CASE WHEN s.user_id = %s THEN true ELSE false END AS is_my_story
        FROM stories s
        JOIN users u ON s.user_id = u.id
        ORDER BY s.created_at DESC
        """,
        (current_user_id,)
    )
    stories = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(stories), 200


@app.route("/stories", methods=["POST"])
@jwt_required()
def add_story():
    user_id = int(get_jwt_identity())
    media_url = None

    if "image" in request.files:
        file = request.files["image"]
        if file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            media_url = f"{BASE_URL}/uploads/{filename}"
    elif request.is_json:
        media_url = (request.get_json() or {}).get("media_url")

    if not media_url:
        return jsonify({"msg": "Медиа файл қажет"}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO stories (user_id, media_url) VALUES (%s, %s) RETURNING id",
        (user_id, media_url)
    )
    story_id = cur.fetchone()["id"]

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": story_id, "msg": "Сторис қосылды"}), 201


@app.route("/stories/<int:story_id>", methods=["DELETE"])
@jwt_required()
def delete_story(story_id):
    user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute("DELETE FROM stories WHERE id = %s AND user_id = %s", (story_id, user_id))
    if cur.rowcount == 0:
        cur.close()
        conn.close()
        return jsonify({"msg": "Сторис табылмады"}), 404

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Сторис өшірілді"}), 200


def load_profile_payload(target_user_id, current_user_id):
    conn = get_db_connection()
    if conn is None:
        return None, None, None

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            u.id,
            u.username,
            u.avatar_url,
            COALESCE(u.bio, '') AS bio,
            COALESCE(u.phone_number, '') AS phone_number,
            (SELECT COUNT(*) FROM posts WHERE author_id = u.id) AS posts_count,
            (SELECT COUNT(*) FROM follows WHERE followed_id = u.id) AS followers_count,
            (SELECT COUNT(*) FROM follows WHERE follower_id = u.id) AS following_count,
            CASE
                WHEN %s IS NOT NULL AND EXISTS (
                    SELECT 1 FROM follows
                    WHERE follower_id = %s AND followed_id = u.id
                ) THEN true
                ELSE false
            END AS is_following,
            CASE WHEN u.id = %s THEN true ELSE false END AS is_me
        FROM users u
        WHERE u.id = %s
        """,
        (current_user_id, current_user_id, current_user_id, target_user_id)
    )
    user_info = cur.fetchone()

    if user_info is None:
        cur.close()
        conn.close()
        return None, None, None

    cur.execute(
        """
        SELECT
            p.id,
            p.caption,
            p.author_id,
            u.username,
            u.avatar_url,
            m.url AS image_url,
            CASE WHEN p.author_id = %s THEN true ELSE false END AS is_my_post,
            COALESCE(lc.likes_count, 0) AS likes_count,
            CASE
                WHEN %s IS NOT NULL AND ul.user_id IS NOT NULL THEN true
                ELSE false
            END AS is_liked,
            CASE
                WHEN %s IS NOT NULL AND f.follower_id IS NOT NULL THEN true
                ELSE false
            END AS is_following_author
        FROM posts p
        JOIN users u ON p.author_id = u.id
        LEFT JOIN media m ON p.id = m.post_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS likes_count
            FROM likes
            GROUP BY post_id
        ) lc ON lc.post_id = p.id
        LEFT JOIN likes ul ON ul.post_id = p.id AND ul.user_id = %s
        LEFT JOIN follows f ON f.followed_id = p.author_id AND f.follower_id = %s
        WHERE p.author_id = %s
        ORDER BY p.id DESC
        """,
        (
            current_user_id,
            current_user_id,
            current_user_id,
            current_user_id,
            current_user_id,
            target_user_id,
        )
    )
    posts = cur.fetchall()

    cur.execute(
        """
        SELECT
            s.id,
            s.user_id,
            s.media_url,
            s.created_at,
            u.username,
            CASE WHEN s.user_id = %s THEN true ELSE false END AS is_my_story
        FROM stories s
        JOIN users u ON s.user_id = u.id
        WHERE s.user_id = %s
        ORDER BY s.created_at DESC
        """,
        (current_user_id, target_user_id)
    )
    stories = cur.fetchall()

    cur.close()
    conn.close()
    return user_info, posts, stories


@app.route("/profile", methods=["GET"])
@jwt_required()
def get_my_profile():
    current_user_id = int(get_jwt_identity())
    user_info, posts, stories = load_profile_payload(current_user_id, current_user_id)
    return jsonify({"user": user_info, "posts": posts, "stories": stories}), 200


@app.route("/users/<int:user_id>/profile", methods=["GET"])
@jwt_required(optional=True)
def get_user_profile(user_id):
    current_user_id = to_int_or_none(get_jwt_identity())
    user_info, posts, stories = load_profile_payload(user_id, current_user_id)

    if user_info is None:
        return jsonify({"msg": "User not found"}), 404

    return jsonify({"user": user_info, "posts": posts, "stories": stories}), 200


@app.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    username = data.get("username", "").strip()
    bio = data.get("bio", "").strip()
    phone_number = data.get("phone_number", "").strip()

    if not username:
        return jsonify({"msg": "Username is required"}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE users
            SET username = %s, bio = %s, phone_number = %s
            WHERE id = %s
            """,
            (username, bio, phone_number, current_user_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"msg": "Failed to update profile"}), 400

    cur.close()
    conn.close()

    user_info, posts, stories = load_profile_payload(current_user_id, current_user_id)
    return jsonify({"user": user_info, "posts": posts, "stories": stories}), 200


@app.route("/profile/avatar", methods=["POST"])
@jwt_required()
def upload_profile_avatar():
    current_user_id = int(get_jwt_identity())

    if "avatar" not in request.files:
        return jsonify({"msg": "Avatar file is required"}), 400

    file = request.files["avatar"]
    if file.filename == "":
        return jsonify({"msg": "Avatar file is required"}), 400

    filename = secure_filename(f"user_{current_user_id}_{file.filename}")
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    avatar_url = f"{BASE_URL}/uploads/{filename}"

    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET avatar_url = %s WHERE id = %s",
        (avatar_url, current_user_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"avatar_url": avatar_url}), 200


@app.route("/users/<int:user_id>/follow", methods=["POST"])
@jwt_required()
def follow_user(user_id):
    current_user_id = int(get_jwt_identity())

    if current_user_id == user_id:
        return jsonify({"status": "error", "message": "You cannot follow yourself"}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    if cur.fetchone() is None:
        cur.close()
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404

    cur.execute(
        """
        INSERT INTO follows (follower_id, followed_id)
        VALUES (%s, %s)
        ON CONFLICT (follower_id, followed_id) DO NOTHING
        """,
        (current_user_id, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success", "message": "Followed"}), 200


@app.route("/users/<int:user_id>/follow", methods=["DELETE"])
@jwt_required()
def unfollow_user(user_id):
    current_user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        "DELETE FROM follows WHERE follower_id = %s AND followed_id = %s",
        (current_user_id, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success", "message": "Unfollowed"}), 200


@app.route("/users/<int:user_id>/followers", methods=["GET"])
@jwt_required(optional=True)
def get_followers(user_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.id, u.username, u.avatar_url
        FROM follows f
        JOIN users u ON u.id = f.follower_id
        WHERE f.followed_id = %s
        ORDER BY u.username
        """,
        (user_id,)
    )
    followers = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(followers), 200


@app.route("/users/<int:user_id>/following", methods=["GET"])
@jwt_required(optional=True)
def get_following(user_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.id, u.username, u.avatar_url
        FROM follows f
        JOIN users u ON u.id = f.followed_id
        WHERE f.follower_id = %s
        ORDER BY u.username
        """,
        (user_id,)
    )
    following = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(following), 200


@app.route("/chats/direct", methods=["POST"])
@jwt_required()
def create_or_get_direct_chat():
    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    recipient_id = int(data["recipient_id"])

    if current_user_id == recipient_id:
        return jsonify({"msg": "Cannot open direct chat with yourself"}), 400

    chat_id = build_chat_id(current_user_id, recipient_id)
    user_one_id, user_two_id = sorted([current_user_id, recipient_id])

    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    ensure_chat_tables(conn)
    cur = conn.cursor()

    cur.execute("SELECT id, username, avatar_url FROM users WHERE id = %s", (recipient_id,))
    other_user = cur.fetchone()
    if other_user is None:
        cur.close()
        conn.close()
        return jsonify({"msg": "User not found"}), 404

    cur.execute(
        """
        INSERT INTO chat_rooms (chat_id, user_one_id, user_two_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (chat_id) DO NOTHING
        """,
        (chat_id, user_one_id, user_two_id)
    )
    conn.commit()

    cur.execute(
        """
        SELECT text, created_at
        FROM chat_messages
        WHERE chat_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (chat_id,)
    )
    last_message = cur.fetchone()

    cur.close()
    conn.close()

    return jsonify({
        "chat_id": chat_id,
        "other_user_id": other_user["id"],
        "other_username": other_user["username"],
        "other_avatar_url": other_user["avatar_url"],
        "last_message": last_message["text"] if last_message else None,
        "last_message_at": str(last_message["created_at"]) if last_message else None,
        "unread_count": 0
    }), 200


@app.route("/chats", methods=["GET"])
@jwt_required()
def get_chats():
    current_user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    ensure_chat_tables(conn)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            cr.chat_id,
            CASE
                WHEN cr.user_one_id = %s THEN other_u.id
                ELSE own_u.id
            END AS other_user_id,
            CASE
                WHEN cr.user_one_id = %s THEN other_u.username
                ELSE own_u.username
            END AS other_username,
            CASE
                WHEN cr.user_one_id = %s THEN other_u.avatar_url
                ELSE own_u.avatar_url
            END AS other_avatar_url,
            last_msg.text AS last_message,
            last_msg.created_at AS last_message_at,
            0 AS unread_count
        FROM chat_rooms cr
        JOIN users own_u ON own_u.id = cr.user_one_id
        JOIN users other_u ON other_u.id = cr.user_two_id
        LEFT JOIN LATERAL (
            SELECT text, created_at
            FROM chat_messages cm
            WHERE cm.chat_id = cr.chat_id
            ORDER BY cm.created_at DESC
            LIMIT 1
        ) last_msg ON true
        WHERE cr.user_one_id = %s OR cr.user_two_id = %s
        ORDER BY last_msg.created_at DESC NULLS LAST, cr.created_at DESC
        """,
        (current_user_id, current_user_id, current_user_id, current_user_id, current_user_id)
    )
    chats = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(chats), 200


@app.route("/chats/<chat_id>/messages", methods=["GET"])
@jwt_required()
def get_chat_messages(chat_id):
    current_user_id = int(get_jwt_identity())
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1
        FROM chat_rooms
        WHERE chat_id = %s AND (user_one_id = %s OR user_two_id = %s)
        """,
        (chat_id, current_user_id, current_user_id)
    )
    if cur.fetchone() is None:
        cur.close()
        conn.close()
        return jsonify({"msg": "Chat not found"}), 404

    cur.execute(
        """
        SELECT
            cm.id::text AS id,
            cm.chat_id,
            cm.sender_id,
            sender.username AS sender_username,
            sender.avatar_url AS sender_avatar_url,
            cm.receiver_id,
            cm.text,
            cm.created_at
        FROM chat_messages cm
        JOIN users sender ON sender.id = cm.sender_id
        WHERE cm.chat_id = %s
        ORDER BY cm.created_at ASC
        """,
        (chat_id,)
    )
    messages = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(messages), 200


@sock.route("/ws/chat")
def chat_socket(ws):
    token = request.args.get("token")
    chat_id = request.args.get("chat_id")

    if not token or not chat_id:
        ws.close()
        return

    try:
        decoded = decode_token(token)
        current_user_id = int(decoded["sub"])
    except Exception:
        ws.close()
        return

    room_connections = active_connections.setdefault(chat_id, [])
    room_connections.append(ws)

    try:
        while True:
            raw_message = ws.receive()
            if raw_message is None:
                break

            data = json.loads(raw_message)
            if data.get("type") != "message":
                continue

            payload = data.get("payload") or {}
            sender_id = int(payload["sender_id"])
            receiver_id = int(payload["receiver_id"])
            text = payload["text"].strip()

            if sender_id != current_user_id or not text:
                continue

            created_at = datetime.utcnow().isoformat()

            conn = get_db_connection()
            if conn is None:
                continue

            ensure_chat_tables(conn)
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO chat_rooms (chat_id, user_one_id, user_two_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id) DO NOTHING
                """,
                (chat_id, min(sender_id, receiver_id), max(sender_id, receiver_id))
            )

            cur.execute(
                """
                INSERT INTO chat_messages (chat_id, sender_id, receiver_id, text, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (chat_id, sender_id, receiver_id, text, created_at)
            )
            message_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()

            outgoing = {
                "type": "message",
                "payload": {
                    "id": str(message_id),
                    "chat_id": chat_id,
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "sender_username": payload.get("sender_username"),
                    "sender_avatar_url": payload.get("sender_avatar_url"),
                    "text": text,
                    "created_at": created_at
                }
            }

            stale = []
            for connection in active_connections.get(chat_id, []):
                try:
                    connection.send(json.dumps(outgoing))
                except Exception:
                    stale.append(connection)

            for connection in stale:
                if connection in active_connections.get(chat_id, []):
                    active_connections[chat_id].remove(connection)
    finally:
        if ws in active_connections.get(chat_id, []):
            active_connections[chat_id].remove(ws)


@app.route("/posts/<int:post_id>/comments", methods=["GET"])
def get_comments(post_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            c.*,
            u.username,
            u.avatar_url
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.post_id = %s
        ORDER BY c.created_at ASC
        """,
        (post_id,)
    )
    comments = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(comments), 200


@app.route("/posts/<int:post_id>/comments", methods=["POST"])
@jwt_required()
def add_comment(post_id):
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    conn = get_db_connection()
    if conn is None:
        return jsonify({"msg": "Database connection error"}), 500

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO comments (post_id, user_id, comment_text) VALUES (%s, %s, %s)",
        (post_id, user_id, data["comment_text"])
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Пікір қосылды"}), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
