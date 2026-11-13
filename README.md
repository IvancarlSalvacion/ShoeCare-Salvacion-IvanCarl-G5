# ShoeCare: Shoe Cleaning Service Management System

CSIT327-G5 Information Management 2, Project Development 1 (Account Feature).
Built with Django (templates) and PostgreSQL / Supabase.

## Features in this phase
- Registration with validation (required fields, email format, unique email, matching passwords, password strength) and hashed passwords
- Login / logout with error messages, `@login_required`-style protection
- Role-based dashboards: Customer, Staff, Administrator (wrong-role URLs redirect to your own dashboard)
- Profile view and edit (name, email, contact number, photo), always limited to the logged-in user

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env  -> then edit .env
python manage.py migrate
python manage.py createsuperuser   # creates an ADMIN account
python manage.py runserver
```
Open http://127.0.0.1:8000/

### Database
Put your Supabase connection string in `.env` as `DATABASE_URL` (and `DB_SSL_REQUIRE=True`),
or fill in the `DB_*` values for a local PostgreSQL database. Do not use SQLite.

### Creating staff accounts
Public sign-up always creates a Customer. Log in as an admin, open
`/django-admin/` > Users > Add user, and choose the role `STAFF` or `ADMIN`.

## Routes
| URL | Who |
|---|---|
| `/register/`, `/login/` | Everyone |
| `/dashboard/` | Redirects to your role's dashboard |
| `/dashboard/customer/` | Customers |
| `/dashboard/staff/` | Staff |
| `/dashboard/admin/` | Administrators |
| `/profile/`, `/profile/edit/` | Any logged-in user (own profile only) |

## Tests
`python manage.py test`
