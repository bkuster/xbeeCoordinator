# -----------------------------------------------------------------------------
# Copyright (c) Ben Kuster 2015, all rights reserved.
#
# Created: 	2015-10-4
# Version: 	0.1
# Purpose: 	Main Python3 code for running a wireless sensor network gateway node
#           on a Raspberry Pi 2 with 4 cores
#
# TODO:     Implementation of conifg files? Or Argparse? If needed
#           - argparse for serial port selection?
#
# This software is provided under the GNU GPLv2
# WITHOUT ANY WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
# If no license was provided, see <http://www.gnu.org/licenses/>
# -----------------------------------------------------------------------------
# ENVIRONMENT
# -----------------------------------------------------------------------------
# standards
import os
import time
from datetime import datetime
import json
import numpy as np
from pathlib import Path
np.set_printoptions(suppress = True) # to suppres scientific writing

# MPI
from mpi4py import MPI

# -----------------------------------------------------------------------------
# MPI SETUP
# To allow for parralel procesing with communication capabilities
# Communication is actually not needed, but could be
# -----------------------------------------------------------------------------
def enum(*sequential, **named):
    """Handy way to fake an enumerated type in Python
    http://stackoverflow.com/questions/36932/how-can-i-represent-an-enum-in-python
    """
    enums = dict(zip(sequential, range(len(sequential))), **named)
    return type('Enum', (), enums)

# define MPI tags
tags = enum('GO', 'ERROR', 'EXIT')

# communiction
comm = MPI.COMM_WORLD
size = comm.Get_size()
rank = comm.Get_rank()
status = MPI.Status()

# -----------------------------------------------------------------------------
# Rank 0 :  THE QUEEN   - Dumps XBee frames
# Rank 1 :  THE GUARD   - Handles errors & requests. Does some data insertion
# Rank 2+:  WORKER BEES - Data insertion
# -----------------------------------------------------------------------------
if rank == 0:
    # XBee
    import serial
    from xbee import XBee, ZigBee

    print("Queen initialization...")

    # Make worker directories
    paths = [Path('./temp/guard/')]
    #paths = ['./temp/guard', './temp/guard/error']
    for i in range(2,size):
        paths.append(Path('./temp/worker{0}/'.format(size-i)))

    for path in paths:
        try:
            path.mkdir(parents=True)
        except:
            print("Folder {0} allready exists".format(path))

    # --------------------------------------------------------------------------
    # FUNCTION dumps
    # dumps the recieved dictionary as a json to a given
    def dumping(obj):
        if obj['id'] != 'rx':
            return
        # make ints from buffer, json cant store bytes...
        for key, value in obj.items():
            if type(value) == bytes:
                obj[key] = np.frombuffer(value, np.uint8).tolist()

        stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%s') + '.json'

        # is it normal data?
        if(obj['rf_data'][0] == 1):
            path = paths.pop()
            with path.joinpath(stamp).open('w') as f:
                json.dump(obj, f)
            paths.insert(0, path)
        else:
            print("sensor active")
            err_path = Path('./temp/guard/' + stamp)
            with err_path.open('w') as f:
                json.dump(obj, f)



    # init xbee
    ser = serial.Serial('/dev/cu.usbserial-DA017S4F', 115200)
    xbee = ZigBee(ser, escaped=True, callback=dumping)
    # Go
    print("Queen active!")
    while True:
        try:
            while not comm.Iprobe(source = MPI.ANY_SOURCE, tag = MPI.ANY_TAG):
                time.sleep(0.001)

            data = comm.recv(source = MPI.ANY_SOURCE, tag = MPI.ANY_TAG, status = status)
            tag = status.Get_tag()
            xbee.tx(dest_addr_long=bytes(data[0]), dest_addr = bytes(data[1]), data=bytes([tag]))
            ser.flush()

        except KeyboardInterrupt:
            break
    # close it, otherwise you get errors when shutting down
    xbee.halt()
    ser.close()

elif rank == 1:
    print("Guard initialization...")
    from guard import guard
    guard_bee = guard('http://quader.igg.tu-berlin.de/istsos/demo', comm)
    print("Guard ready!")
    guard_bee.routine()

elif rank > 1:
    number = comm.Get_size() - rank
    print("Worker #{0} initialization...".format(number))
    import worker
    worker_bee = worker.bee(number)

    print("Worker #{0} Ready!".format(number))
    worker_bee.routine()
