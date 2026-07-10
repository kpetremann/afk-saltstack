#!/bin/bash

# Lint Salt states written in pure Python (files starting with "#!py").
# Ruff configuration lives in pyproject.toml; "*.sls" files are treated as
# Python via the "extend-include" setting.

ret=0

for f in `find . -type f -iname "*.sls"`
do
    header=`head -1 $f`
    if [ "$header" == "#!py" ]
    then
        ruff check "$f"
        ret=$(($ret+$?))
        ruff format "$f" --check
        ret=$(($ret+$?))
    fi
done

exit $ret
