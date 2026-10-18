CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, gender TEXT, role TEXT DEFAULT 'user');
CREATE TABLE IF NOT EXISTS routes(id INTEGER PRIMARY KEY, bus_name TEXT, bus_type TEXT, source TEXT, destination TEXT, travel_date TEXT, dep_time TEXT, price INTEGER);
CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY, user_id INTEGER, route_id INTEGER, total INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP, payment_method TEXT, payment_ref TEXT, phone TEXT);
CREATE TABLE IF NOT EXISTS booked_seats(id INTEGER PRIMARY KEY, booking_id INTEGER, route_id INTEGER, seat_no INTEGER, passenger_name TEXT, passenger_gender TEXT, UNIQUE(route_id, seat_no));
CREATE TABLE IF NOT EXISTS bus_images(id INTEGER PRIMARY KEY, route_id INTEGER, image_path TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, booking_id INTEGER, method TEXT, amount INTEGER, txn_id TEXT, status TEXT, paid_at TEXT DEFAULT CURRENT_TIMESTAMP);
