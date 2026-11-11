-- ShopLite database schema + seed data.
-- Postgres runs every *.sql file in /docker-entrypoint-initdb.d/ exactly once,
-- the first time the data volume is empty. To re-run it: docker compose down -v

CREATE TABLE users (
    id            SERIAL      PRIMARY KEY,
    email         TEXT        NOT NULL UNIQUE,
    name          TEXT        NOT NULL,
    password_hash TEXT        NOT NULL,              -- pbkdf2_sha256$iterations$salt$hash
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Login sessions. We store a SHA-256 of the token, never the token itself.
CREATE TABLE sessions (
    token_hash TEXT        PRIMARY KEY,
    user_id    INTEGER     NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE products (
    id          SERIAL       PRIMARY KEY,
    sku         TEXT         NOT NULL UNIQUE,
    name        TEXT         NOT NULL,
    category    TEXT         NOT NULL,
    description TEXT         NOT NULL,
    price_cents INTEGER      NOT NULL CHECK (price_cents > 0),   -- money as integers, never floats
    stock       INTEGER      NOT NULL CHECK (stock >= 0),
    rating      NUMERIC(2,1) NOT NULL DEFAULT 4.0
);

CREATE TABLE cart_items (
    user_id    INTEGER     NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    product_id INTEGER     NOT NULL REFERENCES products (id),
    quantity   INTEGER     NOT NULL CHECK (quantity BETWEEN 1 AND 50),
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product_id)
);

CREATE TABLE coupons (
    code             TEXT        PRIMARY KEY,
    description      TEXT        NOT NULL,
    percent_off      INTEGER     CHECK (percent_off BETWEEN 1 AND 100),  -- percentage coupons
    amount_off_cents INTEGER     CHECK (amount_off_cents > 0),           -- fixed-amount coupons
    min_order_cents  INTEGER     NOT NULL DEFAULT 0,
    expires_at       TIMESTAMPTZ
);

CREATE TABLE orders (
    id               BIGSERIAL   PRIMARY KEY,
    user_id          INTEGER     NOT NULL REFERENCES users (id),
    status           TEXT        NOT NULL DEFAULT 'confirmed',
    subtotal_cents   INTEGER     NOT NULL,
    discount_cents   INTEGER     NOT NULL DEFAULT 0,
    shipping_cents   INTEGER     NOT NULL DEFAULT 0,
    total_cents      INTEGER     NOT NULL,
    coupon_code      TEXT,
    payment_method   TEXT        NOT NULL,
    shipping_name    TEXT        NOT NULL,
    shipping_address TEXT        NOT NULL,
    shipping_city    TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
    id               BIGSERIAL PRIMARY KEY,
    order_id         BIGINT    NOT NULL REFERENCES orders (id),
    product_id       INTEGER   NOT NULL REFERENCES products (id),
    quantity         INTEGER   NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER   NOT NULL
);

-- NOTE: there is deliberately NO index on orders(user_id) or order_items(order_id).
-- Postgres does not create indexes for foreign keys automatically.
-- (See docs/known-flaws.md and app/db/fix-indexes.sql.)

-- ---------------------------------------------------------------------------
-- Catalogue: 24 products in 6 categories -> product_stock_units has 24 series.
-- A few items have very low stock so "out of stock" happens naturally.
-- ---------------------------------------------------------------------------
INSERT INTO products (sku, name, category, description, price_cents, stock, rating) VALUES
 ('LAP-001', 'Aero 14 Ultrabook',          'laptops',     '14-inch display, 16 GB RAM, 512 GB SSD and an 18-hour battery.',        109900,  120, 4.6),
 ('LAP-002', 'Forge 16 Pro',               'laptops',     '16-inch creator laptop with RTX graphics and 32 GB RAM.',               219900,   40, 4.8),
 ('LAP-003', 'Swift 13 Air',               'laptops',     'Featherweight 1.1 kg laptop built for students.',                        74900,  200, 4.3),
 ('LAP-004', 'Titan 17 Gaming',            'laptops',     '17-inch 240 Hz gaming laptop with per-key RGB.',                        189900,    8, 4.7),
 ('PHN-001', 'Nova X5',                    'phones',      '6.5-inch OLED, triple camera system, 256 GB storage.',                   89900,  150, 4.5),
 ('PHN-002', 'Nova Lite',                  'phones',      'Two-day battery life at an everyday price.',                             29900,  400, 4.1),
 ('PHN-003', 'Pixelate Pro',               'phones',      'Flagship camera phone with 5x optical zoom.',                            99900,   90, 4.7),
 ('PHN-004', 'Fold Flex',                  'phones',      'Foldable phone with a 7.6-inch inner display.',                         179900,    6, 4.2),
 ('AUD-001', 'QuietPods Pro',              'audio',       'Wireless earbuds with active noise cancelling.',                         19900,  500, 4.6),
 ('AUD-002', 'Studio Over-Ear',            'audio',       'Over-ear headphones with a 40-hour battery.',                            29900,  250, 4.5),
 ('AUD-003', 'BoomBox Mini',               'audio',       'Waterproof portable speaker with deep bass.',                             6900,  600, 4.2),
 ('AUD-004', 'SoundBar 5.1',               'audio',       'Home theatre sound bar with a wireless subwoofer.',                      39900,   70, 4.4),
 ('ACC-001', 'USB-C Fast Charger 65W',     'accessories', 'Charges a laptop, phone and earbuds from one plug.',                      3900, 1500, 4.6),
 ('ACC-002', 'Braided USB-C Cable 2m',     'accessories', 'Tough braided cable rated for 10,000 bends.',                             1299, 2000, 4.4),
 ('ACC-003', 'Laptop Sleeve 14"',          'accessories', 'Water-resistant padded sleeve for 13-14 inch laptops.',                   2499,  800, 4.3),
 ('ACC-004', 'Power Bank 20,000 mAh',      'accessories', 'Charges a phone four times; USB-C in and out.',                           4999,  900, 4.5),
 ('GAM-001', 'Wireless Game Controller',   'gaming',      'Low-latency controller for PC and mobile.',                               5999,  500, 4.6),
 ('GAM-002', 'Mechanical Keyboard RGB',    'gaming',      'Hot-swappable switches and per-key lighting.',                            8999,  350, 4.7),
 ('GAM-003', 'Precision Gaming Mouse',     'gaming',      '26K DPI sensor, 58 g ultralight shell.',                                  4999,  450, 4.5),
 ('GAM-004', '27" 165 Hz Monitor',         'gaming',      'QHD IPS panel with 1 ms response time.',                                 32900,   60, 4.6),
 ('HOM-001', 'Smart Bulb (4-pack)',        'smart-home',  'Colour bulbs controlled from your phone or voice.',                       3999,  700, 4.2),
 ('HOM-002', 'Video Doorbell',             'smart-home',  '1080p doorbell camera with two-way talk.',                               12900,  180, 4.3),
 ('HOM-003', 'Smart Speaker Hub',          'smart-home',  'Voice assistant speaker that controls your smart home.',                  9900,  300, 4.4),
 ('HOM-004', 'Robot Vacuum',               'smart-home',  'Self-emptying robot vacuum with lidar mapping.',                         29900,    5, 4.1);

INSERT INTO coupons (code, description, percent_off, amount_off_cents, min_order_cents, expires_at) VALUES
 ('WELCOME10', '10% off your order',                  10,   NULL,     0, NULL),
 ('SAVE20',    '20% off orders over $150',            20,   NULL, 15000, NULL),
 ('FLAT15',    '$15 off orders over $75',           NULL,   1500,  7500, NULL),
 ('SUMMER25',  '25% off (summer sale, expired)',      25,   NULL,     0, now() - interval '30 days');

-- ---------------------------------------------------------------------------
-- Historical data: 500 old customers, 100,000 past orders, ~250,000 order lines.
-- Big enough that a missing index really hurts (sequential scans take real time).
-- Archive users cannot log in: their password hash '!' never matches.
-- ---------------------------------------------------------------------------
INSERT INTO users (email, name, password_hash, created_at)
SELECT 'customer' || g || '@archive.shoplite.test', 'Customer ' || g, '!', now() - interval '2 years'
FROM generate_series(1, 500) AS g;

INSERT INTO orders (user_id, status, subtotal_cents, total_cents, payment_method,
                    shipping_name, shipping_address, shipping_city, created_at)
SELECT 1 + (g % 500), 'delivered', 0, 0, (ARRAY['card', 'wallet', 'cash'])[1 + g % 3],
       'Customer ' || (1 + g % 500), g || ' Archive Road', (ARRAY['Dhaka', 'Chattogram', 'Sylhet', 'Khulna'])[1 + g % 4],
       now() - (g || ' minutes')::interval
FROM generate_series(1, 100000) AS g;

INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents)
SELECT o.id, 1 + ((o.id * 7 + k * 5) % 24), 1 + ((o.id + k) % 3), p.price_cents
FROM orders o
CROSS JOIN LATERAL generate_series(1, 1 + (o.id % 4)::int) AS k
JOIN products p ON p.id = 1 + ((o.id * 7 + k * 5) % 24);

UPDATE orders o
SET subtotal_cents = t.sum_cents, total_cents = t.sum_cents
FROM (SELECT order_id, sum(quantity * unit_price_cents) AS sum_cents FROM order_items GROUP BY order_id) t
WHERE t.order_id = o.id;

ANALYZE;
