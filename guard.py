# -----------------------------------------------------------------------------
# Copyright (c) Ben Kuster 2015, all rights reserved.
#
# Created: 	2015-10-6
# Version: 	0.2
# Purpose: 	GUARD class definition. Monitoring of a Wirless sensor network
# TODO:
# Priority: - Implement selecting and passing criteria for start (argparse?)
#           - Change SOS object to be recreated due to changes on the server!
#
# Future:   - Implement WFS query for position and FOI
#
# This software is provided under the GNU GPLv2
# WITHOUT ANY WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
# If no license was provided, see <http://www.gnu.org/licenses/>
# -----------------------------------------------------------------------------
import sqlite3
import time
import re

# OSWlib stuff
from owslib.sos import SensorObservationService
from owslib.fes import FilterCapabilities
from owslib.ows import OperationsMetadata
from owslib.crs import Crs
from owslib.util import http_post
from owslib.swe.sensor.sml import SensorML
from operator import itemgetter
import xml.etree.ElementTree as ET

from functools import reduce

# NOT needed, kill, just for debugin
from datetime import datetime
import json
import numpy as np
from pathlib import Path
np.set_printoptions(suppress = True)

from mpi4py import MPI
def enum(*sequential, **named):
    """Handy way to fake an enumerated type in Python
    http://stackoverflow.com/questions/36932/how-can-i-represent-an-enum-in-python
    """
    enums = dict(zip(sequential, range(len(sequential))), **named)
    return type('Enum', (), enums)

# define MPI tags
tags = enum('GO', 'ERROR', 'EXIT')

