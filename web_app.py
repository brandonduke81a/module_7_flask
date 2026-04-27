import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URI", "sqlite:///users.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email = db.Column(db.String(150))
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Deal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_name = db.Column(db.String(150), nullable=False)
    gross_potential_rent = db.Column(db.Float, nullable=False)
    vacancy_rate = db.Column(db.Float, nullable=False)
    operating_expenses = db.Column(db.Float, nullable=False)
    annual_debt_service = db.Column(db.Float, nullable=False)
    total_project_cost = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, nullable=False)

    def effective_gross_income(self):
        return self.gross_potential_rent * (1 - self.vacancy_rate)

    def noi(self):
        return self.effective_gross_income() - self.operating_expenses

    def dscr(self):
        if self.annual_debt_service == 0:
            return 0
        return self.noi() / self.annual_debt_service

    def yield_on_cost(self):
        if self.total_project_cost == 0:
            return 0
        return self.noi() / self.total_project_cost

    def to_dict(self):
        return {
            "id": self.id,
            "property_name": self.property_name,
            "gross_potential_rent": self.gross_potential_rent,
            "vacancy_rate": self.vacancy_rate,
            "operating_expenses": self.operating_expenses,
            "annual_debt_service": self.annual_debt_service,
            "total_project_cost": self.total_project_cost,
            "effective_gross_income": self.effective_gross_income(),
            "noi": self.noi(),
            "dscr": self.dscr(),
            "yield_on_cost": self.yield_on_cost(),
            "created_at": self.created_at.isoformat()
        }


with app.app_context():
    db.create_all()


def login_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)
    return wrapper


def admin_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session or not session.get("is_admin"):
            return "Unauthorized", 403
        return route_function(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    session.clear()
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return "Error: Username and password are required.", 400

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "Error: Username already exists.", 400

        new_user = User(
            username=username,
            first_name=request.form.get("first_name", "").strip(),
            last_name=request.form.get("last_name", "").strip(),
            email=request.form.get("email", "").strip()
        )

        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["is_admin"] = user.is_admin
            return redirect(url_for("dashboard"))

        return "Invalid credentials", 401

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username, is_admin=True).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["is_admin"] = True
            return redirect(url_for("admin_users"))

        return "Invalid admin credentials", 401

    return render_template("admin_login.html")


@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user and not user.is_admin:
        Deal.query.filter_by(user_id=user_id).delete()
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for("admin_users"))


@app.route("/make_admin/<int:user_id>")
def make_admin(user_id):
    user = db.session.get(User, user_id)
    if user:
        user.is_admin = True
        db.session.commit()
        return f"{user.username} is now an admin"
    return "User not found"


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        property_name = request.form.get("property_name", "").strip()
        gross_potential_rent = float(request.form.get("gross_potential_rent", 0))
        vacancy_rate = float(request.form.get("vacancy_rate", 0)) / 100
        operating_expenses = float(request.form.get("operating_expenses", 0))
        annual_debt_service = float(request.form.get("annual_debt_service", 0))
        total_project_cost = float(request.form.get("total_project_cost", 0))

        if not property_name:
            return "Error: Property name is required.", 400

        deal = Deal(
            property_name=property_name,
            gross_potential_rent=gross_potential_rent,
            vacancy_rate=vacancy_rate,
            operating_expenses=operating_expenses,
            annual_debt_service=annual_debt_service,
            total_project_cost=total_project_cost,
            user_id=session["user_id"]
        )

        db.session.add(deal)
        db.session.commit()
        return redirect(url_for("dashboard"))

    deals = Deal.query.filter_by(user_id=session["user_id"]).all()
    return render_template("dashboard.html", deals=deals)


@app.route("/delete_deal/<int:deal_id>")
@login_required
def delete_deal(deal_id):
    deal = Deal.query.filter_by(id=deal_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(deal)
    db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/api/v1/deals")
@login_required
def api_get_deals():
    deals = Deal.query.filter_by(user_id=session["user_id"]).all()
    return jsonify([deal.to_dict() for deal in deals])


@app.route("/api/v1/deals/<int:deal_id>")
@login_required
def api_get_deal(deal_id):
    deal = Deal.query.filter_by(id=deal_id, user_id=session["user_id"]).first_or_404()
    return jsonify(deal.to_dict())


if __name__ == "__main__":
    app.run(debug=False, port=5001)