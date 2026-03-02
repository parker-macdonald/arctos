# Arctos

Centralized online results and event management for Jugger.  

Or, *what the fog site always wanted to be*  

see [CONTRIBUTING](CONTRIBUTING.md) for how to get involved.

## Running the App

### Part 1: Backend

1. Install [uv](https://docs.astral.sh/uv/).
2. Set up your SSL certs. if you're using nginx you can do this there
   and use certbot or something. If you're just testing, you can
   create self-signed certs:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 365
```

3. Create a bash script called `run` with the following contents:

```bash
#!/bin/bash -e

uv sync

ARCTOS_CORS_DEV=1 \
ARCTOS_API_BASE=http://127.0.0.1:8081 \
EXTERNAL_BASE_URL=your_public_domain_or_ip \
PYTHONPATH=path/to/arctos:$PYTHONPATH \
YOUTUBE_API_KEY=your_youtube_api_key \
GOOGLE_CLIENT_SECRET=your_google_client_secret \
GOOGLE_CLIENT_ID=your_google_client_id \
SECRET_KEY=your_app_secret_key \
	uv run gunicorn \
        --workers=5 \
        --bind 0.0.0.0:8081 \
        --log-level debug \
        --certfile=cert.pem \
        --keyfile=key.pem \
        run_app:app

```

with all the info filled out. If you don't have some of these, you can
leave them empty; they are only needed for the sign in with google and
youtube auto-seek features.  the `SECRET_KEY` variable must be a
random value for security reasons. You can get one by running

```bash
python -c "import os; print(os.urandom(12).hex())"
```

The gunicorn args provided are just examples; set workers as high as
you'd like, set it to bind to whatever you need, and omit the
`certfile` and `keyfile` arguments if you're handling SSL elsewhere.

> [!IMPORTANT] 
> 
> The `ARCTOS_CORS_DEV` and `ARCTOS_API_BASE` are only for dev
> environments where you don't have a reverse proxy set up to direct
> traffic and are thus hosting the frontend and backend on different
> ports.

4. run `chmod +x run`
5. finally, start the app with `./run`

#### Video storage

To store finalized match recordings in an s3 compatible bucket (I use
Backblaze B2) instead of local disk, set these environment variables
in your `run` script:

| Variable | Required | Description |
|----------|----------|-------------|
| `S3_VIDEO_BUCKET` | Yes | bucket name (create a private bucket in the B2 dashboard). |
| `S3_ENDPOINT_URL` | Yes (for B2) | B2 S3-compatible endpoint, e.g. `https://s3.us-west-002.backblazeb2.com`. Use the endpoint for the region where you created the bucket. |
| `AWS_REGION` | Yes (for B2) | Must match the endpoint region, e.g. `us-west-002` or `us-east-005`. |
| `AWS_ACCESS_KEY_ID` | Yes | Application Key ID. Needs R/W access. |
| `AWS_SECRET_ACCESS_KEY` | Yes | corresponding secret key |
| `S3_PRESIGNED_EXPIRY_SECONDS` | No | Presigned URL lifetime in seconds (default `3600`). |

### Part 2: Frontend

Install the Dioxus CLI:

```bash
cargo install dioxus-cli
```

then (for development) simply `cd frontend` and serve the app:

```bash
dx serve
```

In production, you should run `dx bundle --release` and copy the
output files to somewhere that your reverse proxy can serve.
