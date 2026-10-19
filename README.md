# Gear Library

Share gear through inventories. You own your items. An inventory is a group of people who
share gear: only its members see it and the items listed in it. You can create or join any
number of inventories, and you have one role in each:

- `member`: sees and borrows the inventory's items.
- `admin`: also lists and removes their own items, approves and declines borrow requests
  made through the inventory, and marks those items returned.
- `owner`: also invites users, removes members and sets their roles.

Runs locally with Docker Compose: PostgreSQL, a Django REST Framework backend and a Vite +
React frontend. The database design is in [`docs/schema.md`](docs/schema.md) and the API
draft is in [`docs/api.md`](docs/api.md).

## Setup

```sh
cp .env.example .env    # then set a real password and secret key, and your UID and GID
docker compose up --build
```

Open <http://localhost:5173>. The page shows whether the backend and database are up.

`docker compose up` starts three services:

- `db`: PostgreSQL. Data is kept in the `db-data` volume.
- `backend`: Django on port 8000 inside the Compose network. It waits for the database,
  applies migrations, then runs the development server.
- `frontend`: the Vite dev server, published on `127.0.0.1:5173` only. It forwards
  `/api` to the backend, so the browser sees one origin.

Only the frontend port is published to the host. `backend/` and `frontend/` are mounted
into their containers, so code changes reload without a rebuild. The containers run as
the `UID` and `GID` in `.env`, so files they write are yours.

## Common commands

```sh
docker compose run --rm backend pytest                        # backend tests
docker compose run --rm frontend npm test                     # frontend tests
docker compose run --rm backend python manage.py makemigrations
docker compose run --rm backend python manage.py createsuperuser
docker compose run --rm frontend npm install --save-exact <package>
docker compose down                                           # stop; data stays in the volume
docker compose down -v                                        # stop and delete the data
```

Rebuild after changing `backend/requirements.txt` or `frontend/package.json`:

```sh
docker compose up --build --renew-anon-volumes
```

`node_modules` lives in an anonymous volume, not in `frontend/`. Without
`--renew-anon-volumes`, the container keeps the old volume and the new packages are
missing.
