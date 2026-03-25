"""
Smart Local Business Cloud CRM — Flask Backend
================================================
Tech: Flask + SQLite (swap DB_URI for RDS in production)
Auth: JWT (replace with AWS Cognito in production)
AWS: S3 for images, Lambda stub for AI insights

Run:
    pip install flask flask-cors flask-sqlalchemy flask-jwt-extended
    python app.py

Environment Variables (create a .env file):
    SECRET_KEY=your-secret-key-here
    DATABASE_URL=sqlite:///bizcrmdb.db          # dev
    # DATABASE_URL=mysql+pymysql://user:pass@rds-endpoint/bizcrmdb  # prod
    AWS_ACCESS_KEY_ID=your-key
    AWS_SECRET_ACCESS_KEY=your-secret
    AWS_REGION=ap-south-1
    S3_BUCKET=bizcrmapp-images
    JWT_SECRET_KEY=your-jwt-secret
"""

import os
import json
import hashlib
import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)

# ─────────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=".", template_folder=".")
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["SECRET_KEY"]                      = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
app.config["JWT_SECRET_KEY"]                  = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"]         = os.getenv("DATABASE_URL", "sqlite:///bizcrmdb.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]  = False
app.config["JWT_ACCESS_TOKEN_EXPIRES"]        = datetime.timedelta(hours=12)

db  = SQLAlchemy(app)
jwt = JWTManager(app)

# ─────────────────────────────────────────────────────────
# DATABASE MODELS
# ─────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20),  default="staff")   # admin | staff
    created_at    = db.Column(db.DateTime,    default=datetime.datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = hashlib.sha256(pw.encode()).hexdigest()

    def check_password(self, pw):
        return self.password_hash == hashlib.sha256(pw.encode()).hexdigest()

    def to_dict(self):
        return {"id": self.id, "username": self.username,
                "email": self.email, "role": self.role,
                "created_at": str(self.created_at)}


class Customer(db.Model):
    __tablename__ = "customers"
    id            = db.Column(db.Integer, primary_key=True)
    fname         = db.Column(db.String(80),  nullable=False)
    lname         = db.Column(db.String(80),  nullable=False)
    email         = db.Column(db.String(120), unique=True)
    phone         = db.Column(db.String(20))
    address       = db.Column(db.String(200))
    total_spent   = db.Column(db.Float,   default=0.0)
    visits        = db.Column(db.Integer, default=0)
    joined        = db.Column(db.Date,    default=datetime.date.today)
    created_by    = db.Column(db.Integer, db.ForeignKey("users.id"))

    def loyalty_tier(self):
        if self.total_spent >= 15000: return "Gold"
        if self.total_spent >= 7000:  return "Silver"
        return "Bronze"

    def loyalty_score(self):
        return min(100, int(self.total_spent / 250))

    def to_dict(self):
        return {"id": self.id, "fname": self.fname, "lname": self.lname,
                "email": self.email, "phone": self.phone,
                "address": self.address, "total_spent": self.total_spent,
                "visits": self.visits, "joined": str(self.joined),
                "loyalty_tier": self.loyalty_tier(),
                "loyalty_score": self.loyalty_score()}


class Product(db.Model):
    __tablename__ = "products"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), nullable=False)
    category    = db.Column(db.String(60),  nullable=False)
    price       = db.Column(db.Float,  nullable=False)
    stock       = db.Column(db.Integer, default=0)
    low_alert   = db.Column(db.Integer, default=10)
    image_url   = db.Column(db.String(500), default="📦")
    description = db.Column(db.Text)
    sold        = db.Column(db.Integer, default=0)
    created_at  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def is_low_stock(self):
        return self.stock <= self.low_alert

    def to_dict(self):
        return {"id": self.id, "name": self.name, "category": self.category,
                "price": self.price, "stock": self.stock,
                "low_alert": self.low_alert, "image_url": self.image_url,
                "description": self.description, "sold": self.sold,
                "is_low_stock": self.is_low_stock(),
                "created_at": str(self.created_at)}


