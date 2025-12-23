# Arctos

Centralized online results and event management for Jugger.  

Or, *what the fog site always wanted to be*  

see [CONTRIBUTING](CONTRIBUTING.md) for how to get involved.

## Running the App

1. Install [uv](https://docs.astral.sh/uv/).
2. Set up your SSL certs. if you're using nginx you can do this there and use certbot or something. If you're just testing, you can create self-signed certs:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 365
```

3. Create a bash script called `run` with the following contents:

```bash
#!/bin/bash -e

uv sync

PYTHONPATH=path/to/arctos:$PYTHONPATH \
YOUTUBE_API_KEY=your_youtube_api_key \
GOOGLE_CLIENT_SECRET=your_google_client_secret \
GOOGLE_CLIENT_ID=your_google_client_id \
SECRET_KEY=your_app_secret_key \
	uv run gunicorn \
        --workers=5 \
        --bind 0.0.0.0:8080 \
        --log-level debug \
        --certfile=cert.pem \
        --keyfile=key.pem \
        run_app:app

```

with all the info filled out. If you don't have some of these, you can leave them empty; they are only needed for the sign in with google and youtube auto-seek features.
the `SECRET_KEY` variable must be a random value for security reasons. You can get one by running

```bash
python -c "import os; print(os.urandom(12).hex())"
```

The gunicorn args provided are just examples; set workers as high as you'd like, set it to bind to whatever you need, and omit the `certfile` and `keyfile` arguments if you're handling SSL elsewhere.

4. run `chmod +x run`
5. finally, start the app with `./run`