import os
from functools import wraps
from flask import Flask, request, redirect, url_for, session, jsonify, render_template, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback-dev-secret-key")

# SQLAlchemy Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///coos_lr_orm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ════════════════════════════════════════════════════════════════════════════
# ORM MODEL CLASSES (SQLAlchemy)
# ════════════════════════════════════════════════════════════════════════════

class TenantBranding(db.Model):
    __tablename__ = 'tenant_branding'
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.tenant_id'), primary_key=True)
    primary_color = db.Column(db.String, default='#E8751A', nullable=False)
    secondary_color = db.Column(db.String, default='#0E9F8E', nullable=False)
    logo_text = db.Column(db.String, default='LP', nullable=False)

    def save(self, primary, secondary, logo_text):
        self.primary_color = primary
        self.secondary_color = secondary
        self.logo_text = logo_text
        db.session.commit()

class Tenant(db.Model):
    __tablename__ = 'tenants'
    tenant_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    subdomain = db.Column(db.String, unique=True, nullable=False)
    owner_name = db.Column(db.String, nullable=False)
    phone = db.Column(db.String)
    address = db.Column(db.String)
    is_active = db.Column(db.Integer, default=1, nullable=False)

    branding = db.relationship('TenantBranding', backref='tenant', uselist=False, cascade="all, delete-orphan")
    menu_items = db.relationship('MenuItem', backref='tenant', lazy=True)
    orders = db.relationship('Order', backref='tenant', lazy=True)

    @staticmethod
    def get_all(): return Tenant.query.order_by(Tenant.name).all()
    @staticmethod
    def get_active(): return Tenant.query.filter_by(is_active=1).all()
    @staticmethod
    def get_by_id(tid): return db.session.get(Tenant, tid)
    @staticmethod
    def get_by_subdomain(sub): return Tenant.query.filter_by(subdomain=sub, is_active=1).first()
    
    @staticmethod
    def create(name, subdomain, owner, phone, address):
        new_tenant = Tenant(name=name, subdomain=subdomain, owner_name=owner, phone=phone, address=address)
        db.session.add(new_tenant)
        db.session.flush() # Get the ID before committing
        new_branding = TenantBranding(tenant_id=new_tenant.tenant_id)
        db.session.add(new_branding)
        db.session.commit()
        return new_tenant.tenant_id

    def get_branding(self): return self.branding

    def get_menu(self, category="All", search=""):
        q = MenuItem.query.filter_by(tenant_id=self.tenant_id, is_available=1)
        if category != "All": q = q.filter_by(category=category)
        if search: q = q.filter(MenuItem.name.ilike(f"%{search}%"))
        return q.order_by(MenuItem.category, MenuItem.name).all()

    def get_all_menu_items(self):
        return MenuItem.query.filter_by(tenant_id=self.tenant_id).order_by(MenuItem.category, MenuItem.name).all()

    def get_categories(self):
        items = MenuItem.query.with_entities(MenuItem.category).filter_by(tenant_id=self.tenant_id, is_available=1).distinct().all()
        return [{"category": i[0]} for i in items]

    def get_active_orders(self):
        return Order.query.filter_by(tenant_id=self.tenant_id).filter(Order.status.notin_(['Completed','Cancelled'])).order_by(Order.created_at).all()

    def get_order_history(self, filter_by="all"):
        q = Order.query.filter_by(tenant_id=self.tenant_id).filter(Order.status.in_(['Completed','Cancelled']))
        return q.order_by(Order.created_at.desc()).all()

    def get_analytics(self):
        total = Order.query.filter_by(tenant_id=self.tenant_id).count()
        rev = db.session.query(db.func.sum(Order.total_amount)).filter_by(tenant_id=self.tenant_id, status='Completed').scalar() or 0
        top = db.session.query(OrderLineItem.item_name, db.func.sum(OrderLineItem.quantity).label('qty'), db.func.sum(OrderLineItem.subtotal).label('rev'))\
            .join(Order).filter(Order.tenant_id==self.tenant_id).group_by(OrderLineItem.item_name).order_by(db.desc('qty')).limit(6).all()
        sts = db.session.query(Order.status, db.func.count(Order.order_id).label('cnt')).filter_by(tenant_id=self.tenant_id).group_by(Order.status).all()
        return {"total": total, "revenue": float(rev), "top_items": [{"item_name":t[0],"qty":t[1],"rev":t[2]} for t in top], "statuses": [{"status":s[0],"cnt":s[1]} for s in sts]}

    def toggle_active(self):
        self.is_active = 0 if self.is_active else 1
        db.session.commit()

