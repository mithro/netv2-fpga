#!/bin/bash

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

declare -a cables=("pcb" "cable")

if [ "$RUN" = "all" ] || [ "$RUN" = "35T" ]
then
    echo "Running user 35T FPGA build..."
    for cable in "${cables[@]}"
    do  
	./netv2mvp.py -p 35 -t video_overlay -d 112.5 -c $cable
	cp ./build/gateware/top.bit ./testing-images/user35-$cable.bit
    done
fi

if [ "$RUN" = "all" ] || [ "$RUN" = "100T" ]
then
    echo "Running user 100T FPGA build..."
    for cable in "${cables[@]}"
    do
	./netv2mvp.py -p 100 -t video_overlay -d 112.5 -c $cable
	cp ./build/gateware/top.bit ./testing-images/user100-$cable.bit
    done
fi

echo "Running user firmware build..."
cd ./firmware && make clean && make && cd ..
cp ./firmware/firmware.bin ./testing-images/testing-firmware.bin

echo "All requested builds done."

exit 0
