import os
from dotenv import load_dotenv

load_dotenv()

import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from PIL import Image
from datetime import datetime, time
import math
import re
from timezonefinder import TimezoneFinder
import pytz

# --- OPTIMASI: Pre-compile RegEx & Set Lookup (Kecepatan Instan) ---
RE_CITY_KEYWORD = re.compile(r'(?i)\b(?:kota|kabupaten|kab\.?)\s+([a-zA-Z\s]+)')
RE_CITY_EN = re.compile(r'(?i)\b([a-zA-Z\s]+)\s+city\b')
RE_POSTAL = re.compile(r'\d+')
RE_KECAMATAN = re.compile(r'(?i)\b(?:kecamatan|kec\.?)\b')

PROVINCE_BLACKLIST = {
    'indonesia', 'jawa tengah', 'jateng', 'jawa timur', 'jatim', 'jawa barat', 'jabar', 
    'dki jakarta', 'banten', 'diy', 'daerah istimewa yogyakarta', 'yogyakarta', 'bali', 
    'sumatera utara', 'sumatera barat', 'sumatera selatan', 'lampung', 
    'riau', 'jambi', 'bengkulu', 'kalimantan barat', 'kalimantan timur', 
    'kalimantan selatan', 'kalimantan tengah', 'sulawesi selatan', 
    'sulawesi utara', 'sulawesi tengah', 'sulawesi tenggara', 'papua', 
    'papua barat', 'maluku', 'ntb', 'ntt', 'central java', 'west java', 'east java'
}

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-cicipin-2024')

def process_image(path, size=(600,400)):
    try:
        img = Image.open(path).convert('RGB')
        # Optimasi Anti-Crash untuk Pillow versi terbaru
        try:
            img.thumbnail((size[0], size[1]), Image.Resampling.LANCZOS)
        except AttributeError:
            img.thumbnail((size[0], size[1]), Image.ANTIALIAS)

        new_img = Image.new('RGB', size, (255,255,255))
        x = (size[0] - img.width) // 2
        y = (size[1] - img.height) // 2
        new_img.paste(img, (x, y))
        new_img.save(path)
    except Exception as e:
        app.logger.warning("failed to process image %s: %s", path, e)

# --- REVISI: Hapus Ping Database Biar Loading Vercel Nggak Macet ---
try:
    client = MongoClient(os.environ.get("MONGODB_URI"), serverSelectionTimeoutMS=5000)
    db = client[os.environ.get("DB_NAME")]
    restaurants_collection = db["restaurants"]
except Exception as exc:
    import logging
    logging.getLogger(__name__).error("Database connection failed: %s", exc)
    client, db, restaurants_collection = None, None, None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if db is None:
            flash('Cannot log in: database unreachable', 'danger')
            return render_template('login.html')

        user = db.users.find_one({"username": username})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user.get('username')
            flash('You have successfully logged in', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if "user_id" in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        if db is None:
            flash('Cannot register: database unreachable', 'danger')
            return redirect(url_for('register'))

        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        username = request.form['username'].strip()
        password = request.form['password']
        
        # --- REVISI: Ringankan Enkripsi Password Biar Vercel Nggak Ngos-ngosan ---
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        existing_user = db.users.find_one({"$or": [{"username": username}, {"email": email}]})
        if existing_user:
            flash("Username or Email already exists", "danger")
            return redirect(url_for('register'))

        db.users.insert_one({"full_name": full_name, "email": email, "username": username, "password": hashed_password})
        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

def is_admin():
    return session.get("username") == "admin"

def compute_average_rating(restaurant):
    reviews = restaurant.get('reviews', [])
    if reviews:
        try:
            avg = sum(r.get('rating', 0) for r in reviews) / len(reviews)
        except Exception:
            avg = 0
        restaurant['average_rating'] = round(avg, 1)
    else:
        restaurant['average_rating'] = None
    return restaurant

def compute_open_status(restaurant):
    opening_hours = restaurant.get("opening_hours")
    if not opening_hours:
        restaurant["is_open"] = None
        return restaurant

    try:
        latitude, longitude = restaurant.get('latitude'), restaurant.get('longitude')
        timezone_str = "Asia/Jakarta" 
        if latitude and longitude:
            try:
                tf = TimezoneFinder()
                timezone_str = tf.timezone_at(lat=float(latitude), lng=float(longitude)) or "Asia/Jakarta"
            except Exception:
                pass
        
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz).time()

        match = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', opening_hours)
        if not match:
            restaurant["is_open"] = None
            return restaurant

        open_hour, open_min, close_hour, close_min = map(int, match.groups())
        open_time, close_time = time(open_hour, open_min), time(close_hour, close_min)

        if close_time < open_time:
            restaurant["is_open"] = now >= open_time or now < close_time
        else:
            restaurant["is_open"] = open_time <= now <= close_time
    except Exception:
        restaurant["is_open"] = None

    return restaurant

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0 
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