class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.tenant_id'), nullable=True)
    email = db.Column(db.String, unique=True, nullable=False)
    password = db.Column(db.String, nullable=False)
    full_name = db.Column(db.String, nullable=False)
    role = db.Column(db.String, nullable=False)
    
    tenant = db.relationship('Tenant')

    @staticmethod
    def authenticate(email, password):
        user = User.query.filter_by(email=email.strip().lower()).first()
        if user and check_password_hash(user.password, password):
            return user
        return None

    @staticmethod
    def get_all(): 
        users = User.query.order_by(User.user_id).all()
        for u in users: u.restaurant = u.tenant.name if u.tenant else "—"
        return users

    @staticmethod
    def get_by_email(email): return User.query.filter_by(email=email.strip().lower()).first()

    @staticmethod
    def create(tenant_id, email, password, full_name, role="staff"):
        new_user = User(tenant_id=tenant_id, email=email.strip().lower(), password=generate_password_hash(password), full_name=full_name, role=role)
        db.session.add(new_user)
        db.session.commit()
        return new_user

    def load_into_session(self):
        session["user_id"] = self.user_id; session["role"] = self.role; session["full_name"] = self.full_name; session["tenant_id"] = self.tenant_id

class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    item_id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.tenant_id'), nullable=False)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String, default="")
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String, default='General', nullable=False)
    badge = db.Column(db.String, default="")
    is_available = db.Column(db.Integer, default=1, nullable=False)

    @staticmethod
    def get_by_id(iid, tenant_id): return MenuItem.query.filter_by(item_id=iid, tenant_id=tenant_id).first()

    @staticmethod
    def create(tenant_id, name, description, price, category, badge=None):
        item = MenuItem(tenant_id=tenant_id, name=name, description=description, price=price, category=category, badge=badge or "")
        db.session.add(item)
        db.session.commit()
        return item

    def save(self, name, description, price, category, badge=None):
        self.name = name; self.description = description; self.price = price; self.category = category; self.badge = badge or ""
        db.session.commit()

    def toggle_availability(self):
        self.is_available = 0 if self.is_available else 1
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

class OrderLineItem(db.Model):
    __tablename__ = 'order_line_items'
    line_item_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('menu_items.item_id'), nullable=False)
    item_name = db.Column(db.String, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)

class Order(db.Model):
    __tablename__ = 'orders'
    STATUS_FLOW = {"Received": "In-Progress", "In-Progress": "Ready", "Ready": "Completed"}
    
    order_id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.tenant_id'), nullable=False)
    customer_name = db.Column(db.String, nullable=False)
    customer_phone = db.Column(db.String, nullable=False)
    delivery_address = db.Column(db.String, nullable=False)
    special_notes = db.Column(db.String, default="")
    payment_method = db.Column(db.String, default='Cash on Delivery', nullable=False)
    status = db.Column(db.String, default='Received', nullable=False)
    total_amount = db.Column(db.Float, default=0, nullable=False)
    cancelled_reason = db.Column(db.String, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    line_items = db.relationship('OrderLineItem', backref='order', lazy=True)

    @staticmethod
    def get_by_id(oid, tenant_id=None):
        q = Order.query.filter_by(order_id=oid)
        if tenant_id: q = q.filter_by(tenant_id=tenant_id)
        return q.first()

    @staticmethod
    def create(tenant_id, customer_name, phone, address, notes, payment, total):
        order = Order(tenant_id=tenant_id, customer_name=customer_name, customer_phone=phone, delivery_address=address, special_notes=notes, payment_method=payment, total_amount=round(total, 2))
        db.session.add(order)
        db.session.commit()
        return order.order_id

    def get_line_items(self): return self.line_items

    def add_line_item(self, item_id, item_name, unit_price, quantity):
        li = OrderLineItem(order_id=self.order_id, item_id=item_id, item_name=item_name, unit_price=unit_price, quantity=quantity, subtotal=round(unit_price * quantity, 2))
        db.session.add(li)
        db.session.commit()

    def advance_status(self):
        next_status = self.STATUS_FLOW.get(self.status)
        if next_status:
            self.status = next_status
            db.session.commit()
        return next_status

    def cancel(self, reason="Other"):
        self.status = "Cancelled"; self.cancelled_reason = reason
        db.session.commit()

    def next_status(self): return self.STATUS_FLOW.get(self.status)

# ════════════════════════════════════════════════════════════════════════════
# APPLICATION MODELS (Inheritance via Abstract Base)
# ════════════════════════════════════════════════════════════════════════════
class ApplicationBase(db.Model):
    __abstract__ = True
    email = db.Column(db.String, nullable=False)
    phone = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default='Pending', nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    def decline(self):
        self.status = 'Declined'
        db.session.commit()

class RestaurantApplication(ApplicationBase):
    __tablename__ = 'restaurant_applications'
    app_id = db.Column(db.Integer, primary_key=True)
    biz_name = db.Column(db.String, nullable=False)
    owner_name = db.Column(db.String, nullable=False)
    address = db.Column(db.String, nullable=False)
    subdomain_req = db.Column(db.String, nullable=False)
    description = db.Column(db.String, default="")

    @staticmethod
    def get_all(): return RestaurantApplication.query.order_by(RestaurantApplication.submitted_at.desc()).all()
    @staticmethod
    def get_by_id(aid): return db.session.get(RestaurantApplication, aid)
    @staticmethod
    def submit(biz_name, owner_name, email, phone, address, subdomain, description):
        app = RestaurantApplication(biz_name=biz_name, owner_name=owner_name, email=email.strip().lower(), phone=phone, address=address, subdomain_req=subdomain, description=description)
        db.session.add(app)
        db.session.commit()
    def approve(self):
        Tenant.create(self.biz_name, self.subdomain_req, self.owner_name, self.phone, self.address)
        self.status = 'Approved'
        db.session.commit()

class FreelancerApplication(ApplicationBase):
    __tablename__ = 'freelancer_applications'
    app_id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String, nullable=False)
    experience = db.Column(db.String, nullable=False)
    portfolio = db.Column(db.String, default="")

    @staticmethod
    def get_all(): return FreelancerApplication.query.order_by(FreelancerApplication.submitted_at.desc()).all()
    @staticmethod
    def get_by_id(aid): return db.session.get(FreelancerApplication, aid)
    @staticmethod
    def submit(full_name, email, phone, experience, portfolio):
        app = FreelancerApplication(full_name=full_name, email=email.strip().lower(), phone=phone, experience=experience, portfolio=portfolio)
        db.session.add(app)
        db.session.commit()
    def approve(self):
        User.create(None, self.email, "ChangeMe123!", self.full_name, role="admin")
        self.status = 'Approved'
        db.session.commit()

