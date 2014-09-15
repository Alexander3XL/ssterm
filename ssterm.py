#!/usr/bin/env python2

# ssterm - simple serial-port terminal
# Version 1.8 - September 2014
# Vanya A. Sergeev - <vsergeev@gmail.com>
# https://github.com/vsergeev/ssterm
#
# Copyright (C) 2007-2014 Vanya A. Sergeev
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import sys
import os
import termios
import select
import errno
import getopt
import re
import string

###########################################################################
### Default Options
###########################################################################

# Default TTY Options
TTY_Options = {
                'baudrate': 115200,
                'databits': 8,
                'stopbits': 1,
                'parity': "none",
                'flow_control': "none"
            }

# Default Formatting Options
Format_Options = {
                'output_mode': 'raw',   # 'split', 'splitfull', 'hex', 'hexnl'
                'input_mode': 'raw',    # 'hex'
                'transmit_newline': "raw",
                'receive_newline': "raw",
                'echo': False
            }

# Default color coded characters, e.g. { ord('\n'), ord('A') }
Color_Chars = {}

# Number of columns in hexadecimal print mode
Hexadecimal_Columns = 16

# Quit Escape Character, Ctrl-] = 0x1D
Quit_Escape_Character = 0x1D

# Default color codes:
#   Black/Red, Black/Green, Black/Yellow,
#   White/Blue, White/Magenta, Black/Cyan,
#   Black/White
Color_Codes = [ "\x1b[1;30;41m", "\x1b[1;30;42m", "\x1b[1;30;43m",
                "\x1b[1;37;44m", "\x1b[1;37;45m", "\x1b[1;30;46m",
                "\x1b[1;30;47m"]
Color_Code_Reset = "\x1b[0m"

# Read buffer size
READ_BUFF_SIZE = 4096

###########################################################################
### Program Constants
###########################################################################

# Console Newline
Console_Newline = os.linesep

# Newline Substitution tables
RX_Newline_Sub = {'raw': None, 'cr': "\r", 'crlf': "\r\n", 'lf': "\n", 'crorlf': "\r|\n"}
TX_Newline_Sub = {'raw': None, 'cr': "\r", 'crlf': "\r\n", 'lf': "\n", 'none': ""}

###########################################################################
### Serial Helper Functions
###########################################################################