# --- FUNGSI OPTIMASI: Ekstraksi Kota ---
def extract_real_city(address):
    if not address: return None
    address = address.strip()

    match = RE_CITY_KEYWORD.search(address)
    if match: return match.group(1).split(',')[0].strip().title()
        
    match_en = RE_CITY_EN.search(address)
    if match_en: return match_en.group(1).strip().title()

    parts = [p for p in [p.strip() for p in address.split(',')] if p and not RE_POSTAL.fullmatch(p)]
    if not parts: return None
        
    while parts and parts[-1].lower() in PROVINCE_BLACKLIST:
        parts.pop()

    if parts:
        candidate = parts[-1]
        if RE_KECAMATAN.search(candidate):
            return parts[-2].title() if len(parts) > 1 else None 
        return candidate.title()
    return None

def search_restaurants(search_term=None, min_rating=None, max_price=None, sort_by=None, user_lat=None, user_lon=None):
    if db is None: return []

    query = {}
    if search_term and search_term.lower() != "semua":
        regex = re.compile(re.escape(search_term), re.IGNORECASE)
        query = {"$or": [{"name": regex}, {"category": regex}, {"address": regex}]}

    restaurants = db.restaurants.find(query)
    result = []

    for restaurant in restaurants:
        compute_average_rating(restaurant)
        compute_open_status(restaurant)
        restaurant['review_count'] = len(restaurant.get('reviews', []))

        if user_lat and user_lon and restaurant.get('latitude') and restaurant.get('longitude'):
            restaurant['distance'] = haversine(float(user_lat), float(user_lon), float(restaurant['latitude']), float(restaurant['longitude']))
            restaurant['distance_str'] = f"{restaurant['distance']:.1f} km"
        else:
            restaurant['distance'], restaurant['distance_str'] = float('inf'), ""

        if min_rating is not None and (restaurant['average_rating'] is None or restaurant['average_rating'] < min_rating):
            continue

        result.append(restaurant)

    if sort_by == 'rating': result.sort(key=lambda x: x.get('average_rating') or 0, reverse=True)
    elif sort_by == 'terlaris': result.sort(key=lambda x: x.get('review_count') or 0, reverse=True)
    elif sort_by == 'jarak' and user_lat and user_lon: result.sort(key=lambda x: x.get('distance'))

    return result

@app.route('/')
def index():
    if "user_id" not in session: return redirect(url_for('login'))

    category = request.args.get("category")
    min_rating = request.args.get("min_rating", type=float)
    sort_by = request.args.get("sort_by")
    user_lat, user_lon = request.args.get("user_lat", type=float), request.args.get("user_lon", type=float)

    restaurants = search_restaurants(category, min_rating, None, sort_by, user_lat, user_lon)

    restaurant_count = total_reviews = city_count = 0

    if db is not None:
        try:
            restaurant_count = db.restaurants.count_documents({})
            reviews_agg = list(db.restaurants.aggregate([
                {"$project": {"count": {"$size": {"$ifNull": ["$reviews", []]}}}},
                {"$group": {"_id": None, "total": {"$sum": "$count"}}}
            ]))
            total_reviews = reviews_agg[0]["total"] if reviews_agg else 0

            city_set = {extract_real_city(res.get("address", "")) for res in db.restaurants.find({}, {"address": 1})}
            city_set.discard(None)
            city_count = len(city_set)
        except Exception as exc:
            app.logger.warning("Failed to compute dashboard stats: %s", exc)

    saved_restaurant_ids = []
    if "user_id" in session and db is not None:
        saved_restaurant_ids = [str(w["restaurant_id"]) for w in db.wishlists.find({"user_id": session["user_id"]})]

    return render_template(
        'index.html', restaurants=restaurants, username=session.get("username"),
        saved_restaurant_ids=saved_restaurant_ids, sort_by=sort_by,
        is_authenticated=True, is_admin=is_admin(),
        dashboard_stats={'restaurant_count': restaurant_count, 'total_reviews': total_reviews, 'city_count': city_count}
    )

