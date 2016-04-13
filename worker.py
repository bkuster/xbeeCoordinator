# -----------------------------------------------------------------------------
# Copyright (c) Ben Kuster 2015, all rights reserved.
#
# Created: 	2015-10-4
# Version: 	0.1
# Purpose: 	Defines the Base 'worker' class for the gateway node
#
# This software is provided under the GNU GPLv2
# WITHOUT ANY WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
# If no license was provided, see <http://www.gnu.org/licenses/>
# -----------------------------------------------------------------------------
# ENVIRONMENT
# -----------------------------------------------------------------------------
import struct
from pathlib import Path
import time
import sys
import logging

# TODO not needed, just for testing
import json
import numpy as np
from datetime import datetime

# sql capabilities
import sqlite3

class bee():
    def __init__(self, rank):
        # TASK relevant
        self.id       = rank      # id needs to be a string, needed for path
        self.__tasks  = []        # tasks is the content of path
        self.__newest = 0         # the st_ctime of the newest task
        self.__current_file = str()

        # DATA relevant
        self.__frame  = {}       # processing data frame
        self.__mac   = str()     # current MAC address as string
        self.__uuid = str()      # current UUID as specified by istsos
        self.__row_structure = []# defines the row structure
        self.__data = []         # data tuples to be inserted
        self.__conn = sqlite3.connect('./data/data.dbf')
        self.__path = Path('./temp/worker{0}'.format(rank))

    # --------------------------------------------------------------------------
    # get content of path
    # and add to tasks if newer then newest
    def __update_task(self):
        files = list(self.__path.glob('*.json'))
        for p in files:
            # check for new
            if p.stat()[-1] > self.__newest:
                self.__tasks.append(p) # used to be insert 0,y ?
                self.__newest = p.stat()[-1]
            else:
                continue

    # --------------------------------------------------------------------------
    # CONVERSIONS
    # --------------------------------------------------------------------------
    # __change_sensor changes the currently inserting sensor relevant info
    # such as self.__mac and self.___row_structure
    def __change_sensor(self):
        query = open('./resources/sql/get_row_structure.sql').read().format(self.__mac)
        cur = self.__conn.cursor()
        cur.execute(query)
        self.__row_structure = np.array(cur.fetchall())
        cur.close()

    # --------------------------------------------------------------------------
    # temporary make_data
    def __row_from_bytes(self, line):
        line = list(line)
        raws = []

        for i in range(6):
            raw = line.pop()
            raw = (raw << 8) + line.pop()
            s = struct.pack('H', raw)
            raw = struct.unpack('h', s)[0]
            raws.append(raw)

        time = line.pop()
        for x in range(1,4):
            time = (time << 8)+line.pop()
        unpacked = []
        raws = list(reversed(raws))
        unpacked.append(time)
        for i in range(3):
            unpacked.append(raws[i]/16384.0)
        for i in range(3):
            unpacked.append(raws[i+3]/131.072)

        return(unpacked)
    # --------------------------------------------------------------------------
    # creat__data
    # creates an insertable data packet from the data frame
    # the order of the __row_structure defines the property_ID and
    # should be cycled though: TODO signed unsigned stuff, more variable, sofar hack
    # TODO better integration of temperature. what if sensor doesnt have temp?
    # in general, this entire thing needs better modelling. both here an DB side.
    def __create__data(self):
        row_size = sum(self.__row_structure[:,1])
        data = self.__frame['rf_data']

        if data.pop(0) != 1:
            logging.warning('GOT NO DATA')
            return

        # get the time offset
        timestamp = data.pop(0)
        for i in range(1,4):
            timestamp = (timestamp << 8) + data.pop(0)

        temperature = (data.pop(0) << 8) + data.pop(0)
        temperature = (temperature/340.0)+36.53

        # make arra of rows
        data = np.array(data, ndmin = 2).reshape(10, row_size)
        # structure = self.__row_structure[:,1].tolist()
        # structure = list(reversed(structure)) # backwars because of endian
        rows = []
        # get each row
        for i in range(10):
            row = data[i,:].tolist()
            row = self.__row_from_bytes(row)
            row.append(temperature)# put temperature first, order of structure

            # make timestamp
            if row[0] > 0:
                row[0] = timestamp + (row[0]/1000)
                rows.extend(row)
            else:
                continue

        self.__data = np.array(rows, ndmin = 2).reshape(len(rows)/8, 8) # +1 for temp...
        # TODO this needs to be smoother
        # add temperature to the row_structure for simplicity
        self.__row_structure = np.vstack((self.__row_structure, np.array([8,0], ndmin = 2)))

    # --------------------------------------------------------------------------
    # insert data
    def __insert__data(self):
        # get it into a list of tuples
        query = "INSERT INTO observation VALUES "
        for i in range(self.__data.shape[0]):
            row = self.__data[i,:]
            timestamp = datetime.isoformat(datetime.utcfromtimestamp(row[0]))

            # timestamp is 0, so start at 1
            for j in range(1, len(row)):
                query = query + "('{}', {}, '{}', {}),".format(self.__mac, self.__row_structure[j,0], timestamp, row[j])

        cur = self.__conn.cursor()
        try:
            cur.execute(query[:-1]) # -1 for last ,
            self.__conn.commit()
        except:
            logging.warning('insert error')
            e = sys.exec_info()[0]
            logging.warning(e)
            logging.warning(query)
        cur.close()

    # --------------------------------------------------------------------------
    # process a task
    def __process(self):
        # assign the first task as current task
        self.__current_file = self.__tasks.pop(0)
        with self.__current_file.open() as f:
            self.__frame = json.load(f)
            self.__frame['source_addr_long'] = "".join("{:02x}".format(c) for c in self.__frame['source_addr_long'])

            # see if we got a new sensor
            if self.__frame['source_addr_long'] != self.__mac:
                self.__mac = self.__frame['source_addr_long']
                self.__change_sensor()

            # create numpy array
            self.__create__data()
            self.__insert__data()

        # delete the json
        self.__current_file.unlink()

    # --------------------------------------------------------------------------
    # routine() PUBLIC
    # Go!
    def routine(self):
        while True:
            try:
                self.__update_task()
                time.sleep(2) # snooze to let queen dump...
                while(len(self.__tasks) > 0):
                    self.__process()
            except KeyboardInterrupt:
                break
