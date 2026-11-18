#!/bin/sh
# Run the Django test suite. Extra arguments are passed to "manage.py test", e.g.
#   ./run_tests.sh web.tests.test_entities
#   ./run_tests.sh -v 2
cd "$(dirname "$0")/nspanelmanager" || exit 1

# base.html includes scripts.html, which the React build generates and which is not committed. The
# pages the tests render need it to exist, not to be real, so write an empty stand-in if there is no build.
scripts_html=web/react-components/templates/scripts.html
if [ ! -f "$scripts_html" ]; then
    mkdir -p "$(dirname "$scripts_html")"
    echo "{# stand-in written by run_tests.sh #}" > "$scripts_html"
fi
exec python manage.py test --settings=nspanelmanager.test_settings "$@"