def serial_open(device_path, baudrate, databits, stopbits, parity, flow_control):
    # Open the tty device
    try:
        fd = os.open(device_path, os.O_RDWR | os.O_NOCTTY)
    except OSError as err:
        raise Exception("%s" % str(err))

    # Get current termios attributes
    #   [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
    try:
        tty_attr = termios.tcgetattr(fd)
    except termios.error as err:
        raise Exception("Getting serial port options: %s" % str(err))

    ######################################################################
    ### cflag, ispeed, ospeed
    ######################################################################

    # Reset cflag: Enable receiver, ignore modem control lines
    tty_attr[2] = (termios.CREAD | termios.CLOCAL)

    # Look up the termios baudrate and set it in the attributes structure
    #   tty_attr[cflag], tty_attr[ispeed], tty_attr[ospeed]
    termios_baudrates = {
        50: termios.B50, 75: termios.B75, 110: termios.B110, 134: termios.B134,
        150: termios.B150, 200: termios.B200, 300: termios.B300,
        600: termios.B600, 1200: termios.B1200, 1800: termios.B1800,
        2400: termios.B2400, 4800: termios.B4800, 9600: termios.B9600,
        19200: termios.B19200, 38400: termios.B38400, 57600: termios.B57600,
        115200: termios.B115200, 230400: termios.B230400,
        # Linux baudrates bits missing in termios module included below
        460800: 0x1004, 500000: 0x1005, 576000: 0x1006,
        921600: 0x1007, 1000000: 0x1008, 1152000: 0x1009,
        1500000: 0x100A, 2000000: 0x100B, 2500000: 0x100C,
        3000000: 0x100D, 3500000: 0x100E, 4000000: 0x100F,
    }

    if baudrate in termios_baudrates:
        tty_attr[2] |= termios_baudrates[baudrate]
        tty_attr[4] = termios_baudrates[baudrate]
        tty_attr[5] = termios_baudrates[baudrate]
    else:
        # Set alternate speed via BOTHER (=0x1000) cflag,
        # Pass baudrate directly in ispeed, ospeed
        tty_attr[2] |= 0x1000
        tty_attr[4] = baudrate
        tty_attr[5] = baudrate

    # Look up and set the appropriate cflag bits in termios_options for a given
    # option
    def termios_cflag_map_and_set(termios_options, option, errmsg):
        if not option in termios_options:
            raise ValueError(errmsg)
        tty_attr[2] |= termios_options[option]

    # Look up the termios data bits and set it in the attributes structure
    termios_databits = {5: termios.CS5, 6: termios.CS6, 7: termios.CS7, 8: termios.CS8}
    termios_cflag_map_and_set(termios_databits, databits, "Invalid tty databits!")
    # Look up the termios parity and set it in the attributes structure
    termios_parity = {"none": 0, "even": termios.PARENB, "odd": termios.PARENB | termios.PARODD}
    termios_cflag_map_and_set(termios_parity, parity, "Invalid tty parity!")
    # Look up the termios stop bits and set it in the attributes structure
    termios_stopbits = {1: 0, 2: termios.CSTOPB}
    termios_cflag_map_and_set(termios_stopbits, stopbits, "Invalid tty stop bits!")
    # Look up the termios flow control and set it in the attributes structure
    termios_flowcontrol = {"none": 0, "rtscts": termios.CRTSCTS, "xonxoff": 0}
    termios_cflag_map_and_set(termios_flowcontrol, flow_control, "Invalid tty flow control!")

    ######################################################################
    ### lflag
    ######################################################################

    # Turn off signals generated for special characters, turn off canonical
    # mode so we can have raw input -- tty_attr[lflag]
    tty_attr[3] = 0

    ######################################################################
    ### oflag
    ######################################################################

    # Turn off POSIX defined output processing and character mapping/delays
    # so we can have raw output -- tty_attr[oflag]
    tty_attr[1] = 0

    ######################################################################
    ### iflag
    ######################################################################

    # Ignore break characters -- tty_attr[iflag]
    tty_attr[0] = termios.IGNBRK
    # Enable parity checking if we are using parity -- tty_attr[iflag]
    if parity != "none":
        tty_attr[0] |= (termios.INPCK | termios.ISTRIP)
    # Enable XON/XOFF if we are using software flow control
    if flow_control == "xonxoff":
        tty_attr[0] |= (termios.IXON | termios.IXOFF | termios.IXANY)

    # Set new termios attributes
    try:
        termios.tcsetattr(fd, termios.TCSANOW, tty_attr)
    except termios.error as err:
        raise Exception("Setting serial port options: %s" % str(err))

    # Return the fd
    return fd

def serial_close(fd):
    os.close(fd)

###########################################################################
### TTY Helper Functions
###########################################################################

def stdin_raw_open(echo):
    fd = sys.stdin.fileno()

    # Get the current stdin tty options
    #   [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
    try:
        stdin_attr = termios.tcgetattr(fd)
    except termios.error as err:
        raise Exception("Getting stdin tty options: %s" % str(err))

    # Disable canonical input, so we can send characters without a line
    # feed, disable signal interpretation, and disable echo
    # -- stdin_attr[cflag]
    stdin_attr[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHOE | termios.ISIG)

    # Enable echo if needed
    if echo:
        stdin_attr[3] |= termios.ECHO

    # Turn off XON/XOFF interpretation so they pass through to the serial
    # port -- stdin_attr[iflag]
    stdin_attr[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)

    # Set the new stdin tty attributes
    try:
        termios.tcsetattr(fd, termios.TCSANOW, stdin_attr)
    except termios.error as err:
        raise Exception("Setting stdin tty options: %s" % str(err))

    return fd

def stdout_raw_open():
    # Re-open stdout in unbuffered mode
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

    return sys.stdout.fileno()

