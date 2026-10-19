# Gear Library

Share gear through inventories. You own your items. An inventory is a group of people who
share gear: only its members see it and the items listed in it. You can create or join any
number of inventories, and you have one role in each:

- `member`: sees and borrows the inventory's items.
- `admin`: also lists and removes their own items, approves and declines borrow requests
  made through the inventory, and marks those items returned.
- `owner`: also manages the inventory, its members and its invites.

The full rights of each role are in [`docs/schema.md`](docs/schema.md).

Runs locally with Docker Compose: PostgreSQL, a Django REST Framework backend and a Vite +
React frontend. The database design is in [`docs/schema.md`](docs/schema.md) and the API
draft is in [`docs/api.md`](docs/api.md).

## Setup

```sh
cp .env.example .env    # then set a real password and secret key, and your UID and GID
docker compose up --build
```

Open <http://localhost:5173>, then create an account or log in as a demo user (see
[Demo data](#demo-data)). The home page checks once on load whether the backend and
database are up. On a first start the backend may still be migrating, so reload the page
to check again.

`docker compose up` starts three services:

- `db`: PostgreSQL. Data is kept in the `db-data` volume.
- `backend`: Django on port 8000 inside the Compose network. It waits for the database,
  applies migrations, then runs the development server.
- `frontend`: the Vite dev server, published on `127.0.0.1:5173` only. It forwards
  `/api`, `/admin` and `/static` to the backend, so the browser sees one origin.

Only the frontend port is published to the host. `backend/` and `frontend/` are mounted
into their containers, so code changes reload without a rebuild. The containers run as
the `UID` and `GID` in `.env`, so files they write are yours. The frontend image bakes
them in at build time: after changing them, run
`docker compose up --build --renew-anon-volumes`.

## Common commands

```sh
docker compose run --rm backend pytest                        # backend tests
docker compose run --rm frontend npm test                     # frontend tests
docker compose run --rm backend python manage.py makemigrations
docker compose run --rm backend python manage.py createsuperuser
docker compose run --rm backend python manage.py seed_demo    # demo users, see below
docker compose run --rm frontend npm install --save-exact <package>
docker compose down                                           # stop; data stays in the volume
docker compose down -v                                        # stop and delete the data
docker volume prune                                           # delete unused anonymous volumes
```

The frontend's `node_modules` is an anonymous volume. `docker compose run --rm` removes it
with the container, but `docker compose down` followed by `up`, and `up --renew-anon-volumes`,
leave the old one behind. `docker volume prune` deletes the unused anonymous
volumes of every project on this machine. It keeps named volumes such as `db-data`; only
`--all` deletes those.

The Django admin is at <http://localhost:5173/admin/>. Create a login for it with
`createsuperuser`. The development server serves the admin's CSS only when
`DJANGO_DEBUG=1`, as in `.env.example`.

Rebuild after changing `backend/requirements.txt` or `frontend/package.json`:

```sh
docker compose up --build --renew-anon-volumes
```

`node_modules` lives in an anonymous volume, not in `frontend/`. Without
`--renew-anon-volumes`, the container keeps the old volume and the new packages are
missing.

## Demo data

```sh
docker compose run --rm backend python manage.py seed_demo
```

creates three demo users. Running it again changes nothing: users that already exist are
left as they are. Log in at <http://localhost:5173> with any of them, using the password
`gear-library-demo`:

| Phone number | Name |
|---|---|
| (555) 555-0101 | Avery Brooks |
| (555) 555-0102 | Jordan Diaz |
| (555) 555-0103 | Sam Okafor |