class guard():
    def __init__(self, url, comm):
        self.__path = Path('./temp/guard')
        self.__conn = sqlite3.connect('./data/data.dbf')
        self.__max_count = 100  # define when to insert, very low: DEMO!
        self.__max_time = 60    # number of seconds to wait for insert, low:DEMO!
        self.__max_age = 0      # TODO not implemeted
        self.__check_table = []
        self.__last_insert = datetime.strptime('1970-01-01T00:00:00.0001', '%Y-%m-%dT%H:%M:%S.%f')  # check with max time
        # TODO last insert makes no sense to be honest. need to save time AND sensor... better to
        # do it with the age of the data itself

        # istSOS values
        self.__url = url
        self.__comm = comm

        # current sensor values
        self.__observed_properties = [] # name, urn, uom, size (bytes)
        self.__data = []                # numpy array of data

        # current XML values
        self.__xml_dict = {}            # holds all the named placeholders needed
        self.__xml = str()

        # error handling & sensor registration
        self.__frame = {}
        self.__mac = str()
        self.__uid = str()
        self.__nobs = int()             # number of observations when registering
        self.__frame_id = 1             # frame number we're working on reset after register

    # --------------------------------------------------------------------------
    # __check
    # checks to see if something is ready to be done
    # TODO this should include errors, but DEMO only DB is checked
    def __check(self):
        # check path for files
        files = list(self.__path.glob('*.json'))
        if len(files) > 0:
            # we got an error!
            self.__handle_error(files[0])

        # check DB
        cur = self.__conn.cursor()
        cur.execute(open('./resources/sql/get_data_count.sql').read())
        self.__check_table = np.array(cur.fetchall())
        cur.close()

    # --------------------------------------------------------------------------
    # ERROR HADNLING
    # --------------------------------------------------------------------------
    def __handle_error(self, in_file):
        with in_file.open() as f:
            self.__frame = json.load(f)

            # pass it on to the next task, error or register
            if self.__frame['rf_data'][0] == 3:
                self.__sensor_boot()
            else:
                self.__raise_error() # TODO
                in_file.unlink()

    # --------------------------------------------------------------------------
    # raises the error, via WNS? and others...
    def __raise_error(self):
        logging.debug('got an error:')
        logging.debug(self.__frame) # TODO should be warning

    # --------------------------------------------------------------------------
    # unlink all
    # unlinks all sensor registration frames from a MAC address
    def __unlink_all(self):
        files = list(self.__path.glob('*.json'))
        for i in files:
            with i.open() as f:
                frame = json.load(f)
                if("".join("{:02x}".format(c) for c in frame['source_addr_long']) == self.__mac and
                    frame['rf_data'][0] == 3):
                    i.unlink()

    # --------------------------------------------------------------------------
    # SENSOR REGISTRATION
    # --------------------------------------------------------------------------
    # fired when sensor starts up
    # routine:
    #   check DB
    #   chekc istSOS
    #   register
    #   return response to sensor
    def __sensor_boot(self): # TODO make private after debug
        # get MAC
        self.__mac = "".join("{:02x}".format(c) for c in self.__frame['source_addr_long'])
        # check db for MAC
        cur = self.__conn.cursor()
        cur.execute("SELECT MAC FROM sensor")
        macs = cur.fetchall()
        for i in macs:
            if(self.__mac == i[0]):
                logging.debug('sensor was registered')
                self.__unlink_all()
                self.__comm.send([self.__frame['source_addr_long'], self.__frame['source_addr']], dest=0, tag=tags.GO)

                return

        # not registered!
        self.__read_obs()
        self.__xml_process_sensor()
        self.__insert_sensor()
        self.__unlink_all()

        # sensor is a go!
        self.__comm.send([self.__frame['source_addr_long'], self.__frame['source_addr']], dest=0, tag=tags.GO)

        # TODO delete all files here and raise?
        # clear the dict and the xml
        self.__xml_dict = {}
        self.__xml = str()
        self.__observed_properties = []

    # --------------------------------------------------------------------------
    # get_serial
    # gets the next value for the same sensor
    # double checks the mac address of all the procedures
    # to verify no double registration on same service TODO is this usefull?
    def __get_serial(self):
        # set serial to 1
        serial = 1

        # open SOS connection:
        sos = SensorObservationService(self.__url)
        # for all offerings
        for i in range(len(sos.offerings)):
            for j in range(len(sos.offerings[i].procedures)):
                # FIXME istsos doing weird things again...
                # procedure = sos.offerings[i].procedures[j]
                # outputFormat = 'text/xml;subtype="sensorML/1.0.1"'
                # sensor = SensorML(sos.describe_sensor(procedure=procedure, outputFormat=outputFormat))
                # sensor = sensor.members[0]
                #
                # # check for MAC
                # # try:
                # #     mac = sensor.identifiers['macID']
                # #     if(mac.value == self.__mac):
                # #         print('Sensor allready registed on service!')
                # #         # TODO what happens here....
                # # except:
                # #     continue
                #
                # # chekc name for type
                # if(sensor.name.split('-')[0] == self.__xml_dict['sensor_type']):
                serial += 1

        # set self serial
        self.__xml_dict['serial'] = serial

    # --------------------------------------------------------------------------
    # gets the observation properties
    # from a sensor registration.
    def __read_obs(self):
        # get itterate over all files in
        # the directory for this mac
        files = list(self.__path.glob('*.json'))
        running = True
        while running: # break only when done...
            for i in files:
                with i.open() as f:
                    frame = json.load(f)
                    if("".join("{:02x}".format(c) for c in frame['source_addr_long']) == self.__mac and    # check for mac, register and the right frame
                        frame['rf_data'][0] == 3 and
                        frame['rf_data'][1] == self.__frame_id): # read preliminary
                            if(self.__frame_id == 1): # TODO store in dict....
                                # get procedure type:
                                system_type = str()
                                if(frame['rf_data'][2] == 1):
                                    system_type  = 'insitu-fixed-point'
                                elif(frame['rf_data'][2] == 2):
                                    system_type  = 'insitu-mobile-point'
                                else:
                                    system_type = 'virtual'

                                self.__xml_dict['system_type'] = system_type
                                self.__xml_dict['no_obs'] = frame['rf_data'][3] + 1 # +1 for time!

                                # read the sensor name
                                info = "".join(chr(x) for x in frame['rf_data']).split(';')[1:]
                                self.__xml_dict['sensor_type'] = info.pop(0)

                                # check if we need more frames...
                                if(info[-1][0] == '\x00'):
                                    # place time first!
                                    name = 'Time'
                                    urn = 'urn:ogc:def:parameter:x-istsos:1.0:time:iso8601'
                                    uom = 'iso8601'
                                    size = '4'
                                    self.__observed_properties = np.array([name, urn, uom, size],ndmin=2)
                                    for i in info[:-1]:
                                        self.__append_observation(i)
                                    running = False
                                else: # increment to more frames
                                    self.__frame_id += 1
                            else:
                                # make sure to 'stich' the last entry
                                lastEntry = info.pop()
                                newEntries = "".join(char(x) for x in frame['rf_data']).split(';')[1:]
                                newEntries[0] = lasteEntry + newEntries[0]
                                info.append(newEntries)

                                # check for all, or redo once more
                                if(info[-1][0] == '\x00'):
                                    # place time first!
                                    name = 'Time'
                                    urn = 'urn:ogc:def:parameter:x-istsos:1.0:time:iso8601'
                                    uom = 'iso8601'
                                    self.__observed_properties = np.array([name, urn, uom, '4'],ndmin=2)
                                    for i in info[:-1]:
                                        self.__append_observation(i)
                                    running = False
                                else: # increment to more frames
                                    self.__frame_id += 1

    # --------------------------------------------------------------------------
    # appends the observations string
    # to self.__observed_properties
    # obs_str is the string object from the sensor
    def __append_observation(self, obs_str):
        name = obs_str.split(':')[1]
        uom = obs_str.split(':')[0]
        urn = 'urn:ogc:def:parameter:x-istsos:1.0:' + obs_str.split(':')[0] + ':' + obs_str.split(':')[1] # TODO not nice
        size = obs_str.split(':')[2]
        self.__observed_properties = np.vstack((self.__observed_properties, np.array([name, urn, uom, size], ndmin=2)))

    # --------------------------------------------------------------------------
    # SQL DATA INSERTION
    # --------------------------------------------------------------------------
    def __insert_sensor(self):
        # insert the sensor
        cur = self.__conn.cursor()
        procedure = 'urn:ogc:def:procedure:x-istsos:1.0:'+self.__xml_dict['sensor_type'] + '-' + str(self.__xml_dict['serial'])
        foi = 'urn:ogc:def:feature:x-istsos:1.0:Point:'+self.__xml_dict['foi_name']
        cur.execute("INSERT INTO sensor VALUES ('{0}','{1}','{2}','{3}')".format(self.__mac, procedure, foi, self.__uid))
        self.__conn.commit()
        cur.close()

        # insert properties - takes care of nm relationship too
        self.__insert_properties()

    def __insert_properties(self):
        cur = self.__conn.cursor()

        # see if we have new observables
        for i in range(self.__observed_properties.shape[0]):
            cur.execute("SELECT * FROM observed_property WHERE URN = '{0}'".format(self.__observed_properties[i,1]))
            if len(cur.fetchall()) > 0:
                continue
            else:
                cur.execute("INSERT INTO observed_property(name, URN, UOM, size) VALUES ('{0}','{1}','{2}',{3})".format(*self.__observed_properties[i,:]))
                self.__conn.commit()

        # inserted everything, now create sensor to observation relationship, row order from list
        for i in range(self.__observed_properties.shape[0]):
            cur.execute("SELECT ID FROM observed_property WHERE URN = '{0}'".format(self.__observed_properties[i,1]))
            propertyID = cur.fetchone()[0]
            cur.execute("INSERT INTO sensor_property VALUES ('{0}', {1}, {2})".format(self.__mac, propertyID, i))
            self.__conn.commit()

        cur.close()

    # --------------------------------------------------------------------------
    # XML CREATION - DATA
    # --------------------------------------------------------------------------
    # make composite_phenomenon
    # makes the xml block for the phenomenon, needs dict{count:, body:}
    def __make_composite_phenomenon(self):
        phenomenon = {'count': self.__observed_properties.shape[0]} # number of rows
        body = str()
        for i in range(phenomenon['count']):
            body = body + '<swe:component xlink:href="{0}"/>'.format(self.__observed_properties[i,1]) + "\n"

        phenomenon['body'] = body
        self.__xml_dict['composite_phenomenon'] = open('./resources/xml/composite_phenomenon.xml').read().format(**phenomenon)

    # --------------------------------------------------------------------------
    # makes the xml data array header
    # takes a dict{count:, body:}, where body can be with or without UOM? needs UOM?
    def __make_data_array_header(self, register=False):
        header = {'count': self.__observed_properties.shape[0]}
        body = str()
        for i in range(header['count']):
            body_dict = {'name': self.__observed_properties[i,0], 'urn': self.__observed_properties[i,1], 'uom':self.__observed_properties[i,2]}

            # check what body to take
            if body_dict['uom'] == None:
                body = body + open('./resources/xml/no_uom_field.xml').read().format(**body_dict)
            else:
                body = body + open('./resources/xml/uom_field.xml').read().format(**body_dict)

        header['body'] = body
        if register:
            self.__xml_dict['data_array_inner'] = body

        self.__xml_dict['data_array_header'] = open('./resources/xml/data_array_header.xml').read().format(**header)

    # --------------------------------------------------------------------------
    # __get_data
    # gets the data from the server for all properties and the given time frame
    # the tricky bit is getting the order right...
    # since the properties are ordered by ID, ordering data by time and property_ID
    # this should be reshapable... TODO: test it
    def __get_data(self):
        cur = self.__conn.cursor()
        cur.execute(open('./resources/sql/get_data.sql').read().format(**self.__xml_dict))
        data = cur.fetchall()
        try:
            data = np.array(data, ndmin=2).reshape(int(self.__check_table[0,1]), (self.__observed_properties.shape[0])-1) # 1.is count, 2. is properties - time
        except:
            logging.warning('weird data array')
            logging.warning(data)

        # get time stamps accordingly
        cur.execute(open('./resources/sql/get_time.sql').read().format(**self.__xml_dict))
        time = cur.fetchall()
        times = []
        for i in time:
            times.append(i[0] + "Z")

        time = np.array(times, ndmin=2).reshape(int(self.__check_table[0,1]), 1)

        data = np.hstack((time, data))
        xml_string = np.array2string(data, separator=',')
        repls = (' ' , ''),('[', ''),('],', ';'),('\'', ''),('\n', '')
        xml_string = reduce(lambda a, kv: a.replace(*kv), repls, xml_string)
        self.__xml_dict['data'] = xml_string[:-2]

    # --------------------------------------------------------------------------
    # __xml_process
    # triggered when an istSOS insert should happen
    def __xml_process_data(self):
        # get the top of the check table, sensor with moth values
        cur = self.__conn.cursor()

        # TODO Update Database so sensor FOI and position are the same as on the service!
        cur.execute("SELECT * FROM sensor WHERE MAC = '{0}'".format(self.__check_table[0,0]))
        sensor = cur.fetchone()
        # assign to the xml dict
        self.__xml_dict['mac'] = sensor[0]          # 0 is Mac, we need it as internal PK
        self.__xml_dict['id'] = sensor[3]           # 3rd Col: UUID
        self.__xml_dict['procedure'] = sensor[1]    # 1st col: URN
        self.__xml_dict['foi'] = sensor[2]          # 2nd col: FOI URN
        self.__xml_dict['begin'] = self.__check_table[0,2] # third cell is oldest
        self.__xml_dict['end'] = self.__check_table[0,3]   # fourth cell is newest

        # get properties
        query = open('./resources/sql/get_observed_property.sql').read()
        cur.execute(query.format(self.__xml_dict['mac']))
        self.__observed_properties = np.array(cur.fetchall())
        cur.close()

        # Make xml strings
        self.__make_composite_phenomenon()
        self.__make_data_array_header()
        self.__get_data()
        self.__xml = open('./resources/xml/main.xml').read().format(**self.__xml_dict)

        # TODO handle response
        response = http_post(self.__url, self.__xml)
        print(response)
        self.__last_insert = datetime.now()

        # delete inserted data locally
        cur = self.__conn.cursor()
        notDelete = True
        while notDelete:
            try:
                cur.execute(open('./resources/sql/delete_inserted.sql').read().format(**self.__xml_dict))
                notDelte = False
            except:
                sleep(1)

        self.__conn.commit()
        cur.close()

        # clear the dict and the xml
        self.__xml_dict = {}
        self.__xml = str()
        self.__observed_properties = []

    # --------------------------------------------------------------------------
    # XML CREATION - REGISTER SENSOR TODO
    # --------------------------------------------------------------------------
    def __xml_process_sensor(self):
        self.__xml_dict['mac'] = self.__mac
        self.__xml_dict['count'] = self.__observed_properties.shape[0]

        # TODO set this to be something from GeoServer or what ever... hard coded
        self.__xml_dict['foi_name'] = 'default'
        self.__xml_dict['epsg'] = 4326 # set to WGS84

        # make the other parameters
        self.__make_data_array_header(True)
        self.__make_composite_phenomenon()
        self.__get_serial()

        # all set! register this!
        self.__xml = open('./resources/xml/insert_sensor_main.xml').read().format(**self.__xml_dict)
        response = http_post(self.__url, self.__xml)
        self.__parse_rs(response)

    # --------------------------------------------------------------------------
    # RESPONSE HANDLING TODO, make PRIVATE after debug
    # --------------------------------------------------------------------------
    # parse_rs
    # parse the register sensor response and add the uuid to the sqlite DB
    def __parse_rs(self, response):
        tree = ET.fromstring(response)
        uid = tree.find('AssignedSensorId')
        self.__uid = uid.text.split(':')[-1]
        return

    # --------------------------------------------------------------------------
    # parse_io
    # just a small check to make sure the obervations were entered.
    # not sure if this should also do error handling, or we want to do that in the
    # routine. TODO
    def parse_io(self, response):
        return(NULL)

    # --------------------------------------------------------------------------
    # ROUTINE
    # --------------------------------------------------------------------------
    def routine(self):
        while True:
            try:
                self.__check()
                # we got something
                if(self.__check_table.size > 0):
                    # oldest = datetime.strptime(str(self.__check_table[0,2]), '%Y-%m-%dT%H:%M:%S.%f') # TODO
                    if(int(self.__check_table[0,1]) > self.__max_count or (datetime.utcnow() - self.__last_insert).seconds > self.__max_time):
                        self.__xml_process_data()
                else:
                    time.sleep(5) # take a 5 second nap
            except KeyboardInterrupt:
                break
