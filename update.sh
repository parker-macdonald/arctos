#!/bin/bash

set -e

. $BASHRC_PATH

cd $REPO_ROOT


if [ "${HAS_PULLED:-0}" -ne 1 ]; then
    git fetch origin
    git reset --hard $GIT_BRANCH
    exec env HAS_PULLED=1 $REPO_ROOT/update.sh
    exit 0
fi

. $CARGO_ENV_FILE

cd frontend
dx bundle --web --release
chmod -R a+rwX dist/public
cp -r dist/public $FRONTEND_SERVER_ROOT

cd ..

systemctl --user stop arctos
make db-backup
make db-migrate
systemctl --user start arctos

cd docs

if [ "$BUILD_DOCS" -eq 1 ]; then
  make html
  chmod -R a+rwX _build
  cp -r _build/html $DOCS_SERVER_ROOT
fi

set +e