class Sale(db.Model):
    __tablename__ = "sales"
    id          = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey("products.id"),  nullable=False)
    qty         = db.Column(db.Integer, nullable=False)
    unit_price  = db.Column(db.Float,   nullable=False)
    total       = db.Column(db.Float,   nullable=False)
    method      = db.Column(db.String(30), default="Cash")
    sale_date   = db.Column(db.Date,    default=datetime.date.today)
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    customer    = db.relationship("Customer", backref="sales")
    product     = db.relationship("Product",  backref="sales")

    def to_dict(self):
        return {"id": self.id, "customer_id": self.customer_id,
                "product_id": self.product_id, "qty": self.qty,
                "unit_price": self.unit_price, "total": self.total,
                "method": self.method, "sale_date": str(self.sale_date),
                "customer_name": f"{self.customer.fname} {self.customer.lname}" if self.customer else "",
                "product_name": self.product.name if self.product else ""}


class InventoryLog(db.Model):
    __tablename__ = "inventory_logs"
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    action     = db.Column(db.String(30))  # restock | sale | adjustment
    qty_change = db.Column(db.Integer)
    note       = db.Column(db.String(200))
    logged_at  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "product_id": self.product_id,
                "action": self.action, "qty_change": self.qty_change,
                "note": self.note, "logged_at": str(self.logged_at)}


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def admin_required(fn):
    """Decorator: requires admin role in JWT."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        uid  = get_jwt_identity()
        user = User.query.get(uid)
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def success(data=None, msg="OK", code=200):
    return jsonify({"status": "success", "message": msg, "data": data}), code


def error(msg="Error", code=400):
    return jsonify({"status": "error", "message": msg}), code


# ─────────────────────────────────────────────────────────
# ROUTES — STATIC (serve the HTML frontend)
# ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ─────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
def register():
    """POST /api/auth/register  { username, email, password, role? }"""
    data = request.get_json() or {}
    if not data.get("username") or not data.get("email") or not data.get("password"):
        return error("username, email and password are required")

    if User.query.filter_by(email=data["email"]).first():
        return error("Email already registered", 409)

    user = User(
        username=data["username"].strip(),
        email=data["email"].strip().lower(),
        role=data.get("role", "staff")
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=user.id)
    return success({"token": token, "user": user.to_dict()}, "Registered successfully", 201)


@app.route("/api/auth/login", methods=["POST"])
def login():
    """POST /api/auth/login  { email, password }"""
    data = request.get_json() or {}
    user = User.query.filter_by(email=data.get("email", "").lower()).first()

    if not user or not user.check_password(data.get("password", "")):
        return error("Invalid credentials", 401)

    token = create_access_token(identity=user.id)
    return success({"token": token, "user": user.to_dict()}, "Login successful")


@app.route("/api/auth/me", methods=["GET"])
@jwt_required()
def get_me():
    user = User.query.get(get_jwt_identity())
    return success(user.to_dict())


# ─────────────────────────────────────────────────────────
# CUSTOMER ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/customers", methods=["GET"])
@jwt_required()
def get_customers():
    """GET /api/customers?q=name&tier=Gold&page=1&per_page=20"""
    q       = request.args.get("q", "")
    tier    = request.args.get("tier", "")
    page    = int(request.args.get("page", 1))
    per_pg  = int(request.args.get("per_page", 20))

    query = Customer.query
    if q:
        query = query.filter(
            (Customer.fname + " " + Customer.lname).ilike(f"%{q}%") |
            Customer.email.ilike(f"%{q}%") |
            Customer.phone.ilike(f"%{q}%")
        )

    customers = query.order_by(Customer.total_spent.desc()).paginate(
        page=page, per_page=per_pg, error_out=False
    )

    result = [c.to_dict() for c in customers.items]
    if tier:
        result = [c for c in result if c["loyalty_tier"] == tier]

    return success({
        "customers": result,
        "total": customers.total,
        "pages": customers.pages,
        "page": page
    })


@app.route("/api/customers/<int:cid>", methods=["GET"])
@jwt_required()
def get_customer(cid):
    c = Customer.query.get_or_404(cid)
    data = c.to_dict()
    data["sales"] = [s.to_dict() for s in c.sales]
    return success(data)


@app.route("/api/customers", methods=["POST"])
@jwt_required()
def create_customer():
    data = request.get_json() or {}
    if not data.get("fname") or not data.get("email"):
        return error("fname and email are required")

    if Customer.query.filter_by(email=data["email"]).first():
        return error("Customer with this email already exists", 409)

    c = Customer(
        fname=data["fname"].strip(),
        lname=data.get("lname", "").strip(),
        email=data["email"].strip().lower(),
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        created_by=get_jwt_identity()
    )
    db.session.add(c)
    db.session.commit()
    return success(c.to_dict(), "Customer added", 201)


@app.route("/api/customers/<int:cid>", methods=["PUT"])
@jwt_required()
def update_customer(cid):
    c    = Customer.query.get_or_404(cid)
    data = request.get_json() or {}
    for field in ("fname", "lname", "phone", "address"):
        if field in data:
            setattr(c, field, data[field])
    if "email" in data:
        c.email = data["email"].strip().lower()
    db.session.commit()
    return success(c.to_dict(), "Customer updated")


@app.route("/api/customers/<int:cid>", methods=["DELETE"])
@admin_required
def delete_customer(cid):
    c = Customer.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return success(None, "Customer deleted")


# ─────────────────────────────────────────────────────────
# PRODUCT ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/products", methods=["GET"])
@jwt_required()
def get_products():
    """GET /api/products?q=&category=&low_stock=true"""
    q         = request.args.get("q", "")
    category  = request.args.get("category", "")
    low_only  = request.args.get("low_stock") == "true"

    query = Product.query
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%") | Product.description.ilike(f"%{q}%"))
    if category:
        query = query.filter(Product.category == category)

    products = query.order_by(Product.sold.desc()).all()
    if low_only:
        products = [p for p in products if p.is_low_stock()]

    return success({"products": [p.to_dict() for p in products]})


@app.route("/api/products/<int:pid>", methods=["GET"])
@jwt_required()
def get_product(pid):
    p = Product.query.get_or_404(pid)
    return success(p.to_dict())


@app.route("/api/products", methods=["POST"])
@jwt_required()
def create_product():
    data = request.get_json() or {}
    if not data.get("name") or not data.get("price"):
        return error("name and price are required")

    p = Product(
        name=data["name"].strip(),
        category=data.get("category", "Other"),
        price=float(data["price"]),
        stock=int(data.get("stock", 0)),
        low_alert=int(data.get("low_alert", 10)),
        image_url=data.get("image_url", "📦"),
        description=data.get("description", "")
    )
    db.session.add(p)
    db.session.commit()

    _log_inventory(p.id, "initial_stock", p.stock, "Product created")
    return success(p.to_dict(), "Product added", 201)


@app.route("/api/products/<int:pid>", methods=["PUT"])
@jwt_required()
def update_product(pid):
    p    = Product.query.get_or_404(pid)
    data = request.get_json() or {}

    old_stock = p.stock
    for field in ("name", "category", "price", "stock", "low_alert", "image_url", "description"):
        if field in data:
            setattr(p, field, data[field])

    if p.stock != old_stock:
        _log_inventory(p.id, "adjustment", p.stock - old_stock, "Manual stock update")

    db.session.commit()
    return success(p.to_dict(), "Product updated")


@app.route("/api/products/<int:pid>/restock", methods=["POST"])
@jwt_required()
def restock_product(pid):
    p    = Product.query.get_or_404(pid)
    data = request.get_json() or {}
    qty  = int(data.get("qty", 50))
    p.stock += qty
    _log_inventory(p.id, "restock", qty, data.get("note", "Restock"))
    db.session.commit()
    return success(p.to_dict(), f"Restocked {qty} units")


@app.route("/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def delete_product(pid):
    p = Product.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return success(None, "Product deleted")


def _log_inventory(product_id, action, qty_change, note=""):
    log = InventoryLog(product_id=product_id, action=action, qty_change=qty_change, note=note)
    db.session.add(log)


# ─────────────────────────────────────────────────────────
# SALES ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/sales", methods=["GET"])
@jwt_required()
def get_sales():
    """GET /api/sales?from=2025-01-01&to=2025-12-31&customer_id=&page=1"""
    from_d  = request.args.get("from")
    to_d    = request.args.get("to")
    cust_id = request.args.get("customer_id")
    page    = int(request.args.get("page", 1))
    per_pg  = int(request.args.get("per_page", 30))

    query = Sale.query
    if from_d:
        query = query.filter(Sale.sale_date >= from_d)
    if to_d:
        query = query.filter(Sale.sale_date <= to_d)
    if cust_id:
        query = query.filter(Sale.customer_id == int(cust_id))

    sales = query.order_by(Sale.sale_date.desc()).paginate(
        page=page, per_page=per_pg, error_out=False
    )
    total_rev = db.session.query(db.func.sum(Sale.total)).scalar() or 0

    return success({
        "sales": [s.to_dict() for s in sales.items],
        "total_revenue": total_rev,
        "total_orders": Sale.query.count(),
        "pages": sales.pages,
        "page": page
    })


@app.route("/api/sales", methods=["POST"])
@jwt_required()
def create_sale():
    """POST /api/sales { customer_id, product_id, qty, method, sale_date? }"""
    data = request.get_json() or {}
    if not data.get("customer_id") or not data.get("product_id") or not data.get("qty"):
        return error("customer_id, product_id, qty are required")

    product = Product.query.get(data["product_id"])
    if not product:
        return error("Product not found", 404)

    qty = int(data["qty"])
    if product.stock < qty:
        return error(f"Insufficient stock. Available: {product.stock}", 422)

    customer = Customer.query.get(data["customer_id"])
    if not customer:
        return error("Customer not found", 404)

    total = product.price * qty

    sale = Sale(
        customer_id=customer.id,
        product_id=product.id,
        qty=qty,
        unit_price=product.price,
        total=total,
        method=data.get("method", "Cash"),
        sale_date=data.get("sale_date") or datetime.date.today(),
        created_by=get_jwt_identity()
    )
    db.session.add(sale)

    # Update stock and sold count
    product.stock -= qty
    product.sold  += qty

    # Update customer spend
    customer.total_spent += total
    customer.visits      += 1

    # Inventory log
    _log_inventory(product.id, "sale", -qty, f"Sale #{sale.id}")
    db.session.commit()

    response_data = sale.to_dict()
    response_data["low_stock_alert"] = product.is_low_stock()
    return success(response_data, "Sale recorded", 201)


@app.route("/api/sales/<int:sid>", methods=["GET"])
@jwt_required()
def get_sale(sid):
    s = Sale.query.get_or_404(sid)
    return success(s.to_dict())


# ─────────────────────────────────────────────────────────
# INVENTORY LOGS
# ─────────────────────────────────────────────────────────

@app.route("/api/inventory/logs", methods=["GET"])
@jwt_required()
def get_inventory_logs():
    pid  = request.args.get("product_id")
    query = InventoryLog.query
    if pid:
        query = query.filter_by(product_id=int(pid))
    logs = query.order_by(InventoryLog.logged_at.desc()).limit(100).all()
    return success({"logs": [l.to_dict() for l in logs]})


# ─────────────────────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────────────────────

@app.route("/api/dashboard/stats", methods=["GET"])
@jwt_required()
def dashboard_stats():
    """Returns aggregated stats for the dashboard overview."""
    total_rev   = db.session.query(db.func.sum(Sale.total)).scalar() or 0
    total_orders = Sale.query.count()
    total_cust  = Customer.query.count()
    low_stock   = Product.query.filter(Product.stock <= Product.low_alert).count()

    # Monthly revenue (last 6 months)
    today  = datetime.date.today()
    months = []
    for i in range(5, -1, -1):
        m = today.replace(day=1) - datetime.timedelta(days=i*30)
        label = m.strftime("%b")
        start = m.replace(day=1)
        if m.month == 12:
            end = m.replace(year=m.year+1, month=1, day=1)
        else:
            end = m.replace(month=m.month+1, day=1)
        rev = db.session.query(
            db.func.sum(Sale.total)
        ).filter(Sale.sale_date >= start, Sale.sale_date < end).scalar() or 0
        months.append({"month": label, "revenue": float(rev)})

    # Top products
    top_products = db.session.query(
        Product.name, Product.sold, Product.category
    ).order_by(Product.sold.desc()).limit(5).all()

    # Day of week sales
    dow_sales = {}
    all_sales = Sale.query.all()
    for s in all_sales:
        day = s.sale_date.strftime("%a")
        dow_sales[day] = dow_sales.get(day, 0) + s.total

    return success({
        "total_revenue":  float(total_rev),
        "total_orders":   total_orders,
        "total_customers": total_cust,
        "low_stock_count": low_stock,
        "monthly_revenue": months,
        "top_products":   [{"name": p[0], "sold": p[1], "category": p[2]} for p in top_products],
        "dow_sales":      dow_sales
    })


# ─────────────────────────────────────────────────────────
# AI INSIGHTS ENDPOINT (calls Lambda in production)
# ─────────────────────────────────────────────────────────

@app.route("/api/insights", methods=["GET"])
@jwt_required()
def get_insights():
    """
    In production: invoke AWS Lambda function 'bizcrmAIInsights' via boto3.
    Here we compute insights locally for demo purposes.
    """
    products = Product.query.all()
    sales    = Sale.query.all()
    customers = Customer.query.all()

    if not products or not sales:
        return success({"insights": [], "forecast": []})

    # Best seller
    top_sold = max(products, key=lambda p: p.sold)

    # Declining product
    declining = min(products, key=lambda p: p.sold)

    # Best day
    day_totals = {}
    for s in sales:
        day = s.sale_date.strftime("%A")
        day_totals[day] = day_totals.get(day, 0) + s.total
    best_day = max(day_totals, key=day_totals.get) if day_totals else "—"

    # Restock list
    low_products = [p.name for p in products if p.is_low_stock()]

    # Top customer
    top_cust = max(customers, key=lambda c: c.total_spent) if customers else None

    # Average order value
    total_rev = sum(s.total for s in sales)
    avg_order = total_rev / len(sales) if sales else 0

    insights = [
        {"icon": "🏆", "title": "Best Selling Product",
         "text": f"{top_sold.name} leads with {top_sold.sold} units sold. Increase its stock.",
         "category": "product"},
        {"icon": "📉", "title": "Declining Product",
         "text": f"{declining.name} has the lowest sales ({declining.sold} units). Consider a promotion.",
         "category": "product"},
        {"icon": "📅", "title": "Peak Sales Day",
         "text": f"Your best sales day is {best_day}. Maximise promotions on this day.",
         "category": "sales"},
        {"icon": "📦", "title": "Restock Required",
         "text": f"Urgently restock: {', '.join(low_products) if low_products else 'None — all stocked!'}",
         "category": "inventory"},
        {"icon": "👑", "title": "Top Customer",
         "text": f"{top_cust.fname} {top_cust.lname} has spent ₹{top_cust.total_spent:,.0f}. Send a loyalty reward!" if top_cust else "No customers yet.",
         "category": "customer"},
        {"icon": "💡", "title": "Avg Order Value",
         "text": f"Average order is ₹{avg_order:,.0f}. Try upselling to increase this by 15-20%.",
         "category": "sales"},
    ]

    # Simple linear forecast (last 6 months trend)
    forecast = [
        {"month": "Month 1", "projected": round(total_rev * 1.05)},
        {"month": "Month 2", "projected": round(total_rev * 1.08)},
        {"month": "Month 3", "projected": round(total_rev * 1.12)},
        {"month": "Month 4", "projected": round(total_rev * 1.15)},
        {"month": "Month 5", "projected": round(total_rev * 1.18)},
        {"month": "Month 6", "projected": round(total_rev * 1.22)},
    ]

    return success({"insights": insights, "forecast": forecast})


# ─────────────────────────────────────────────────────────
# CHATBOT ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    """POST /api/chat { message: "Which product sold the most?" }"""
    data    = request.get_json() or {}
    message = data.get("message", "").lower().strip()

    if not message:
        return error("message is required")

    products  = Product.query.all()
    sales_all = Sale.query.all()
    customers = Customer.query.all()

    total_rev = sum(s.total for s in sales_all)
    top_sold  = max(products, key=lambda p: p.sold) if products else None
    low_stock = [p for p in products if p.is_low_stock()]
    top_cust  = max(customers, key=lambda c: c.total_spent) if customers else None

    day_totals = {}
    for s in sales_all:
        day = s.sale_date.strftime("%A")
        day_totals[day] = day_totals.get(day, 0) + s.total
    best_day = max(day_totals, key=day_totals.get) if day_totals else "—"

    response = "I can help with product sales, stock levels, customer info, and revenue insights."

    if any(k in message for k in ["top sell", "best sell", "most sell", "popular"]):
        response = f"🏆 {top_sold.name} is your top seller with {top_sold.sold} units sold." if top_sold else "No sales data yet."

    elif any(k in message for k in ["low stock", "restock", "running out"]):
        if low_stock:
            names = ", ".join(p.name for p in low_stock[:5])
            response = f"⚠️ {len(low_stock)} item(s) need restocking: {names}."
        else:
            response = "✅ All products are well stocked!"

    elif any(k in message for k in ["customer", "who buy", "loyal"]):
        response = f"👑 Top customer: {top_cust.fname} {top_cust.lname} — spent ₹{top_cust.total_spent:,.0f}." if top_cust else "No customers yet."

    elif any(k in message for k in ["revenue", "sales", "earn", "income", "money"]):
        avg = total_rev / len(sales_all) if sales_all else 0
        response = f"💰 Total revenue: ₹{total_rev:,.0f} across {len(sales_all)} orders. Avg order: ₹{avg:,.0f}."

    elif any(k in message for k in ["best day", "day of week", "peak day"]):
        response = f"📅 Your peak sales day is {best_day}. Plan promotions accordingly!"

    elif any(k in message for k in ["hello", "hi", "hey", "help"]):
        response = "👋 Hi! Ask me about top products, low stock, customers, revenue, or best sales days."

    return success({"response": response})


# ─────────────────────────────────────────────────────────
# REPORTS / EXPORT ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/reports/sales", methods=["GET"])
@jwt_required()
def export_sales_report():
    """Returns JSON report data; frontend handles CSV conversion."""
    sales = Sale.query.order_by(Sale.sale_date.desc()).all()
    return success({"report": [s.to_dict() for s in sales], "generated_at": str(datetime.datetime.utcnow())})


@app.route("/api/reports/inventory", methods=["GET"])
@jwt_required()
def export_inventory_report():
    products = Product.query.all()
    return success({"report": [p.to_dict() for p in products], "generated_at": str(datetime.datetime.utcnow())})


# ─────────────────────────────────────────────────────────
# NOTIFICATIONS ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    notifs = []
    low_stock = Product.query.filter(Product.stock <= Product.low_alert).all()
    for p in low_stock:
        notifs.append({"type": "red", "text": f"{p.name} is low on stock ({p.stock} left)", "time": "Now"})

    # High value customer milestone
    gold_customers = [c for c in Customer.query.all() if c.loyalty_tier() == "Gold"]
    if gold_customers:
        notifs.append({"type": "green", "text": f"{len(gold_customers)} Gold tier customer(s) this month!", "time": "Today"})

    return success({"notifications": notifs})


# ─────────────────────────────────────────────────────────
# SEARCH ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/search", methods=["GET"])
@jwt_required()
def global_search():
    """GET /api/search?q=jeans"""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return error("Query must be at least 2 characters")

    products  = Product.query.filter(Product.name.ilike(f"%{q}%")).limit(5).all()
    customers = Customer.query.filter(
        (Customer.fname + " " + Customer.lname).ilike(f"%{q}%") |
        Customer.email.ilike(f"%{q}%")
    ).limit(5).all()

    return success({
        "products":  [p.to_dict() for p in products],
        "customers": [c.to_dict() for c in customers]
    })


# ─────────────────────────────────────────────────────────
# AWS S3 PRESIGNED URL (for product image upload)
# ─────────────────────────────────────────────────────────

@app.route("/api/s3/presign", methods=["POST"])
@jwt_required()
def get_presigned_url():
    """
    POST /api/s3/presign { filename: "product.jpg", content_type: "image/jpeg" }
    Returns a presigned S3 URL for direct browser upload.
    Requires: pip install boto3
    """
    try:
        import boto3
        from botocore.exceptions import NoCredentialsError

        data         = request.get_json() or {}
        filename     = data.get("filename", "upload.jpg")
        content_type = data.get("content_type", "image/jpeg")
        bucket       = os.getenv("S3_BUCKET", "bizcrmapp-images")
        region       = os.getenv("AWS_REGION", "ap-south-1")

        s3 = boto3.client("s3", region_name=region)
        key = f"products/{datetime.datetime.utcnow().timestamp()}_{filename}"

        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=300
        )
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        return success({"upload_url": url, "public_url": public_url})

    except ImportError:
        return error("boto3 not installed. Run: pip install boto3")
    except Exception as e:
        return error(str(e), 500)


# ─────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return success({"status": "healthy", "version": "1.0.0",
                    "timestamp": str(datetime.datetime.utcnow())})


# ─────────────────────────────────────────────────────────
# DATABASE SEED (development only)
# ─────────────────────────────────────────────────────────

def seed_database():
    """Seed with sample data for development."""
    if User.query.count():
        return  # Already seeded

    print("🌱 Seeding database...")

    # Admin user
    admin = User(username="admin", email="admin@bizcrmapp.com", role="admin")
    admin.set_password("Admin@1234")
    staff = User(username="staff1", email="staff@bizcrmapp.com", role="staff")
    staff.set_password("Staff@1234")
    db.session.add_all([admin, staff])
    db.session.flush()

    # Customers
    customers_data = [
        ("Priya",    "Sharma",  "priya@email.com",   "9876543210", "Dehradun, UK", 14800, 12),
        ("Rahul",    "Verma",   "rahul@email.com",   "9812345678", "Delhi",         8200,  7),
        ("Anjali",   "Singh",   "anjali@email.com",  "9765432101", "Haridwar, UK", 22500, 18),
        ("Mohammed", "Khan",    "khan@email.com",    "9900112233", "Dehradun, UK",  3400,  3),
        ("Sunita",   "Negi",    "sunita@email.com",  "9811122334", "Mussoorie, UK", 6700,  5),
    ]
    custs = []
    for fn, ln, email, phone, addr, spent, visits in customers_data:
        c = Customer(fname=fn, lname=ln, email=email, phone=phone,
                     address=addr, total_spent=spent, visits=visits, created_by=admin.id)
        db.session.add(c)
        custs.append(c)
    db.session.flush()

    # Products
    products_data = [
        ("Blue Denim Jacket",  "Clothing",     1299, 32, 10, "🧥", "Classic blue denim jacket",     45),
        ("iPhone Case Pro",    "Accessories",   499,  7, 10, "📱", "Protective iPhone case",        88),
        ("White Sneakers",     "Footwear",     1899, 15,  8, "👟", "Classic white sneakers",        31),
        ("Cotton T-Shirt",     "Clothing",      349,  3, 10, "👕", "100% cotton t-shirt",          120),
        ("Wireless Earbuds",   "Electronics",  2499, 20,  5, "🎧", "Bluetooth wireless earbuds",    55),
        ("Leather Wallet",     "Accessories",   799, 42, 10, "👛", "Genuine leather bifold wallet", 67),
        ("Cargo Shorts",       "Clothing",      699,  5,  8, "🩳", "Multi-pocket cargo shorts",     29),
        ("Running Shoes",      "Footwear",     2199, 18,  8, "👟", "Lightweight running shoes",     43),
    ]
    prods = []
    for name, cat, price, stock, low, img, desc, sold in products_data:
        p = Product(name=name, category=cat, price=price, stock=stock,
                    low_alert=low, image_url=img, description=desc, sold=sold)
        db.session.add(p)
        prods.append(p)
    db.session.flush()

    # Sales
    sales_data = [
        (custs[0].id, prods[0].id, 2, "UPI",       "2025-01-15"),
        (custs[1].id, prods[3].id, 3, "Cash",      "2025-01-18"),
        (custs[2].id, prods[4].id, 1, "Card",      "2025-01-20"),
        (custs[0].id, prods[1].id, 2, "UPI",       "2025-02-02"),
        (custs[3].id, prods[2].id, 1, "Cash",      "2025-02-10"),
        (custs[2].id, prods[5].id, 2, "Card",      "2025-02-14"),
        (custs[4].id, prods[3].id, 4, "UPI",       "2025-03-05"),
        (custs[1].id, prods[6].id, 2, "Cash",      "2025-03-12"),
        (custs[2].id, prods[0].id, 1, "UPI",       "2025-03-18"),
        (custs[0].id, prods[7].id, 1, "NetBanking","2025-04-01"),
    ]
    for cid, pid, qty, method, date_str in sales_data:
        prod = next(p for p in prods if p.id == pid)
        sale = Sale(customer_id=cid, product_id=pid, qty=qty,
                    unit_price=prod.price, total=prod.price*qty,
                    method=method,
                    sale_date=datetime.datetime.strptime(date_str, "%Y-%m-%d").date(),
                    created_by=admin.id)
        db.session.add(sale)

    db.session.commit()
    print("✅ Database seeded successfully!")
    print("   Admin:  admin@bizcrmapp.com / Admin@1234")
    print("   Staff:  staff@bizcrmapp.com / Staff@1234")


# ─────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_database()

    print("""
╔══════════════════════════════════════════════════════╗
║  🏪  BizCRM — Smart Local Business CRM              ║
║  Flask backend running on http://localhost:5000      ║
╠══════════════════════════════════════════════════════╣
║  API Endpoints:                                      ║
║    POST /api/auth/register                           ║
║    POST /api/auth/login                              ║
║    GET  /api/customers                               ║
║    GET  /api/products                                ║
║    POST /api/sales                                   ║
║    GET  /api/insights                                ║
║    POST /api/chat                                    ║
║    GET  /api/dashboard/stats                         ║
║    GET  /api/health                                  ║
╠══════════════════════════════════════════════════════╣
║  Credentials:                                        ║
║    admin@bizcrmapp.com / Admin@1234                  ║
║    staff@bizcrmapp.com / Staff@1234                  ║
╚══════════════════════════════════════════════════════╝
    """)

    app.run(debug=True, host="0.0.0.0", port=5000)
