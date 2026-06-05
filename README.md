# POLAR H10 ECG MONITORING

## CONTEXT
This script was developed for ECG and ACC data streaming to a computer for research purposes. 

Note that due to Bluetooth handling issues it currently works only on Mac and Windows. On Linux it works very haphazardly.

## SCRIPTS
### BLEAK TEST
Run this to check nearby belts. You'll need the belt name and the MAC Address (for Win and Linux) or UUID (for Mac).

### HR BELT ACCESS
This is for testing purposes only, to see what services are available. 

### CONFIG
This is a `yaml` file that contains settings. If needed, copy the belt info (name, mac address/uuid). Do not change other info. If you accidentally delete it, don't worry, there's a backup file in the `docs`.

### ONLINE WIN
This is the main script that has the following functionality:
- reads the `config.yaml` file for settings
- connects to the belt
- displays battery level information
- starts data streaming (ECG and ACC) on user interaction (press space)
- calculates timeframes for each data point
- stores data in csv files for acc and ecg
- resamples acc to match ecg data and creates a joint csv file. 
- calculates canine RR values
- stores RR and BPM in corresponding csv files

## DEVELOPER NOTES
### CONTROL POINT BYTE ARRAYS
In each byte array the first byte is the control type.

|Control type   |Code   |
|---------------|-------|
|Get settings   |0x01   |
|Start          |0x02   |
|Stop           |0x03   |

The second byte is the measurement type.

| Measurement type  | Code  | Available on H10  |
|-------------------|-------|-------------------|
|ECG                |0x00   |Yes                |
|PPG                |0x01   |No                 |
|ACC                |0x02   |Yes                |
|PPI                |0x03   |No                 |

For `get settings` and `stop` these two bytes are enough.

To start data streaming, this is the pattern:
02-00-00-01-82-00-01-01-0E-00
1--2--3--4--5--6--7--8--9--10

To break it down each byte:
1:      control (02 = start)
2:      measurement type (00 = ecg)

3:      setting id (00 = sample rate)
4:      value count (01 = one value will follow)
5-6:    setting value (82 00 = 130 Hz - little endian!)

7:      setting id (01 = resolution)
8:      value count (01 = one value will follow)
9-10:   setting value (0E 00 = 14 bit - little endian!)

### Polar Measurement Data (PMD) BYTE ARRAY
In each packet the first ten bytes are the header:
1:      Measurement type
2-9:    Polar time stamp (nanoseconds elapsed from boot)
10:     Frame type (00 = 24 bit ecg sample)     

Then data points follow in sequence:
xx-xx-xx: one datapoint (little endian)
This runs until the packet ends.