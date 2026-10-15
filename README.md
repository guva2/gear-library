# Gear Library

Share gear with the people you know. Gear belongs to a household. You can see and borrow
gear from your connections' households.

Runs locally with Docker Compose: PostgreSQL and a Django backend. The database design is
in [`docs/schema.md`](docs/schema.md).

## Setup

```sh
cp .env.example .env    # then set a real password and secret key
docker compose up -d db
docker compose run --rm backend python manage.py migrate
```

The database port is not published to the host.

## Common commands

```sh
docker compose run --rm backend pytest                        # run the tests
docker compose run --rm backend python manage.py createsuperuser
docker compose run --rm backend python manage.py makemigrations
docker compose build backend                                  # after code changes
docker compose down                                           # stop; data stays in the volume
docker compose down -v                                        # stop and delete the data
```

The backend image copies the source at build time, so rebuild it after changing code.
`makemigrations` writes the new migration inside the container. To get the file into the
working tree, mount the source:

```sh
docker compose run --rm --user "$(id -u):$(id -g)" -v "$PWD/backend:/app" \
  backend python manage.py makemigrations
```
