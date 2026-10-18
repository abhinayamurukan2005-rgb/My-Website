import sqlite3, json, os, uuid
from werkzeug.utils import secure_filename
from functools import wraps
from flask import Flask, render_template, request, redirect, session, g, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))       # works on your laptop and on a hosting server
_key = os.path.join(BASE, "secret.key")
if not os.path.exists(_key):
    open(_key, "w").write(uuid.uuid4().hex + uuid.uuid4().hex)
app.secret_key = open(_key).read()
DB = os.path.join(BASE, "busmate.db")
UPLOAD_DIR = os.path.join(BASE, "static", "uploads")
ALLOWED = {"png", "jpg", "jpeg", "webp"}
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# departure time slots every 30 minutes, shown in 12-hour format
TIMES = [(f"{h:02d}:{m:02d}", f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}") for h in range(24) for m in (0, 30)]
app.jinja_env.globals["TIMES"] = TIMES

@app.template_filter("ampm")
def ampm(t):
    try:
        h, m = map(int, str(t).split(":")); return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
    except Exception:
        return t

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB)
    c.executescript(open(os.path.join(BASE, "schema.sql")).read())
    for col in ("payment_method TEXT", "payment_ref TEXT", "phone TEXT"):      # upgrade older databases
        try: c.execute("ALTER TABLE bookings ADD COLUMN " + col)
        except sqlite3.OperationalError: pass
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users(name,email,password,gender,role) VALUES('Admin','admin@busmate.com',?,'M','admin')",
                  (generate_password_hash("admin123"),))
    if not c.execute("SELECT 1 FROM routes").fetchone():
        c.execute("INSERT INTO routes(bus_name,bus_type,source,destination,travel_date,dep_time,price) VALUES('BusMate Express','AC Seater 2+2','Coimbatore','Chennai','2026-10-25','21:30',650)")
    c.commit(); c.close()

def norm_phone(v):
    v = "".join(ch for ch in v if ch.isdigit())
    if len(v) == 12 and v.startswith("91"): v = v[2:]
    return v if len(v) == 10 and v[0] in "6789" else ""

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if session.get("role") != "admin":
            flash("Admins only. Please log in with the admin password.")
            return redirect("/admin/login")
        return f(*a, **k)
    return w

@app.template_filter("t12")
def t12(v):
    try:
        h, m = map(int, v.split(":")); return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
    except Exception:
        return v

@app.template_filter("dmy")
def dmy(v):
    try:
        y, m, d = v.split("-"); return f"{int(d)} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)-1]} {y}"
    except Exception:
        return v

@app.route("/")
def home():
    s, d, t = request.args.get("source", ""), request.args.get("destination", ""), request.args.get("date", "")
    q = "SELECT * FROM routes WHERE source LIKE ? AND destination LIKE ? AND travel_date LIKE ?"
    routes = db().execute(q, (f"%{s}%", f"%{d}%", f"%{t}%")).fetchall()
    return render_template("home.html", routes=routes)

@app.route("/login")
@app.route("/register")
def no_passenger_login():
    return redirect("/")         # passengers book with a mobile number, no account needed

@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

@app.route("/route/<int:rid>/seats")
def seats(rid):
    r = db().execute("SELECT * FROM routes WHERE id=?", (rid,)).fetchone()
    return render_template("seats.html", r=r)

@app.route("/api/seats/<int:rid>")
def api_seats(rid):
    rows = db().execute("SELECT seat_no, passenger_gender FROM booked_seats WHERE route_id=?", (rid,)).fetchall()
    return jsonify({str(r["seat_no"]): r["passenger_gender"] for r in rows})  # gender only, no names

@app.route("/book", methods=["POST"])
def book():
    rid = int(request.form["route_id"])
    phone = norm_phone(request.form.get("phone", ""))
    if not phone:
        flash("Please enter a valid 10-digit mobile number"); return redirect(f"/route/{rid}/seats")
    items = json.loads(request.form["data"])
    if not items:
        flash("Select at least one seat"); return redirect(f"/route/{rid}/seats")
    taken = {x["seat_no"] for x in db().execute("SELECT seat_no FROM booked_seats WHERE route_id=?", (rid,))}
    if any(int(i["seat"]) in taken for i in items):
        flash("Sorry, one of those seats was just booked. Please pick again."); return redirect(f"/route/{rid}/seats")
    price = db().execute("SELECT price FROM routes WHERE id=?", (rid,)).fetchone()["price"]
    session["pending"] = {"rid": rid, "items": items, "total": price * len(items), "phone": phone}
    return redirect("/payment")      # the booking is saved only after payment succeeds