def stdin_reset():
    fd = sys.stdin.fileno()

    # Reset stdin terminal for canonical input, echo, and signals

    # Get the current stdin tty options
    #   [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
    try:
        stdin_attr = termios.tcgetattr(fd)
    except termios.error as err:
        raise Exception("Getting stdin tty options: %s" % str(err))

    # Enable canonical input, echo, signals -- stdin_attr[cflag]
    stdin_attr[3] |= (termios.ICANON | termios.ECHO | termios.ECHOE | termios.ISIG)

    # Re-enable XON/XOFF interpretation -- stdin_attr[iflag]
    stdin_attr[0] |= (termios.IXON | termios.IXOFF | termios.IXANY)

    # Set the new stdin tty attributes
    try:
        termios.tcsetattr(fd, termios.TCSANOW, stdin_attr)
    except termios.error as err:
        raise Exception("Setting stdin tty options: %s" % str(err))

###########################################################################
### fd read and write
###########################################################################

def fd_read(fd, n):
    return os.read(fd, n)

def fd_write(fd, data):
    return os.write(fd, data)

###########################################################################
### Receive and transmit newline substitutions
###########################################################################

def format_tx_nlsub(data, sub):
    # Substitute console newlines in data with 'sub'

    # FIXME: This assumes a single character platform newline.
    data = ''.join([sub if x == Console_Newline else x for x in data])

    return data

# State used by format_tx_hex
txhex_state = ""
def format_tx_hex(data):
    global txhex_state

    hex_data = ""
    for x in data:
        if x in string.hexdigits:
            txhex_state += x
        # Reset our state if we encounter a none hex character
        else:
            txhex_state = ""

        # Convert 2 consecutive hex characters
        if len(txhex_state) == 2:
            hex_data += chr(int(txhex_state, 16))
            txhex_state = ""

    return hex_data

# State used by format_rx_nlsub
rxnl_state = ""
def format_rx_nlsub(data, match):
    global rxnl_state

    # Substitute 'match' in data with console newline

    # Append left-over newline character match from before
    data = rxnl_state + data
    rxnl_state = ""

    # Substitute newline matches with console newline
    data = re.sub(match, Console_Newline, data)

    # If the last character is a part of a match, save it for later
    if data[-1] == match[0][0]:
        rxnl_state = data[-1]
        data = data[0:-1]

    return data

###########################################################################
### Formatted Print
###########################################################################

def format_print_raw(stdout_fd, data):
    if len(Color_Chars) == 0:
        fd_write(stdout_fd, data)
    else:
        # Unfortunately, for generality, we can't do a global
        # regex substitution on data with the color-coded
        # version, since we could have potentially selected
        # color code characters that are present in the ANSI
        # color escape sequences. So we operate on the data
        # a char at time here.
        for x in data:
            # Color code this character if it's in our color chars dictionary
            if ord(x) in Color_Chars:
                fd_write(stdout_fd, Color_Codes[Color_Chars[ord(x)]] + x + Color_Code_Reset)
            else:
                fd_write(stdout_fd, x)

# State used by format_print_hexadecimal
stdout_cursor_x = 0
def format_print_hexadecimal(stdout_fd, data, interpret_newlines=False):
    global stdout_cursor_x

    for x in data:
        # Color code this character if it's in our color chars dictionary
        if len(Color_Chars) > 0 and ord(x) in Color_Chars:
            fd_write(stdout_fd, Color_Codes[Color_Chars[ord(x)]] + ("%02x" % ord(x)) + Color_Code_Reset)
        else:
            fd_write(stdout_fd, "%02x" % ord(x))
        stdout_cursor_x += 1

        # Pretty print into two columns
        if stdout_cursor_x == Hexadecimal_Columns/2:
            fd_write(stdout_fd, "  ")
        elif stdout_cursor_x == Hexadecimal_Columns:
            fd_write(stdout_fd, "\n")
            stdout_cursor_x = 0
        else:
            fd_write(stdout_fd, " ")

        # Insert a newline if we encounter one and we're interpreting them
        # FIXME: This assumes a single character platform newline.
        if x == Console_Newline and interpret_newlines:
            fd_write(stdout_fd, Console_Newline)
            stdout_cursor_x = 0

def format_print_hexadecimal_newline(stdout_fd, data):
    format_print_hexadecimal(stdout_fd, data, interpret_newlines=True)

