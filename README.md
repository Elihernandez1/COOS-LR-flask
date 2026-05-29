# COOS-LR — Customizable Online Ordering System for Local Restaurants

A multi-tenant SaaS web application that enables technology freelancers to deploy fully branded digital ordering platforms for local, independent restaurants.

Built with Python, Flask, SQLAlchemy ORM, and Jinja2 templates. This is the Flask prototype — the production rewrite is in Node.js/Express.js/PostgreSQL.

## Live Demo
[Coming soon on Render.com]

## Demo Credentials
| Role | Email | Password |
|------|-------|----------|
| Admin | admin@coos-lr.com | demo123 |
| Luigi's Staff | staff@luigi.com | demo123 |
| Sakura Staff | staff@sakura.com | demo123 |
| Brew & Bean Staff | staff@brewbean.com | demo123 |

## Demo Restaurants
- Luigi's Pizzeria → /order/pizzeria-luigi
- Sakura Sushi → /order/sakura-sushi
- Brew & Bean Coffee → /order/brew-and-bean

## Tech Stack
| Layer | Technology |
|-------|------------|
| Backend | Python, Flask |
| ORM | SQLAlchemy |
| Database | SQLite (demo) |
| Templates | Jinja2 |
| Auth | bcrypt, Session-based RBAC |
| Deployment | Render.com |

## Features
- Multi-tenant architecture with fully isolated restaurant data
- Three user portals: Customer, Restaurant Staff, Admin
- Role-Based Access Control (RBAC)
- Order management with real-time status tracking
- Per-tenant branding (colors, logo)
- Restaurant and freelancer application workflows
- Admin dashboard with analytics

## Run Locally
`ash
pip install flask flask-sqlalchemy werkzeug gunicorn
python coos_lr_oopv.py
`
Then open http://localhost:5000
