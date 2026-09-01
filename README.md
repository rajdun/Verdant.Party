# Verdant

Django app do sprzedazy kwiatow online. Modularna struktura: `catalog`, `inventory`, `orders`, `users`, `finance`, `logistics`, `marketplaces` (patrz `src/apps/`).

## Wymagania

- Docker + Docker Compose

## Start od zera (Docker)

```bash
cp .env.example .env

docker compose up -d --build

docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate

docker compose exec web python manage.py createsuperuser

docker compose exec web python manage.py collectstatic --noinput
```

App: http://localhost:8000
Admin: http://localhost:8000/admin/
Postgres: `localhost:5432` (`verdant` / `verdant` / `verdant` domyslnie, patrz `.env`)

## Codzienna praca

```bash
docker compose up -d          # start w tle
docker compose logs -f web    # logi appki
docker compose down           # stop (baza zostaje w wolumenie)
docker compose down -v        # stop + kasuje dane bazy
```

Zmiana modeli:

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

Shell / testy:

```bash
docker compose exec web python manage.py shell
docker compose exec web python manage.py test
```

## Start bez Dockera (lokalny venv)

Wymaga lokalnie postgresa (lub zmiany `POSTGRES_HOST` w `.env` na `localhost`).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r src/requirements/dev.txt

export POSTGRES_HOST=localhost   # jesli postgres lokalnie, nie w Dockerze

cd src
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Struktura

```
src/
├── config/            # ustawienia projektu (settings/base|dev|prod.py), urls, wsgi/asgi
├── apps/
│   ├── common/         # abstrakcyjne base models (TimeStampedModel)
│   ├── catalog/         # produkty, kategorie
│   ├── inventory/         # stan magazynowy
│   ├── orders/             # koszyk, zamowienia
│   ├── users/               # custom user model, auth
│   ├── finance/               # platnosci, faktury
│   ├── logistics/               # dostawa
│   └── marketplaces/             # integracje zewnetrzne (np. Allegro)
├── templates/          # globalne szablony
├── static/              # globalne statyki
└── requirements/         # base / dev / prod
```