# State used by format_print_split
stdout_split_bytes = []
def format_print_split(stdout_fd, data, partial_print=True):
    global stdout_split_bytes

    # Erase partially completed strings with \r
    if partial_print:
        if len(stdout_split_bytes) > 0:
            fd_write(stdout_fd, "\r")

    def split_print(byte_list):
        # split_print() expects:
        # 1 <= len(byte_list) <= Hexadecimal_Columns

        # Print the hexadecimal representation
        for i in range(len(byte_list)):
            # Color code this character if it's in our color chars dictionary
            if len(Color_Chars) > 0 and ord(byte_list[i]) in Color_Chars:
                fd_write(stdout_fd, Color_Codes[Color_Chars[ord(byte_list[i])]] + ("%02x" % ord(byte_list[i])) + Color_Code_Reset)
            else:
                fd_write(stdout_fd, "%02x" % ord(byte_list[i]))

            # Pretty print into two columns
            if (i+1) == Hexadecimal_Columns/2:
                fd_write(stdout_fd, "  ")
            else:
                fd_write(stdout_fd, " ")

        # Fill up the rest of the hexadecimal representation
        # with blank space
        if len(byte_list) < Hexadecimal_Columns/2:
            # Account for the pretty print column separator
            fd_write(stdout_fd, " " + " "*(3*(Hexadecimal_Columns-len(byte_list))))
        elif len(byte_list) < Hexadecimal_Columns:
            fd_write(stdout_fd, " "*(3*(Hexadecimal_Columns-len(byte_list))))

        # Print the ASCII representation
        fd_write(stdout_fd, " |")
        for i in range(len(byte_list)):
            # Use the character if it's an ASCII printable
            # character, otherwise use a dot
            if byte_list[i] in string.letters+string.digits+string.punctuation+' ':
                c = byte_list[i]
            else:
                c = "."
            # Color code this character if it's in our
            # color chars dictionary
            if len(Color_Chars) > 0 and ord(byte_list[i]) in Color_Chars:
                fd_write(stdout_fd, Color_Codes[Color_Chars[ord(byte_list[i])]] + c + Color_Code_Reset)
            else:
                fd_write(stdout_fd, c)
        fd_write(stdout_fd, "|")

    for x in data:
        # Add to our split byte window
        stdout_split_bytes.append(x)
        # If we get a full column window, print it out with a
        # newline
        if len(stdout_split_bytes) == Hexadecimal_Columns:
            split_print(stdout_split_bytes)
            fd_write(stdout_fd, Console_Newline)
            stdout_split_bytes = []

    # Print partially completed strings
    if partial_print:
        # Print out any bytes left in our window
        if len(stdout_split_bytes) > 0:
            split_print(stdout_split_bytes)

def format_print_split_full_lines(stdout_fd, data):
    format_print_split(stdout_fd, data, partial_print=False)

###########################################################################
### Main Read/Write Loop
###########################################################################

def read_write_loop(serial_fd, stdin_fd, stdout_fd):
    # Look up our formatting options
    txnl_sub = TX_Newline_Sub[Format_Options['transmit_newline']]
    rxnl_sub = RX_Newline_Sub[Format_Options['receive_newline']]
    input_mode = Format_Options['input_mode']
    format_print = {
            'raw': format_print_raw,
            'split': format_print_split,
            'splitfull': format_print_split_full_lines,
            'hex': format_print_hexadecimal,
            'hexnl': format_print_hexadecimal_newline,
        }[Format_Options['output_mode']]

    # Select between serial port and stdin file descriptors
    read_fds = [serial_fd, stdin_fd]

    while True:
        ready_read_fds, _, _ = select.select(read_fds, [], [])

        if stdin_fd in ready_read_fds:
            # Read a buffer from stdin
            try:
                buff = fd_read(stdin_fd, READ_BUFF_SIZE)
            except Exception as err:
                raise Exception("Error reading stdin: %s\n" % str(err))

            # Process and write the buffer to the serial port
            if buff and len(buff) > 0:
                # If we detect the escape character, then quit
                if chr(Quit_Escape_Character) in buff:
                    break

                # Perform transmit newline subsitutions
                if txnl_sub != None:
                    buff = format_tx_nlsub(buff, txnl_sub)

                # Perform hexadecimal interpretation
                if input_mode == 'hex':
                    buff = format_tx_hex(buff)

                # Write the buffer to the serial port
                try:
                    fd_write(serial_fd, buff)
                except Exception as err:
                    raise Exception("Error writing to serial port: %s\n" % str(err))

        if serial_fd in ready_read_fds:
            # Read a buffer from the serial port
            try:
                buff = fd_read(serial_fd, READ_BUFF_SIZE)
            except Exception as err:
                raise Exception("Error reading serial port: %s\n" % str(err))

            # Format and print the buffer to the console
            if buff and len(buff) > 0:
                # Perform receive newline substitutions
                if rxnl_sub != None:
                    buff = format_rx_nlsub(buff, rxnl_sub)

                # Print to stdout
                try:
                    format_print(stdout_fd, buff)
                except Exception as err:
                    raise Exception("Error writing to stdout: %s\n" % str(err))

