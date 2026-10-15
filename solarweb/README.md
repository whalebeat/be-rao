# SolarWeb (Flask)

A Flask rewrite of the WordPress + WooCommerce SolarWeb site in `E:/HMH/SolarWeb`. It is a solar-equipment catalogue with:
- products by category and brand, with spec tables and datasheets
- a **cart that sends an order request, with no online payment**
- projects, news and static pages
- the solar calculator, with leads
- an admin area for staff

**Stack:** Flask 3.1, SQLAlchemy 2, PostgreSQL in production (SQLite locally), Bootstrap 5, Pillow and nh3. Uploaded images and PDFs are stored in the database, because Render's free tier has no persistent disk.

## How it runs today: inside be-rao at `/solar`

SolarWeb is the `solarweb/` package of the be-rao repo. be-rao's `wsgi.py` uses Werkzeug's `DispatcherMiddleware` to send `/solar/*` here and everything else to be-rao. Both apps run in one Render service and share one Postgres database:
- **Database:** every SolarWeb table is prefixed `sw_`, so nothing clashes with be-rao's tables, including the two `user` tables.
- **Logins:** SolarWeb uses its own cookie (`sw_session`, `Path=/solar`) and its own secret key, so the two logins never mix. Logging into one app doesn't log you into the other.
- **Settings:** SolarWeb reads `SOLARWEB_<NAME>` first, then `<NAME>`. In the shared environment, set the `SOLARWEB_` variables listed in be-rao's `.env.example`.
  - `DATABASE_URL` is deliberately shared.
  - If `SOLARWEB_SECRET_KEY` is missing, a secret is derived from `SECRET_KEY`, so it's never the same as be-rao's.
- **Search engines:** `SOLARWEB_NOINDEX=1` adds `noindex` while the site is being tested at `/solar`.

## Run locally

Run these from the be-rao repo root:

```bash
venv/Scripts/pip install -r requirements-dev.txt     # macOS/Linux: venv/bin/pip
venv/Scripts/python -m solarweb.seed                 # demo products, pages and a sample project
venv/Scripts/python wsgi.py                          # be-rao at /, SolarWeb at /solar
```

- Site: http://127.0.0.1:5000/solar/
- Admin: http://127.0.0.1:5000/solar/admin/dang-nhap
  - The username is `SOLARWEB_ADMIN_USERNAME` (default `admin`) and the password is `SOLARWEB_ADMIN_PASSWORD`.
  - If the password is blank, one is generated and printed the first time the app starts, and you must change it on first login.
  - This account is separate from be-rao's `admin`.
- Tests: `venv/Scripts/python -m pytest` runs both apps' tests plus `tests/test_dispatch.py`, which checks that the two apps work side by side.

You can re-run `python -m solarweb.seed` at any time. It updates products by SKU and only creates pages and projects that are missing. Without `DATABASE_URL`, local data goes to `instance/solarweb.db`, separate from be-rao's SQLite file.

## What's where

| Path | Purpose |
|---|---|
| `__init__.py` | `create_app()`: config (`env()` reads `SOLARWEB_<NAME>`), blueprints, template helpers |
| `wsgi.py` | Standalone entry point (`gunicorn solarweb.wsgi:app`), for its own domain later |
| `models.py` | Database models; `init_db()` creates the tables and the first admin |
| `blueprints/public.py` | Home, catalogue, product pages, projects, news, pages, contact form, calculator, lead API, `/media`, sitemap and robots |
| `blueprints/cart.py` | Session cart and order-request checkout |
| `blueprints/admin.py` | `/admin`: products, categories, brands, CSV, orders, leads, messages, content, settings, users |
| `security.py` | CSRF, login throttling, roles, rate limits, security headers, Cloudflare Turnstile |
| `settings.py` | Site settings and calculator defaults, labels and provinces (ported from `solarweb-calculator.php`) |
| `csv_io.py` | Product CSV import and export in WooCommerce's format |
| `storage.py` | Image and PDF uploads stored in the database; images are re-encoded and scaled to at most 1600 px |
| `static/calculator.js`, `static/calculator.css` | Byte-for-byte copies from the WordPress plugin |
| `seed/products.csv` | Demo catalogue, and the CSV template for staff |

## How the WordPress features map

- **"Liên hệ" price:** leave the price empty. The product shows "Liên hệ" but can still be added to the cart, and the order notes that some items need a quote.
- **Order request:**
  - The checkout asks for Name, Phone, Address and City, plus an optional Email and a note. Payment is COD only and there's no shipping calculation.
  - The button reads "Gửi yêu cầu đặt hàng".
  - Orders appear in **Admin → Đơn hàng**, and the admin is emailed when SMTP is set up.
