#!/bin/sh
# Run the project-local Ontop CLI with the project-local JDK (no system Java needed).
HERE="$(cd "$(dirname "$0")" && pwd)"
export JAVA_HOME="$(ls -d "$HERE"/jdk/*/Contents/Home)"
export PATH="$JAVA_HOME/bin:$PATH"
exec "$HERE/ontop/ontop" "$@"