@app.route("/payment", methods=["GET", "POST"])
def payment():
    p = session.get("pending")
    if not p: return redirect("/")
    r = db().execute("SELECT * FROM routes WHERE id=?", (p["rid"],)).fetchone()
    if request.method == "POST":
        f = request.form; m = f.get("method"); card = f.get("card", "").replace(" ", "")
        ok = (m == "UPI" and "@" in f.get("upi", "")) or \
             (m == "Card" and len(card) == 16 and card.isdigit() and f.get("cvv", "").isdigit()) or \
             (m == "NetBanking" and f.get("bank"))
        if not ok:
            flash("Please check your payment details"); return redirect("/payment")
        ref = "BM" + uuid.uuid4().hex[:8].upper()       # demo only: card details are never stored
        try:
            cur = db().execute("INSERT INTO bookings(route_id,total,payment_method,payment_ref,phone) VALUES(?,?,?,?,?)",
                               (p["rid"], p["total"], m, ref, p["phone"]))
            for i in p["items"]:
                db().execute("INSERT INTO booked_seats(booking_id,route_id,seat_no,passenger_name,passenger_gender) VALUES(?,?,?,?,?)",
                             (cur.lastrowid, p["rid"], int(i["seat"]), i["name"], i["gender"]))
            db().commit()
        except sqlite3.IntegrityError:
            db().rollback(); session.pop("pending", None)
            flash("Sorry, a seat was just booked by someone else. Payment not taken. Please pick again.")
            return redirect(f"/route/{p['rid']}/seats")
        session.pop("pending", None)
        return redirect(f"/ticket/{ref}")
    return render_template("payment.html", r=r, p=p)

@app.route("/ticket/<ref>")
def ticket(ref):
    b = db().execute("""SELECT b.*, r.bus_name, r.source, r.destination, r.travel_date, r.dep_time, GROUP_CONCAT(s.seat_no) AS seats
        FROM bookings b JOIN routes r ON r.id=b.route_id JOIN booked_seats s ON s.booking_id=b.id
        WHERE b.payment_ref=? GROUP BY b.id""", (ref,)).fetchone()
    if not b: return redirect("/")
    return render_template("confirmation.html", b=b)

@app.route("/my-tickets")
def my_tickets():
    raw = request.args.get("phone", ""); phone = norm_phone(raw); rows = None
    if raw and not phone:
        flash("Please enter a valid 10-digit mobile number")
    elif phone:
        rows = db().execute("""SELECT b.id, b.total, b.payment_method, b.payment_ref, r.bus_name, r.source, r.destination, r.travel_date, r.dep_time,
            GROUP_CONCAT(s.seat_no) AS seats FROM bookings b JOIN routes r ON r.id=b.route_id JOIN booked_seats s ON s.booking_id=b.id
            WHERE b.phone=? GROUP BY b.id ORDER BY b.id DESC""", (phone,)).fetchall()
    return render_template("bookings.html", rows=rows, phone=phone)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=? AND role='admin'", (request.form["email"],)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], name=u["name"], role="admin")
            return redirect("/admin")
        flash("Invalid admin email or password")
    return render_template("admin_login.html")

@app.route("/admin/password", methods=["POST"])
@admin_required
def admin_password():
    u = db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    if not check_password_hash(u["password"], request.form["old"]) or len(request.form["new"]) < 6:
        flash("Wrong current password, or new password is shorter than 6 characters")
    else:
        db().execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(request.form["new"]), u["id"]))
        db().commit(); flash("Admin password changed")
    return redirect("/admin")

@app.route("/admin")
@admin_required
def admin():
    d = db()
    q = request.args.get("q", "").strip(); date = request.args.get("date", "").strip()
    stats = d.execute("SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS rev FROM bookings").fetchone()
    routes = d.execute("SELECT * FROM routes WHERE bus_name LIKE ? AND travel_date LIKE ? ORDER BY travel_date, dep_time",
                       (f"%{q}%", f"%{date}%")).fetchall()
    passengers = d.execute("""SELECT s.booking_id, s.seat_no, s.passenger_name, s.passenger_gender, r.bus_name, r.source, r.destination,
        r.travel_date, r.dep_time, COALESCE(b.phone, u.name) AS booked_by, b.payment_method, b.payment_ref, b.created
        FROM booked_seats s JOIN routes r ON r.id=s.route_id JOIN bookings b ON b.id=s.booking_id LEFT JOIN users u ON u.id=b.user_id
        WHERE r.bus_name LIKE ? AND r.travel_date LIKE ? ORDER BY s.id DESC""", (f"%{q}%", f"%{date}%")).fetchall()
    chart = d.execute("SELECT r.bus_name || ': ' || r.source || ' → ' || r.destination AS label, COUNT(s.id) AS n FROM routes r LEFT JOIN booked_seats s ON s.route_id=r.id GROUP BY r.id").fetchall()
    imgs = {}
    for i in d.execute("SELECT * FROM bus_images").fetchall():
        imgs.setdefault(i["route_id"], []).append(i)
    return render_template("admin.html", stats=stats, routes=routes, passengers=passengers, imgs=imgs, chart=chart, q=q, date=date)

