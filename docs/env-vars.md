# Environment Variables

This is a list of all environment variables that can be used to
configure Arctos.

`SECRET_KEY`
: the flask secret. generate randomly.

`ARCTOS_CORS_DEV`
: (default `0`) if `1`, sets cookies to allow CORS requests. needed for development
  when we don't have a reverse proxy set up.
  
`ARCTOS_PORT`
: (default `5006`) port to run the backend on. 

`SQLALCHEMY_DATABASE_URI`
: fairly self explanatory. URI to db.

`SCRIPT_NAME`
: path prefix for subpath deployments. ngl i have no clue why I added
  this so it may be removed

`MAX_CONTENT_LENGTH_BYTES`
: max content length in a single request. a flask setting.

`SILLY_USERS`
: colon-separated list of silly users.

`RECORDING_ARTIFACTS_AFTER_UPLOAD`
: (default: `delete`) what to do with footage after it's been uploaded. either `delete` or `s3` (upload to s3 bucket)

`ENABLE_MANUAL_FOOTAGE_UPLOADS`
: (default: `false`) on `true`, show button to upload footage on tournament page.

`RETRY_FINALIZATION_USER_IDS`
: colon-separated list of users that see the button to retry video finalization.


## Google Oauth2 info

go to google cloud console for these

`GOOGLE_CLIENT_ID`
: client ID

`GOOGLE_CLIENT_SECRET`
: client secret.

Google OAuth callback URLs are derived from the incoming request host. If the
same server is reachable on multiple public domains, add each domain's
`/_api/auth/google/callback` URL to the authorized redirect URIs in Google
Cloud Console.


## S3 Bucket Config

`AWS_REGION`

`AWS_ACCESS_KEY_ID`

`AWS_SECRET_ACCESS_KEY`

`S3_ENDPOINT_URL`

`S3_PRESIGNED_EXPIRY_SECONDS`

`S3_VIDEO_BUCKET`

`S3_VIDEO_PREFIX`

## Youtube config

`YOUTUBE_API_KEY`
: its literally just the youtube api key what explanation do you want

`YOUTUBE_UPLOAD_CLIENT_ID`
: client id for youtube

`YOUTUBE_UPLOAD_CLIENT_SECRET`
: client secret for youtube

`YOUTUBE_UPLOAD_REFRESH_TOKEN`
: go to the google api playground and change the settings to 'use my
  client ID and secret' or something in order to get this

`YOUTUBE_UPLOAD_PRIVACY_STATUS`
: (default `unlisted`) the privacy status to set youtube videos to.

`YOUTUBE_UPLOAD_CATEGORY_ID`
: (default 22) youtube category to upload to. probably should default
to 17 since thats what its set to in prod rn.