###########################################################################
### Help and Command-Line Options Parsing
###########################################################################

def print_usage():
    print "Usage: %s [options] <serial port device>\n" % sys.argv[0]
    print "\
ssterm - simple serial-port terminal v1.8\n\
Vanya A. Sergeev - <vsergeev@gmail.com>\n\
https://github.com/vsergeev/ssterm\n\
\n\
Serial Port Options:\n\
  -b, --baudrate <rate>         Specify baudrate (e.g. 9600, 115200, etc.)\n\
  -d, --databits <number>       Specify number of data bits [5,6,7,8]\n\
  -p, --parity <type>           Specify parity [none, odd, even]\n\
  -t, --stopbits <number>       Specify number of stop bits [1,2]\n\
  -f, --flow-control <type>     Specify flow-control [none, rtscts, xonxoff]\n\
\n\
Output Formatting Options:\n\
  -o, --output <mode>           Specify output mode\n\
                                  raw       raw (default)\n\
                                  split     hex./ASCII split\n\
                                  splitfull hex./ASCII split with full lines\n\
                                  hex       hex.\n\
                                  hexnl     hex. with newlines\n\
\n\
  --rx-nl <substitution>        Enable receive newline substitution\n\
                                  [raw, cr, lf, crlf, crorlf]\n\
\n\
  -c, --color <list>            Specify comma-delimited list of characters in\n\
                                  ASCII or hex. to color code: A,$,0x0d,0x0a,...\n\
\n\
Input Formatting Options:\n\
  -i, --input <mode>            Specify input mode\n\
                                  raw       raw (default)\n\
                                  hex       hex. interpretaion\n\
\n\
  --tx-nl <substitution>        Enable transmit newline substitution\n\
                                  [raw, none, cr, lf, crlf]\n\
\n\
  -e, --echo                    Enable local character echo\n\
\n\
Miscellaneous:\n\
  -h, --help                    Display this usage/help\n\
  -v, --version                 Display the program's version\n\n"
    print "\
Quit Escape Character:          Ctrl-]\n\
\n\
Default Options:\n\
 baudrate: 115200 | databits: 8 | parity: none | stopbits: 1 | flowctrl: none\n\
 output mode: raw | rx newline: raw | color code: off\n\
 input mode: raw  | tx newline: raw | local echo: off\n"

def print_version():
    print "ssterm version 1.8 - 09/13/2014"

