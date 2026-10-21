# Gear Library

This is a toy project inspired by the Chicago Tool Library and Little Free Libraries. The
project allows users to make connections and borrow items from each other. Connections
really should only be made with trusted friends in real life, which practically limits
the scope of the user network.

The model is built around users, connections, and inventories with 3 major roles. I went
with this style of model because I was interested in learning about Django Rest Framework
and the access control features it offered. I thought that user defined inventories would
mesh nicely with the concept of user groups. I also figured it would introduce relevant
distributed systems problems that some simpler models would miss. The three roles in an
inventory are:

- `member`: this role is limited to borrowing items from an inventory.
- `admin`: this role can approve/decline requests to borrow items as well as add/remove
  items and members from an inventory. I was thinking of this role as a roommate in a
  house with a shared inventory, or a regular at a shared workshop.
- `owner`: the owner has the responsibility of the admin, but additionally can change
  the roles of the inventory's members.

The full rights of each role are in [`docs/schema.md`](docs/schema.md). In order to add
users to inventories, you must first connect with them using the phone number associated
with the account. I wanted a simple user login flow and connection mechanism. Phone
number seemed nice to me because it implies that connecting users already trust each
other enough in real life to swap numbers. Additionally, it means connected users
already have a communication channel, and I didn't want to include a chat in the scope
of this project.

In hindsight I would have preferred a simpler solution because I couldn't review it all,
but toward the beginning of the project I was more nervous about submitting something
trivial. I'd like to call out that I included a front-end because I wanted to provide
a concrete demo, however I did not review any of the front-end code. I'm not a front-end
expert by any means, I just wanted an end-to-end prototype. I spent my development time
reviewing the backend, which was basically all written by Claude code. I reviewed all of
the backend source code, although I was learning some Django Rest Framework best
practices on the fly so I definitely had some blind spots. I also collaborated with
Claude on test design for the project, but didn't actually review most of the test code.
I got a little too ambitious and realized I couldn't finish this project end-to-end if
I fully reviewed the front-end or tests.

The rest of this doc outlines how to setup/build/run this app and is written by Claude.

Runs locally with Docker Compose: PostgreSQL, a Django REST Framework backend and a Vite +
React frontend. The database design is in [`docs/schema.md`](docs/schema.md) and the API
draft is in [`docs/api.md`](docs/api.md).

## Setup

```sh
cp .env.example .env    # then set a real password and secret key, and your UID and GID
docker compose up --build
```

Open <http://localhost:5173>, then create an account or log in as a demo user (see
[Demo data](#demo-data)). To check that the backend and database are up:

```sh
curl http://localhost:5173/api/health/
```

It answers `{"status": "ok", "database": "ok"}`, or `503` when the database is
unavailable. On a first start the backend may still be migrating, so try again after a
few seconds.

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
docker compose run --rm backend python manage.py seed_demo    # demo data, see below
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

creates four demo users, three inventories, the users' connections, their gear, one borrow
request and one loan. Running it again changes nothing: users that already exist are left
as they are, a demo inventory is skipped when its owner below is already in an inventory
with that name, a demo connection is skipped when the two users already have a connection
or a request, and a demo item is skipped, with its listings and its loan, when its owner
already has an item with that name. The tables below describe a freshly seeded database.

Log in at <http://localhost:5173> with any of them, using the password `gear-library-demo`:

| Phone number | Name | Climbing Club | Camping Crew | Hiking Group |
|---|---|---|---|---|
| (555) 555-0101 | Avery Brooks | owner | member | pending invite from Sam, not a member yet |
| (555) 555-0102 | Jordan Diaz | admin | owner | not a member |
| (555) 555-0103 | Sam Okafor | member | admin | owner |
| (555) 555-0104 | Riley Nakamura | not a member | not a member | not a member |

Discover shows a user only the items they can borrow but not use themselves: Avery sees
the Camping Crew gear and Sam the Climbing Club gear, except the first aid kit, which is
listed in both. Jordan is an admin or owner everywhere and sees nothing. Riley is in no
inventory, has no gear and sees nothing. Hiking Group has no gear.

Connections:

- Avery, Jordan and Sam are all connected to each other. Every invite, accepted or
  pending, went to a connection of its sender.
- Riley has sent Avery a request, which is pending.

Gear, and where it is listed:

| Owner | Item | Listed in |
|---|---|---|
| Avery | Climbing rope, Belay device | Climbing Club |
| Avery | Headlamp | nowhere |
| Jordan | Quickdraws | Climbing Club |
| Jordan | First aid kit | Climbing Club and Camping Crew |
| Jordan | Two-person tent | Camping Crew |
| Sam | Camp stove, Sleeping bag | Camping Crew |
| Sam | Chalk bag | nowhere |

Borrowing:

- Sam has asked to borrow Avery's climbing rope through Climbing Club. The request is
  pending.
- Sam has Jordan's two-person tent on loan through Camping Crew.
