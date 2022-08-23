import argparse
import sys
import pathlib
import re
import serial
import serial.tools.list_ports_osx as ports
import time
import logging
import json
logging.basicConfig(filename='log.log', level=logging.DEBUG)

# TODOs:
#  -- for OpenDrop with integrated temp controller, ODC sends temp setting for each heating region,
#       and OD takes care of PID control directly -- MFSim should output temps for each TS to
#       set proper temps for each heater.
#  -- ODC also sends a flag for feedback (looks like to set the capacitance feedback);
#       when we get feedback-control working as expected, we should probably shove
#       instructions into a queue so that OD can still receive them and process them
#       as feedback-control finishes.

debug = False

# last electrode for each dimension of the grid (0-indexed)
X = 13
Y = 7

left_mag = False
right_mag = False


def main(cli):
    if cli.translate:
        # translate filename.mfprog file to opendrop filename.od and filename.json

        filename = cli.input.split('.')[0]

        ts_to_coords = parse_input(cli)
        ts_to_coords = translate_grid(ts_to_coords)

        # translate for uploading to OpenDropController
        json_rep = list()
        for ts, coords in ts_to_coords.items():
            this_frame = dict()
            ys = [["0"]*16 for _ in range(8)]
            for coord in coords:
                ys[coord[1]][coord[0]] = "1"
            for i, y in enumerate(ys):
                this_frame[f"y{i}"] = ''.join(y)
            this_frame['frame'] = int(ts)
            json_rep.append(this_frame)
        json.dump(json_rep, open(f"{cli.output_directory}/{filename}.json", 'w'), indent=2)

        # translate for direct serial control
        bytemap = coord_to_bytemap(ts_to_coords)
        with open(file=cli.output_directory + "/" + filename + '.od', mode="w") as outfile:
            for ts in bytemap:
                outfile.write(' '.join([str(st) for st in ts])+'\n')
    else:
        bytemap = open(file=cli.input, mode='r').readlines()

    if cli.serial_control:
        control_opendrop(bytemap)
    return 0


def control_opendrop(bytemap):
    # control data is as follows:
    '''
    BitNum  |   Target
    0           right magnet
    1           left magnet
    2-7         ?
    8           feedback flag
    9           ?
    10          temp1
    11          temp2
    12          temp3
    13-15       ?
    '''
    control_data = [0] * 16
    # setting temp1-3 to 25c, as opendrop_controller gui does the same. not sure if this is important.
    control_data[10] = 25
    control_data[11] = 25
    control_data[12] = 25

    # find OpenDrop port
    portname = ""
    for port in ports.comports():
        if port.product == "Feather M0":
            portname = port.device
            break
    if portname == "":
        exit("coulnd't find port")
    OpenDrop = serial.Serial(port=portname, baudrate=115200, timeout=5)
    time.sleep(1)
    OpenDrop.read_all()
    OpenDrop.flushInput()
    OpenDrop.flushOutput()

    # bytemap = [[0, 126, 8, 8, 126, 0, 124, 84, 92, 0, 92, 80, 124, 0, 94, 0, 0, 0]]
    # control_data = [0, 0, 0, 0, 0, 0, 0, 0, 25, 25, 25, 0, 0, 0]
    try:
        for i, byte_ts in enumerate(bytemap):
            print(f"ts: {i}")
            logging.warning(f"TS: {i}")
            transmit(byte_ts, OpenDrop, control_data)
    except KeyboardInterrupt:
        OpenDrop.close()

    OpenDrop.close()


# opendrop expects a 32-bit payload.  byte_ts(16)+control_data(16) covers this.
def transmit(byte_ts, od, control_data):
    logging.debug(f"top of transmit: {od.read_all()}")
    od.flushOutput()

    for _byte in byte_ts+control_data:
        if _byte > 255: # make sure we're not overflowing!
            logging.warning("WHOA, SLOW DOWN THERE, BUDDY!")
        # data = chr(_byte).encode()
        data = int.to_bytes(_byte, length=1, byteorder='big')
        if debug:
            print(f'sending byte {_byte}')
        logging.info(f'Sending byte: {_byte} encoded as {data}')
        od.write(data)
        time.sleep(0.001)
        got = od.readline()
        if debug:
            print(got)
        logging.info(f"Received: {got}")

    logging.debug(f"setting fluxels: {od.readlines(2)}")
    time.sleep(1)  # activate new electrode every ~1 second
    control_in = [0]*26
    for i in range(26):
        control_in[i] = od.read()
        time.sleep(0.001)
    if debug:
        print(control_in)
    logging.debug(f"bottom of transmit: {control_in}")


def coord_to_bytemap(ts_to_coords):
    bytemap = list()
    for coords in ts_to_coords.values():
        # eg.
        #  coords = [[0, 3], [0, 2], [1, 1]]
        #   should create the list [12=2^2+2^3, 2=2^1, 0, 0, 0, 0, 0, 0, ...]
        this_ts = [0]*16
        coords.sort()
        for coord in coords:
            this_ts[coord[0]] += (1 << coord[1])
        bytemap.append(this_ts)
    return bytemap


def translate_grid(ts_to_coords: dict):
    #ts_to_coords is dict of int -> set of string tuples
    # need to convert each set to list of int (list) pairs
    for ts, coords in ts_to_coords.items():
        new_coords = list()
        for coord in coords:
            x, y = int(coord[0]), int(coord[1])
            top = True if y < 4 else False
            if x < 0:  # west i/o op
                if x == -3:
                    y = 3 if top else 4
                elif x == -2:
                    y = 2 if top else 5
                elif y not in [1, 6]:
                    y = 1 if top else 6
                else:
                    y = 0 if top else 7
                x = 0
            elif x > X:  # east i/o op
                if x == X+3:
                    y = 3 if top else 4
                elif x == X+2:
                    y = 2 if top else 5
                elif y not in [1, 6]:
                    y = 1 if top else 6
                else:
                    y = 0 if top else 7
                x = X+2
            else:  # normal grid activation
                x += 1
            new_coords.append([x, y])
        ts_to_coords[ts] = new_coords
    return ts_to_coords


def parse_input(cli):
    """ pretty straightforward; we have electrode activations of the form:
       TS: <space-separated list of coords>
       where coord is simple (x,y) format.
       """
    ts_to_coords = dict()  # into to list of coords (pairs)
    with open(file=cli.input, mode="r") as infile:
        for line in infile:
            ts, rawcoords = line.strip().split(':')
            rawcoords = re.sub(r'[(]', '', rawcoords)
            if len(rawcoords) == 0:
                break
            coords = set()
            for rc in rawcoords.split(')'):  # (x1,y1)(x2,y2)...
                if len(rc) == 0:
                    break
                coords.add(tuple(x for x in rc.split(',')))
                # coords.add((tuple(int(x), int(y)) for x, y in rc.split(',')))
                # coords.append([int(x) for x in rc.split(',')])
            if int(ts) not in ts_to_coords:
                ts_to_coords[int(ts)] = coords
            else:
                ts_to_coords[int(ts)] += coords
    return ts_to_coords


if __name__ == '__main__':
    # setup cli
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-od", "--output_directory", default="Output/")
    # parser.add_argument("-o", "--output", default="activations.txt")
    parser.add_argument("-t", "--translate", default=True)
    parser.add_argument("-sc", "--serial_control", default=True)

    # parse args
    args = parser.parse_args(sys.argv[1:])

    # setup output path if it doesn't exist
    pathlib.Path(args.output_directory).mkdir(parents=True, exist_ok=True)

    main(args)
