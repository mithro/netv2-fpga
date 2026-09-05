#!/bin/sh

PYTHONHASHSEED=1

if [ -z "$1" ]
then
    RUN="all"
    echo "None of 100T or 35T specified, so building all variants." 
else
    if [ "$1" = "help" ]
    then
	echo "Valid build options: 100T or 35T. Blank is the same as all."
	exit 0
    fi
    RUN="$1"
    echo "Run set to $1."
fi

if [ "$RUN" = "all" ] || [ "$RUN" = "35T" ]
then
    echo "Running user 35T FPGA build..."
    ./netv2mvp.py -p 35 -t video_overlay
    cp ./build/gateware/top.bit ./production-images/user-35.bit
fi

if [ "$RUN" = "all" ] || [ "$RUN" = "100T" ]
then
    echo "Running user 100T FPGA build..."
    ./netv2mvp.py -p 100 -t video_overlay
    cp ./build/gateware/top.bit ./production-images/user-100.bit
fi

echo "Running user firmware build..."
cd ./firmware && make clean && make && cd ..
cp ./firmware/firmware.bin ./production-images/user-firmware.bin

echo "All requested builds done."

exit 0