# ════════════════════════════════════════════════════════════════════════════
# HELPERS & CONTEXT PROCESSORS (Available globally in Jinja Templates)
# ════════════════════════════════════════════════════════════════════════════
def login_required(role=None):
    def dec(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                flash("Please log in.", "warning")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Access denied.", "danger")
                return redirect(url_for("index"))
            return f(*a, **kw)
        return wrapper
    return dec

@app.context_processor
def inject_globals():
    """These functions can be called directly inside any HTML template."""
    def badge(status):
        key = status.replace("-", "")
        return f'<span class="bdg bdg-{key}">{status}</span>'

    def render_stepper(status):
        steps = ["Received", "In-Progress", "Ready", "Completed"]
        cur   = steps.index(status) if status in steps else 0
        html  = ""
        for i, s in enumerate(steps):
            done   = cur > i; active = cur == i
            ic_cls = "done" if done else ("cur" if active else "")
            ic_lbl = "✓" if done else str(i + 1)
            det    = "Completed" if done else ("In progress…" if active else "Waiting")
            ln     = f'<div class="step-line {"done" if done else ""}"></div>' if i < len(steps) - 1 else ""
            html  += (f'<div class="step"><div class="step-ic-wrap">'
                      f'<div class="step-ic {ic_cls}">{ic_lbl}</div>{ln}</div>'
                      f'<div class="step-body"><div class="step-lbl {"on" if done or active else ""}">{s}</div>'
                      f'<div class="step-det">{det}</div></div></div>')
        return html
    return dict(badge=badge, render_stepper=render_stepper)


# ════════════════════════════════════════════════════════════════════════════
# ROUTES
# ════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    tenants = Tenant.get_active()
    return render_template("home.html", tenants=tenants)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = User.authenticate(request.form["email"], request.form["password"])
        if user:
            user.load_into_session()
            return redirect("/admin" if user.role == "admin" else "/staff" if user.role == "staff" else request.args.get("next", "/"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/signup", methods=["GET","POST"])
def customer_signup():
    if request.method == "POST":
        if User.get_by_email(request.form["email"]):
            flash("An account with that email already exists.", "warning")
            return redirect("/login")
        try:
            User.create(None, request.form["email"], request.form["password"], request.form["full_name"].strip(), role="customer")
            user = User.get_by_email(request.form["email"])
            user.load_into_session()
            flash(f'Welcome, {user.full_name}! Your account is ready.', "success")
            return redirect(request.args.get("next", "/"))
        except Exception:
            flash("Something went wrong. Please try again.", "danger")
    return render_template("signup.html")

@app.route("/apply/restaurant", methods=["GET","POST"])
def apply_restaurant():
    if request.method == "POST":
        RestaurantApplication.submit(
            request.form["biz_name"], request.form["owner_name"],
            request.form["email"].strip().lower(), request.form["phone"],
            request.form["address"], request.form["subdomain"].lower().strip().replace(" ","-"),
            request.form.get("description","")
        )
        flash("Application submitted! Our team will review it within 2 business days.", "success")
        return redirect(url_for("restaurant_thanks"))
    return render_template("apply_restaurant.html")

@app.route("/apply/restaurant/thanks")
def restaurant_thanks():
    return render_template("thanks.html", message="Our team will review your application and reach out within 2 business days with your login credentials and ordering page URL.")

@app.route("/apply/freelancer", methods=["GET","POST"])
def apply_freelancer():
    if request.method == "POST":
        FreelancerApplication.submit(
            request.form["full_name"], request.form["email"].strip().lower(),
            request.form["phone"], request.form["experience"], request.form.get("portfolio","")
        )
        flash("Application submitted! We will be in touch within 3 business days.", "success")
        return redirect(url_for("freelancer_thanks"))
    return render_template("apply_freelancer.html")

@app.route("/apply/freelancer/thanks")
def freelancer_thanks():
    return render_template("thanks.html", message="Our team will review your application and reach out within 3 business days to discuss next steps and provide portal access.")

@app.route("/order/<sub>")
def customer_menu(sub):
    tenant = Tenant.get_by_subdomain(sub)
    if not tenant: return "Restaurant not found or inactive.", 404
    cat = request.args.get("cat","All")
    q = request.args.get("q","").strip()
    items = tenant.get_menu(cat, q)
    cats = tenant.get_categories()
    br = tenant.get_branding()
    cart = session.get("cart", {})
    cnt = sum(v["qty"] for v in cart.values())
    
    MENU_EMOJI = {"pizzeria-luigi":"🍕","sakura-sushi":"🍤","brew-and-bean":"☕"}
    food_icon = MENU_EMOJI.get(sub, "🍽️")
    
    return render_template("customer_menu.html", tenant=tenant, items=items, cats=cats, br=br, cart=cart, cnt=cnt, cat=cat, q=q, food_icon=food_icon)

@app.route("/order/<sub>/add", methods=["POST"])
def add_to_cart(sub):
    iid = str(request.form["iid"])
    cart = session.get("cart", {})
    if iid in cart: cart[iid]["qty"] += 1
    else: cart[iid] = {"name": request.form["name"], "price": float(request.form["price"]), "qty": 1}
    session["cart"] = cart
    flash(f'"{request.form["name"]}" added to cart.', "success")
    return redirect(f"/order/{sub}?cat={request.form.get('cat','All')}")

@app.route("/order/<sub>/cart")
def view_cart(sub):
    tenant = Tenant.get_by_subdomain(sub)
    br = tenant.get_branding()
    cart = session.get("cart", {})
    total = sum(v["price"] * v["qty"] for v in cart.values())
    return render_template("cart.html", tenant=tenant, br=br, cart=cart, total=total)

@app.route("/order/<sub>/cart/update", methods=["POST"])
def update_cart(sub):
    iid = str(request.form["iid"])
    qty = int(request.form.get("qty", 1))
    cart = session.get("cart", {})
    if iid in cart:
        if qty <= 0: del cart[iid]
        else: cart[iid]["qty"] = qty
    session["cart"] = cart
    return redirect(f"/order/{sub}/cart")

@app.route("/order/<sub>/cart/remove/<iid>")
def remove_from_cart(sub, iid):
    cart = session.get("cart", {})
    cart.pop(iid, None)
    session["cart"] = cart
    return redirect(f"/order/{sub}/cart")

@app.route("/order/<sub>/checkout", methods=["GET","POST"])
def checkout(sub):
    tenant = Tenant.get_by_subdomain(sub)
    cart = session.get("cart", {})
    total = sum(v["price"] * v["qty"] for v in cart.values())

    if request.method == "POST":
        if not cart: 
            flash("Cart is empty.", "warning")
            return redirect(f"/order/{sub}")
        oid = Order.create(
            tenant.tenant_id, request.form["name"], request.form["phone"],
            request.form["address"], request.form.get("notes",""),
            request.form["payment"], total
        )
        order = Order.get_by_id(oid)
        for iid, v in cart.items():
            order.add_line_item(int(iid), v["name"], v["price"], v["qty"])
        session.pop("cart", None)
        return redirect(f"/order/{sub}/confirmation/{oid}")

    return render_template("checkout.html", tenant=tenant, cart=cart, total=total)

@app.route("/order/<sub>/confirmation/<int:oid>")
def order_confirmation(sub, oid):
    tenant = Tenant.get_by_subdomain(sub)
    order = Order.get_by_id(oid, tenant.tenant_id)
    items = order.get_line_items()
    return render_template("order_confirmation.html", tenant=tenant, order=order, items=items)

@app.route("/order/<sub>/track/<int:oid>")
def order_status(sub, oid):
    tenant = Tenant.get_by_subdomain(sub)
    order = Order.get_by_id(oid, tenant.tenant_id)
    return render_template("track_order.html", tenant=tenant, order=order)

@app.route("/api/order/<int:oid>")
def api_order(oid):
    order = Order.get_by_id(oid)
    return jsonify({"status": order.status}) if order else (jsonify({"error": "not found"}), 404)

# ════════════════════════════════════════════════════════════════════════════
# ROUTES — STAFF PORTAL
# ════════════════════════════════════════════════════════════════════════════
@app.route("/staff")
@login_required(role="staff")
def staff_dashboard():
    tenant = Tenant.get_by_id(session["tenant_id"])
    orders = tenant.get_active_orders()
    counts = {s: sum(1 for o in orders if o.status == s) for s in ["Received","In-Progress","Ready"]}
    return render_template("staff_dashboard.html", tenant=tenant, orders=orders, counts=counts)

@app.route("/staff/order/<int:oid>")
@login_required(role="staff")
def staff_order_detail(oid):
    tenant = Tenant.get_by_id(session["tenant_id"])
    order = Order.get_by_id(oid, tenant.tenant_id)
    items = order.get_line_items()
    return render_template("staff_order_detail.html", tenant=tenant, order=order, items=items)

@app.route("/staff/order/<int:oid>/advance", methods=["POST"])
@login_required(role="staff")
def advance_order(oid):
    order = Order.get_by_id(oid, session["tenant_id"])
    new_status = order.advance_status()
    if new_status: flash(f"Order #{oid} → {new_status}", "success")
    return redirect("/staff")

@app.route("/staff/order/<int:oid>/cancel", methods=["POST"])
@login_required(role="staff")
def cancel_order(oid):
    order = Order.get_by_id(oid, session["tenant_id"])
    order.cancel(request.form.get("reason","Other"))
    flash(f"Order #{oid} cancelled.", "warning")
    return redirect("/staff")

@app.route("/staff/history")
@login_required(role="staff")
def order_history():
    tenant = Tenant.get_by_id(session["tenant_id"])
    f = request.args.get("f","all")
    orders = tenant.get_order_history(f)
    return render_template("staff_history.html", tenant=tenant, orders=orders, filter=f)

@app.route("/staff/menu")
@login_required(role="staff")
def staff_menu():
    tenant = Tenant.get_by_id(session["tenant_id"])
    items = tenant.get_all_menu_items()
    return render_template("staff_menu.html", tenant=tenant, items=items)

@app.route("/staff/menu/add", methods=["GET","POST"])
@login_required(role="staff")
def add_item():
    tenant = Tenant.get_by_id(session["tenant_id"])
    if request.method == "POST":
        MenuItem.create(
            tenant.tenant_id, request.form["name"], request.form.get("desc",""),
            float(request.form["price"]), request.form["cat"], request.form.get("badge") or None
        )
        flash(f'"{request.form["name"]}" added.', "success")
        return redirect("/staff/menu")
    return render_template("staff_menu_form.html", tenant=tenant, item=None)

@app.route("/staff/menu/edit/<int:iid>", methods=["GET","POST"])
@login_required(role="staff")
def edit_item(iid):
    tenant = Tenant.get_by_id(session["tenant_id"])
    item = MenuItem.get_by_id(iid, tenant.tenant_id)
    if request.method == "POST":
        item.save(
            request.form["name"], request.form.get("desc",""),
            float(request.form["price"]), request.form["cat"], request.form.get("badge") or None
        )
        flash("Item updated.", "success")
        return redirect("/staff/menu")
    return render_template("staff_menu_form.html", tenant=tenant, item=item)

@app.route("/staff/menu/toggle/<int:iid>", methods=["POST"])
@login_required(role="staff")
def toggle_item(iid):
    item = MenuItem.get_by_id(iid, session["tenant_id"])
    item.toggle_availability()
    flash(f'"{item.name}" marked {"Sold Out" if not item.is_available else "Available"}.', "success")
    return redirect("/staff/menu")

@app.route("/staff/menu/delete/<int:iid>", methods=["POST"])
@login_required(role="staff")
def delete_item(iid):
    item = MenuItem.get_by_id(iid, session["tenant_id"])
    name = item.name
    item.delete()
    flash(f'"{name}" deleted.', "warning")
    return redirect("/staff/menu")

@app.route("/staff/analytics")
@login_required(role="staff")
def staff_analytics():
    tenant = Tenant.get_by_id(session["tenant_id"])
    data = tenant.get_analytics()
    avg = data["revenue"] / data["total"] if data["total"] else 0
    return render_template("staff_analytics.html", tenant=tenant, data=data, avg=avg)

# ════════════════════════════════════════════════════════════════════════════
# ROUTES — ADMIN PORTAL
# ════════════════════════════════════════════════════════════════════════════
@app.route("/admin")
@login_required(role="admin")
def admin_dashboard():
    tenants = Tenant.get_all()
    
    # New SQLAlchemy ORM queries (No raw SQL!)
    tot_ord = Order.query.count()
    tot_rev = db.session.query(db.func.sum(Order.total_amount)).filter_by(status='Completed').scalar() or 0
    tot_usr = User.query.filter_by(role='staff').count()
    
    return render_template("admin_dashboard.html", tenants=tenants, tot_ord=tot_ord, tot_rev=tot_rev, tot_usr=tot_usr)

@app.route("/admin/onboard", methods=["GET","POST"])
@login_required(role="admin")
def onboard():
    if request.method == "POST":
        try:
            Tenant.create(
                request.form["name"], request.form["subdomain"].lower().strip(),
                request.form["owner"], request.form.get("phone",""), request.form.get("address","")
            )
            flash(f'Restaurant "{request.form["name"]}" onboarded!', "success")
        except Exception:
            flash("Subdomain already taken.", "danger")
        return redirect("/admin")
    return render_template("admin_onboard.html")

@app.route("/admin/branding/<int:tid>", methods=["GET","POST"])
@login_required(role="admin")
def admin_branding(tid):
    tenant = Tenant.get_by_id(tid)
    br = tenant.get_branding()
    if request.method == "POST":
        br.save(request.form["pc"], request.form["sc"], request.form["lt"])
        flash(f'Branding for "{tenant.name}" updated.', "success")
        return redirect("/admin")
    return render_template("admin_branding.html", tenant=tenant, br=br)

@app.route("/admin/tenant/<int:tid>/toggle", methods=["POST"])
@login_required(role="admin")
def toggle_tenant(tid):
    tenant = Tenant.get_by_id(tid)
    was_active = tenant.is_active
    tenant.toggle_active()
    flash(f'"{tenant.name}" {"deactivated" if was_active else "activated"}.', "success")
    return redirect("/admin")

@app.route("/admin/users", methods=["GET","POST"])
@login_required(role="admin")
def user_management():
    users = User.get_all()
    tenants = Tenant.get_active()
    if request.method == "POST":
        try:
            User.create(int(request.form["tid"]), request.form["email"], request.form["password"], request.form["full_name"])
            flash("Staff account created.", "success")
        except Exception:
            flash("Email already in use.", "danger")
        return redirect("/admin/users")
    return render_template("admin_users.html", users=users, tenants=tenants)

@app.route("/admin/analytics")
@login_required(role="admin")
def admin_analytics():
    tenants = Tenant.get_all()
    per = [{"name":t.name, "sub":t.subdomain, "orders":t.get_analytics()["total"], "rev":t.get_analytics()["revenue"], "active":t.is_active} for t in tenants]
    tot_o = sum(r["orders"] for r in per)
    tot_r = sum(r["rev"] for r in per)
    return render_template("admin_analytics.html", per=per, tot_o=tot_o, tot_r=tot_r)

@app.route("/admin/applications/restaurant")
@login_required(role="admin")
def review_restaurant_apps():
    apps = RestaurantApplication.get_all()
    return render_template("admin_apps_restaurant.html", apps=apps)

@app.route("/admin/applications/restaurant/<int:aid>/approve", methods=["POST"])
@login_required(role="admin")
def approve_restaurant_app(aid):
    app_obj = RestaurantApplication.get_by_id(aid)
    if app_obj and app_obj.status == "Pending":
        try:
            app_obj.approve()
            flash(f'"{app_obj.biz_name}" approved and onboarded!', "success")
        except Exception:
            flash("Subdomain already taken.", "danger")
    return redirect("/admin/applications/restaurant")

@app.route("/admin/applications/restaurant/<int:aid>/decline", methods=["POST"])
@login_required(role="admin")
def decline_restaurant_app(aid):
    app_obj = RestaurantApplication.get_by_id(aid)
    if app_obj:
        app_obj.decline()
        flash("Application declined.", "warning")
    return redirect("/admin/applications/restaurant")

@app.route("/admin/applications/freelancer")
@login_required(role="admin")
def review_freelancer_apps():
    apps = FreelancerApplication.get_all()
    return render_template("admin_apps_freelancer.html", apps=apps)

@app.route("/admin/applications/freelancer/<int:aid>/approve", methods=["POST"])
@login_required(role="admin")
def approve_freelancer_app(aid):
    app_obj = FreelancerApplication.get_by_id(aid)
    if app_obj and app_obj.status == "Pending":
        try:
            app_obj.approve()
            flash(f'"{app_obj.full_name}" approved! Temp password: ChangeMe123!', "success")
        except Exception:
            flash("An admin account with that email already exists.", "danger")
    return redirect("/admin/applications/freelancer")

@app.route("/admin/applications/freelancer/<int:aid>/decline", methods=["POST"])
@login_required(role="admin")
def decline_freelancer_app(aid):
    app_obj = FreelancerApplication.get_by_id(aid)
    if app_obj:
        app_obj.decline()
        flash("Application declined.", "warning")
    return redirect("/admin/applications/freelancer")

# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════
def seed_database():
    """Populates the ORM database with demo data."""
    if Tenant.query.first(): return # Already seeded
    
    pw = generate_password_hash("demo123")

    t1 = Tenant(name="Luigi's Pizzeria", subdomain="pizzeria-luigi", owner_name="Luigi Hernandez", phone="(212) 555-0149", address="88 Broadway Ave, NY")
    t2 = Tenant(name="Sakura Sushi", subdomain="sakura-sushi", owner_name="Hana Tanaka", phone="(212) 555-0220", address="45 Park Ave, NY")
    t3 = Tenant(name="Brew & Bean Coffee", subdomain="brew-and-bean", owner_name="Sofia Martinez", phone="(212) 555-0391", address="12 Lexington Ave, NY")
    db.session.add_all([t1, t2, t3])
    db.session.commit() # Commit to generate IDs

    db.session.add_all([
        TenantBranding(tenant_id=t1.tenant_id, primary_color='#E8751A', secondary_color='#0E9F8E', logo_text='LP'),
        TenantBranding(tenant_id=t2.tenant_id, primary_color='#C0392B', secondary_color='#2C3E50', logo_text='SS'),
        TenantBranding(tenant_id=t3.tenant_id, primary_color='#6F4E37', secondary_color='#D4A017', logo_text='BB')
    ])

    db.session.add_all([
        User(tenant_id=t1.tenant_id, email="staff@luigi.com", password=pw, full_name="Marco Romano", role="staff"),
        User(tenant_id=t2.tenant_id, email="staff@sakura.com", password=pw, full_name="Kenji Tanaka", role="staff"),
        User(tenant_id=t3.tenant_id, email="staff@brewbean.com", password=pw, full_name="Sofia Martinez", role="staff"),
        User(tenant_id=None, email="admin@coos-lr.com", password=pw, full_name="Elihut Hernandez", role="admin")
    ])

    # 🍕 Luigi's Menu
    luigi_items = [
        MenuItem(tenant_id=t1.tenant_id, name="Margherita", description="Classic tomato & fresh mozzarella", price=12.99, category="Pizza", badge="POPULAR"),
        MenuItem(tenant_id=t1.tenant_id, name="Pepperoni", description="Loaded with premium pepperoni", price=14.99, category="Pizza", badge=""),
        MenuItem(tenant_id=t1.tenant_id, name="BBQ Chicken", description="Smoky BBQ with grilled chicken", price=15.99, category="Pizza", badge="NEW"),
        MenuItem(tenant_id=t1.tenant_id, name="Veggie Supreme", description="Garden-fresh seasonal toppings", price=13.99, category="Pizza", badge=""),
        MenuItem(tenant_id=t1.tenant_id, name="Four Cheese", description="Mozzarella, cheddar, parmesan, gouda", price=13.49, category="Pizza", badge="CHEF"),
        MenuItem(tenant_id=t1.tenant_id, name="Caesar Salad", description="Romaine, croutons, parmesan", price=8.99, category="Salads", badge=""),
        MenuItem(tenant_id=t1.tenant_id, name="Garlic Bread", description="Toasted with herb butter", price=4.99, category="Appetizers", badge=""),
        MenuItem(tenant_id=t1.tenant_id, name="Tiramisu", description="Classic Italian dessert", price=6.99, category="Desserts", badge=""),
        MenuItem(tenant_id=t1.tenant_id, name="Sparkling Water", description="San Pellegrino 500ml", price=3.49, category="Drinks", badge="")
    ]
    
    # 🍣 Sakura Menu
    sakura_items = [
        MenuItem(tenant_id=t2.tenant_id, name="Salmon Nigiri", description="Fresh Atlantic salmon", price=12.99, category="Nigiri", badge="POPULAR"),
        MenuItem(tenant_id=t2.tenant_id, name="Dragon Roll", description="Shrimp tempura & avocado", price=15.99, category="Rolls", badge="CHEF"),
        MenuItem(tenant_id=t2.tenant_id, name="Miso Soup", description="Traditional dashi broth", price=4.99, category="Soups", badge=""),
        MenuItem(tenant_id=t2.tenant_id, name="Edamame", description="Salted steamed soybeans", price=5.99, category="Appetizers", badge="")
    ]

    # ☕ Brew & Bean Menu
    brew_items = [
        MenuItem(tenant_id=t3.tenant_id, name="Espresso", description="Double shot, rich & bold", price=3.49, category="Espresso", badge="POPULAR"),
        MenuItem(tenant_id=t3.tenant_id, name="Cappuccino", description="Espresso, steamed milk & foam", price=4.99, category="Espresso", badge=""),
        MenuItem(tenant_id=t3.tenant_id, name="Caramel Latte", description="Espresso, milk & house caramel syrup", price=5.49, category="Espresso", badge="NEW"),
        MenuItem(tenant_id=t3.tenant_id, name="Cold Brew", description="Slow-steeped 12-hour cold brew", price=4.49, category="Cold Drinks", badge=""),
        MenuItem(tenant_id=t3.tenant_id, name="Iced Matcha Latte", description="Ceremonial matcha, oat milk", price=5.49, category="Cold Drinks", badge="CHEF"),
        MenuItem(tenant_id=t3.tenant_id, name="Drip Coffee", description="House blend, freshly brewed", price=2.99, category="Hot Drinks", badge=""),
        MenuItem(tenant_id=t3.tenant_id, name="Chai Latte", description="Spiced chai with steamed milk", price=4.99, category="Hot Drinks", badge=""),
        MenuItem(tenant_id=t3.tenant_id, name="Croissant", description="Buttery, flaky, baked fresh daily", price=3.99, category="Pastries", badge="POPULAR"),
        MenuItem(tenant_id=t3.tenant_id, name="Blueberry Muffin", description="Bursting with fresh blueberries", price=3.49, category="Pastries", badge=""),
        MenuItem(tenant_id=t3.tenant_id, name="Avocado Toast", description="Sourdough, smashed avocado, chili flakes", price=8.99, category="Food", badge="NEW"),
        MenuItem(tenant_id=t3.tenant_id, name="Granola Bowl", description="Greek yogurt, honey, seasonal fruit", price=7.99, category="Food", badge="")
    ]

    db.session.add_all(luigi_items + sakura_items + brew_items)
    db.session.commit()
    
    # Add a couple of demo orders to Luigi's
    o1 = Order(tenant_id=t1.tenant_id, customer_name='Maria Rodriguez', customer_phone='(212)555-9101', delivery_address='22 5th Ave, NY', special_notes='Extra cheese', status='Received', total_amount=34.97)
    o2 = Order(tenant_id=t1.tenant_id, customer_name='James Thornton', customer_phone='(212)555-0182', delivery_address='88 Park Blvd, NY', special_notes='Nut allergy', status='In-Progress', total_amount=21.98)
    db.session.add_all([o1, o2])
    db.session.commit()

    db.session.add_all([
        OrderLineItem(order_id=o1.order_id, item_id=luigi_items[1].item_id, item_name='Pepperoni', unit_price=14.99, quantity=2, subtotal=29.98),
        OrderLineItem(order_id=o1.order_id, item_id=luigi_items[6].item_id, item_name='Garlic Bread', unit_price=4.99, quantity=1, subtotal=4.99),
        OrderLineItem(order_id=o2.order_id, item_id=luigi_items[0].item_id, item_name='Margherita', unit_price=12.99, quantity=1, subtotal=12.99),
        OrderLineItem(order_id=o2.order_id, item_id=luigi_items[5].item_id, item_name='Caesar Salad', unit_price=8.99, quantity=1, subtotal=8.99)
    ])
    db.session.commit()

with app.app_context():
    db.create_all()
    seed_database()

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)