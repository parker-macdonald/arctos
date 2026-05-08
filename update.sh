#!/bin/bash

set -e

cd $REPO_ROOT

git fetch origin
git reset --hard $GIT_BRANCH

. $CARGO_ENV_FILE

cd frontend
dx bundle --web --release
chmod -R a+rwX dist/public
cp -r dist/public $FRONTEND_SERVER_ROOT

systemctl --user stop arctos
make db-backup
make db-migrate
systemctl --user start arctos

cd ../docs

if [ "$BUILD_DOCS" -eq 1 ]; then
  make html
  chmod -R a+rwX _build
  cp -r _build/html $DOCS_SERVER_ROOT
fi

set +e