- **Specs and datasheet:** the "Thông số kỹ thuật" tab is built from the product's spec rows. A datasheet is either an uploaded PDF or a URL.
- **Calculator:**
  - `/tinh-dien-mat-troi/` uses the same JS and the same defaults, so it gives the same results as WordPress.
  - Prices and assumptions are under **Admin → Tính điện mặt trời**.
  - Leads, with the consent wording and time, appear under **Yêu cầu tư vấn**.
- **Contact form:** replaces Contact Form 7. Messages go to **Admin → Tin nhắn liên hệ**.
- **Floating Zalo / hotline buttons:** the numbers are set in **Admin → Cài đặt chung**.
- **Security** (`solarweb-hardening.php`):
  - Security headers (nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, and HSTS on HTTPS).
  - CSRF protection on every form, and a generic login error.
  - Login throttling (5 attempts per 15 minutes).
  - Each IP can send at most 5 orders, leads or contact messages per hour, and forms have a honeypot field.
  - Turnstile protects checkout, the contact form and leads once keys are set. It fails closed: if Cloudflare can't be reached, the submission is refused.
  - Set `SOLARWEB_BEHIND_CLOUDFLARE=1` only when the site is behind Cloudflare. The rate limits then use the visitor's real IP from `CF-Connecting-IP`.
- **SEO** (instead of Rank Math):
  - Every page has a title, meta description, canonical link and Open Graph tags.
  - Product pages include `Product` JSON-LD.
  - `/sitemap.xml` and `/robots.txt` are generated.
  - SEO title and description fields are on products and posts.

## Maintaining products (for staff)

- **Add or edit one product:** Admin → Sản phẩm → Thêm sản phẩm. Fill in:
  - the name, SKU and price (leave the price empty for "Liên hệ")
  - categories and brands
  - spec rows
  - images
  - a datasheet PDF or link
- **Bulk add or update:**
  1. Admin → Nhập / Xuất CSV → **Tải tệp CSV** to download.
  2. Edit the file in Excel and save it as **CSV UTF-8**.
  3. Import it with "Cập nhật sản phẩm có sẵn" ticked, so products are updated by SKU.
- **Hide a product:** untick "Hiện trên website".
- **Delete a product:** use the delete button on the product page. Old orders keep the product's name and price.

## Deploy

### Now: at teso.vn/solar, in the be-rao service
be-rao's `render.yaml` already lists the variables. If the Render service was created by hand rather than from the Blueprint, set these in the dashboard:
1. Start Command: `gunicorn wsgi:app`
2. Environment:
   - `SOLARWEB_SECRET_KEY`: a random value
   - `SOLARWEB_ADMIN_PASSWORD`: a strong one
   - `SOLARWEB_SITE_URL`: `https://teso.vn/solar`
   - `SOLARWEB_NOINDEX`: `1`
   - optionally `SOLARWEB_ADMIN_EMAIL`, `SOLARWEB_SMTP_*` and `SOLARWEB_TURNSTILE_*`
3. Deploy, then log in at `https://teso.vn/solar/admin/dang-nhap`. To load the demo data, open the Render Shell and run `python -m solarweb.seed`.
4. Set the hotline, Zalo number and address in Admin → Cài đặt chung. Rewrite the **Chính sách bảo mật** page (Admin → Trang) before launch.

### Later: on its own domain
1. On Render, create a new web service from the same repo:
   - Start Command: `gunicorn solarweb.wsgi:app`
   - its own Postgres database
   - the variables without the `SOLARWEB_` prefix, or with it; both work
2. Copy the data from the shared database. Only SolarWeb's tables are dumped:
   ```bash
   pg_dump --no-owner --table='sw_*' "$OLD_DATABASE_URL" | psql "$NEW_DATABASE_URL"
   ```
3. Set `SITE_URL` to the new domain, e.g. `https://solarweb.vn`, and remove `NOINDEX`.
4. Add the domain under the new service's Custom Domains.
5. In be-rao's `wsgi.py`, replace the `/solar` mount with a redirect to the new domain, or remove it. Then drop the `sw_*` tables from be-rao's database once you've checked the copy.

### Free-tier limits: read before launch
- **The free web service sleeps after 15 minutes idle.** The first visitor then waits about a minute. Upgrade to a paid instance before real traffic arrives.
- **The free Postgres database expires 30 days after it's created and is limited to 1 GB.** Upgrade it before launch, or the data will be lost. Uploaded images count toward the limit (each is re-encoded to roughly 100–300 KB).
- **Free instances may block outgoing SMTP ports.** If order and lead emails don't arrive, use a paid instance or an email provider with an HTTP API. Everything is saved in the admin either way.
- **be-rao and SolarWeb share one service.** A deploy or crash affects both, and both wake up together after the service sleeps.
- **Rate limits are kept in memory.** They reset when the service restarts and are counted separately by each gunicorn worker.
