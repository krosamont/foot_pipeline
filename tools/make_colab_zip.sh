#!/bin/sh
# Pack what Colab needs (pipeline package, tests + frozen data, requirements, notebook) into dist/pmd_colab.zip
# usage: tools/make_colab_zip.sh
cd "$(dirname "$0")/.."
mkdir -p dist
rm -f dist/pmd_colab.zip
zip -qr dist/pmd_colab.zip pmd tests requirements.txt postmatchdashboard_whoscored_v2.py notebooks/run_on_colab.ipynb -x "*/__pycache__/*" && echo "wrote dist/pmd_colab.zip ($(du -h dist/pmd_colab.zip | cut -f1))"
