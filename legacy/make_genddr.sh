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

declare -a interm=("NONE" "40" "50" "60")
declare -a strengths=("34ohm" "40ohm")

if [ "$RUN" = "all" ] || [ "$RUN" = "100T" ]
then
    echo "Running user 100T FPGA build..."
    for term in "${interm[@]}"
        do
   	   for strength in "${strengths[@]}"
	   do
		     ./netv2mvp_genddr.py -p 100 -t video_overlay -d 112.5 -i $term -s $strength 
		     cp ./build/gateware/top.bit ./genddr-images/user100-f$term-d$strength.bit
           done
	done
fi

if [ "$RUN" = "all" ] || [ "$RUN" = "35T" ]
then
    echo "Running user 35T FPGA build..."
    for term in "${interm[@]}"
        do
   	   for strength in "${strengths[@]}"
	      do  
#	       echo user35-f$term-d$strength.bit
		     ./netv2mvp_genddr.py -p 35 -t video_overlay -d 112.5 -i $term -s $strength 
		     cp ./build/gateware/top.bit ./genddr-images/user35-f$term-d$strength.bit
           done
	done
fi

echo "Running user firmware build..."
cd ./firmware && make clean && make && cd ..
cp ./firmware/firmware.bin ./genddr-images/genddr-firmware.bin

echo "All requested builds done."

exit 0