@app.route('/add_restaurant', methods=['GET', 'POST'])
def add_restaurant():
    if "user_id" not in session or not is_admin(): return redirect(url_for("index"))

    if request.method == 'POST':
        try:
            image_url = None
            if 'image' in request.files and request.files.get("image").filename != "":
                image_url = cloudinary.uploader.upload(request.files.get("image"))["secure_url"]

            db.restaurants.insert_one({
                "name": request.form.get('name'), "category": request.form.get('category'),
                "address": request.form.get('address'), "latitude": float(request.form.get('latitude', 0)),
                "longitude": float(request.form.get('longitude', 0)), "opening_hours": request.form.get('opening_hours', '').strip() or None,
                "price_range": request.form.get('price_range'), "image_url": image_url, "reviews": []
            })
            flash("Restaurant added successfully!", "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash("Failed to add restaurant", "danger")

    return render_template('add_restaurant.html')

@app.route('/edit_restaurant/<restaurant_id>', methods=['GET', 'POST'])
def edit_restaurant(restaurant_id):
    if "user_id" not in session or not is_admin(): return redirect(url_for("index"))
    restaurant = db.restaurants.find_one({"_id": ObjectId(restaurant_id)})

    if request.method == 'POST':
        update_fields = {
            "name": request.form['name'], "category": request.form['category'], "address": request.form['address'],
            "opening_hours": request.form.get('opening_hours', '').strip() or None,
            "latitude": float(request.form.get('latitude', 0)), "longitude": float(request.form.get('longitude', 0)),
            "price_range": request.form['price_range']
        }
        if 'image' in request.files and request.files.get("image").filename != "":
            update_fields["image_url"] = cloudinary.uploader.upload(request.files.get("image"))["secure_url"]

        db.restaurants.update_one({"_id": ObjectId(restaurant_id)}, {"$set": update_fields})
        flash("Restaurant updated successfully!", "success")
        return redirect(url_for('index'))

    return render_template('edit_restaurant.html', restaurant=restaurant)

@app.route('/delete_restaurant/<restaurant_id>')
def delete_restaurant(restaurant_id):
    if is_admin():
        db.restaurants.delete_one({"_id": ObjectId(restaurant_id)})
        flash("Restaurant deleted successfully!", "success")
    return redirect(url_for('index'))

@app.route('/add_review/<restaurant_id>', methods=['GET', 'POST'])
def add_review(restaurant_id):
    if "user_id" not in session: return redirect(url_for("login"))
    restaurant = db.restaurants.find_one({"_id": ObjectId(restaurant_id)})

    if request.method == 'POST':
        review_image = None
        if 'image' in request.files and request.files['image'].filename:
            review_image = cloudinary.uploader.upload(request.files['image'], resource_type="image")["secure_url"]

        db.restaurants.update_one(
            {"_id": ObjectId(restaurant_id)},
            {"$push": {"reviews": {
                "user_id": session["user_id"], "username": session["username"],
                "rating": float(request.form.get('rating', 0)), "comment": request.form['comment'],
                "image_url": review_image, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            }}}
        )
        flash("Review added successfully!", "success")
        return redirect(url_for('restaurant_detail', restaurant_id=restaurant_id))

    return render_template('add_review.html', restaurant=restaurant)

@app.route('/restaurant/<restaurant_id>')
def restaurant_detail(restaurant_id):
    restaurant = db.restaurants.find_one({"_id": ObjectId(restaurant_id)})
    if restaurant:
        compute_average_rating(restaurant)
        compute_open_status(restaurant)
        
        rating_counts = {stars: 0 for stars in range(1, 6)}
        total_reviews = len(restaurant.get('reviews', []))
        for review in restaurant.get('reviews', []):
            try: star_value = int(float(review.get('rating', 0)))
            except: star_value = 0
            if 1 <= star_value <= 5: rating_counts[star_value] += 1

        rating_percentages = {star: round((rating_counts[star] / total_reviews * 100), 1) if total_reviews > 0 else 0 for star in range(1, 6)}

        return render_template(
            'restaurant_detail.html', restaurant=restaurant, rating_counts=rating_counts,
            rating_percentages=rating_percentages, total_reviews=total_reviews,
            username=session.get('username'), is_authenticated="user_id" in session
        )
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have successfully logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/toggle_wishlist', methods=['POST'])
def toggle_wishlist():
    if "user_id" not in session: return {"success": False, "message": "Unauthorized"}, 401
    restaurant_id = request.json.get("restaurant_id")
    existing = db.wishlists.find_one({"user_id": session["user_id"], "restaurant_id": ObjectId(restaurant_id)})

    if existing:
        db.wishlists.delete_one({"_id": existing["_id"]})
        return {"success": True, "is_saved": False}
    else:
        db.wishlists.insert_one({"user_id": session["user_id"], "restaurant_id": ObjectId(restaurant_id)})
        return {"success": True, "is_saved": True}

@app.route('/wishlist')
def wishlist():
    if "user_id" not in session: return redirect(url_for("login"))
    restaurant_ids = [w["restaurant_id"] for w in db.wishlists.find({"user_id": session["user_id"]})]
    restaurants = list(db.restaurants.find({"_id": {"$in": restaurant_ids}}))

    for r in restaurants: compute_average_rating(r); compute_open_status(r)
    return render_template('wishlist.html', restaurants=restaurants, username=session["username"], saved_restaurant_ids=[str(i) for i in restaurant_ids])

if __name__ == '__main__':
    app.run(debug=True)