if __name__ == '__main__':
    # Parse options
    try:
        options, args = getopt.gnu_getopt(sys.argv[1:], "b:d:p:t:f:o:c:i:ehv", ["baudrate=", "databits=", "parity=", "stopbits=", "flow-control=", "output=", "color=", "rx-nl=", "input=", "tx-nl=", "echo", "help", "version"])
    except getopt.GetoptError, err:
        print str(err), "\n"
        print_usage()
        sys.exit(-1)

    # Update options containers
    for opt_c, opt_arg in options:
        # Serial port options
        if opt_c in ("-b", "--baudrate"):
            try:
                TTY_Options['baudrate'] = int(opt_arg, 10)
            except ValueError:
                sys.stderr.write("Error: Invalid tty baudrate!\n")
                sys.exit(-1)
        elif opt_c in ("-d", "--databits"):
            try:
                TTY_Options['databits'] = int(opt_arg, 10)
            except ValueError:
                sys.stderr.write("Error: Invalid tty data bits!\n")
                sys.exit(-1)
        elif opt_c in ("-p", "--parity"):
            TTY_Options['parity'] = opt_arg
        elif opt_c in ("-t", "--stopbits"):
            try:
                TTY_Options['stopbits'] = int(opt_arg, 10)
            except ValueError:
                sys.stderr.write("Error: Invalid tty stop bits!\n")
                sys.exit(-1)
        elif opt_c in ("-f", "--flow-control"):
            TTY_Options['flow_control'] = opt_arg

        # Output Formatting Options
        elif opt_c in ("-o", "--output"):
            if not opt_arg in ["raw", "split", "splitfull", "hex", "hexnl"]:
                sys.stderr.write("Error: Invalid output mode!\n")
                print_usage()
                sys.exit(-1)
            Format_Options['output_mode'] = opt_arg
        elif opt_c == "--tx-nl":
            if not opt_arg in TX_Newline_Sub:
                sys.stderr.write("Error: Invalid tx newline type!\n")
                print_usage()
                sys.exit(-1)
            Format_Options['transmit_newline'] = opt_arg
        elif opt_c in ("-c", "--color"):
            opt_arg = filter(lambda x: len(x) >= 1, opt_arg.split(","))
            if len(opt_arg) > len(Color_Codes):
                sys.stderr.write("Error: Maximum color code characters (%d) exceeded!\n" % len(Color_Codes))
                sys.exit(-1)
            # Parse ASCII and hex encoded characters into our Color_Chars dictionary
            for c in opt_arg:
                # ASCII character
                if len(c) == 1:
                    Color_Chars[ord(c)] = len(Color_Chars)
                # Hexadecimal number
                elif len(c) > 2 and c[0:2] == "0x":
                    try:
                        c_int = int(c, 16)
                    except ValueError:
                        sys.stderr.write("Error: Unknown color code character: %s\n" % c)
                        sys.exit(-1)
                    Color_Chars[c_int] = len(Color_Chars)
                # Unknown
                else:
                    sys.stderr.write("Error: Unknown color code character: %s\n" % c)
                    sys.exit(-1)

        # Input Formatting Options
        elif opt_c in ("-i", "--input"):
            if not opt_arg in ["raw", "hex"]:
                sys.stderr.write("Error: Invalid input mode!\n")
                print_usage()
                sys.exit(-1)
            Format_Options['input_mode'] = opt_arg
        elif opt_c == "--rx-nl":
            if not opt_arg in RX_Newline_Sub:
                sys.stderr.write("Error: Invalid rx newline type!\n")
                print_usage()
                sys.exit(-1)
            Format_Options['receive_newline'] = opt_arg
        elif opt_c in ("-e", "--echo"):
            Format_Options['echo'] = True

        # Miscellaneous Options
        elif opt_c in ("-h", "--help"):
            print_usage()
            sys.exit(0)
        elif opt_c in ("-v", "--version"):
            print_version()
            sys.exit(0)

    # Make sure a serial port device is specified
    if len(args) < 1:
        print_usage()
        sys.exit(-1)

    # Open the serial port with our options
    try:
        serial_fd = serial_open(args[0], TTY_Options['baudrate'], TTY_Options['databits'], TTY_Options['stopbits'], TTY_Options['parity'], TTY_Options['flow_control'])
    except Exception as err:
        sys.stderr.write("Error opening serial port: %s\n" % str(err))
        sys.exit(-1)

    # Open stdin in raw mode
    try:
        stdin_fd = stdin_raw_open(Format_Options['echo'])
    except Exception as err:
        sys.stderr.write("Error opening stdin in raw mode: %s\n" % str(err))
        sys.exit(-1)

    # Open stdout in raw mode
    try:
        stdout_fd = stdout_raw_open()
    except Exception as err:
        sys.stderr.write("Error opening stdout in raw mode: %s\n" % str(err))
        sys.exit(-1)

    try:
        read_write_loop(serial_fd, stdin_fd, stdout_fd)
    except Exception as err:
        sys.stderr.write("%s\n" % str(err))
        sys.exit(-1)

    print ""

    # Reset our console to buffered mode
    try:
        stdin_reset()
    except Exception as err:
        sys.stderr.write("Error resetting stdin to buffered mode: %s\n" % str(err))
        sys.exit(-1)

    # Close the serial port
    try:
        serial_close(serial_fd)
    except Exception as err:
        sys.stderr.write("Error closing serial port: %s\n" % str(err))
        sys.exit(-1)