@app.route("/admin/add", methods=["POST"])
@admin_required
def add_route():
    f = request.form
    db().execute("INSERT INTO routes(bus_name,bus_type,source,destination,travel_date,dep_time,price) VALUES(?,?,?,?,?,?,?)",
                 (f["bus_name"], f["bus_type"], f["source"], f["destination"], f["travel_date"], f["dep_time"], f["price"]))
    db().commit(); return redirect("/admin")

@app.route("/admin/delete/<int:rid>")
@admin_required
def del_route(rid):
    db().execute("DELETE FROM routes WHERE id=?", (rid,)); db().commit(); return redirect("/admin")

def route_images(rid):
    rows = db().execute("SELECT * FROM bus_images WHERE route_id=?", (rid,)).fetchall()
    if rows:
        return ["/static/uploads/" + r["image_path"] for r in rows]
    return [f"/static/images/default/{n}.svg" for n in ("seats", "aisle", "cabin")]  # shown until admin uploads photos

@app.route("/route/<int:rid>/preview")
def preview(rid):
    r = db().execute("SELECT * FROM routes WHERE id=?", (rid,)).fetchone()
    return render_template("preview.html", r=r, images=route_images(rid))

@app.route("/admin/upload/<int:rid>", methods=["POST"])
@admin_required
def upload(rid):
    for f in request.files.getlist("photos"):
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext in ALLOWED:
            name = uuid.uuid4().hex + "." + ext
            f.save(os.path.join(UPLOAD_DIR, secure_filename(name)))
            db().execute("INSERT INTO bus_images(route_id,image_path) VALUES(?,?)", (rid, name))
    db().commit(); return redirect("/admin")

@app.route("/admin/image/delete/<int:iid>")
@admin_required
def del_image(iid):
    row = db().execute("SELECT image_path FROM bus_images WHERE id=?", (iid,)).fetchone()
    if row:
        try: os.remove(os.path.join(UPLOAD_DIR, row["image_path"]))
        except OSError: pass
        db().execute("DELETE FROM bus_images WHERE id=?", (iid,)); db().commit()
    return redirect("/admin")

@app.route("/admin/edit/<int:rid>", methods=["GET", "POST"])
@admin_required
def edit_route(rid):
    if request.method == "POST":
        f = request.form
        db().execute("UPDATE routes SET bus_name=?,bus_type=?,source=?,destination=?,travel_date=?,dep_time=?,price=? WHERE id=?",
                     (f["bus_name"], f["bus_type"], f["source"], f["destination"], f["travel_date"], f["dep_time"], f["price"], rid))
        db().commit(); return redirect("/admin")
    r = db().execute("SELECT * FROM routes WHERE id=?", (rid,)).fetchone()
    return render_template("edit_route.html", r=r)

def cancel_booking(bid):
    db().execute("UPDATE payments SET status='Refunded' WHERE booking_id=?", (bid,))   # simulated refund
    db().execute("DELETE FROM booked_seats WHERE booking_id=?", (bid,))   # frees the seats again
    db().execute("DELETE FROM bookings WHERE id=?", (bid,)); db().commit()

@app.route("/admin/cancel/<int:bid>")
@admin_required
def admin_cancel(bid):
    cancel_booking(bid); return redirect(request.referrer or "/admin")

@app.route("/cancel/<int:bid>", methods=["POST"])
def user_cancel(bid):
    phone = norm_phone(request.form.get("phone", ""))
    if phone and db().execute("SELECT 1 FROM bookings WHERE id=? AND phone=?", (bid, phone)).fetchone():
        cancel_booking(bid); flash("Booking cancelled")
    return redirect("/my-tickets?phone=" + phone)

init_db()      # also runs when a hosting server loads the app

if __name__ == "__main__":
    app.run(debug=True, port=5050)
