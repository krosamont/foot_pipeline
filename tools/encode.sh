#!/bin/sh
# usage: tools/encode.sh out/frames out/fabric.mp4 30
# standard-range yuv420p H.264 (the JPEG frames are full range), so QuickTime, browsers and phones play it
cd "$(dirname "$0")/.."
ffmpeg -v error -y -framerate ${3:-30} -i "$1/f_%05d.jpg" -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2,scale=in_range=pc:out_range=tv,format=yuv420p" -c:v libx264 -profile:v high -crf 18 -preset medium -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 -movflags +faststart -tag:v avc1 "$2" && echo "encoded $2"
