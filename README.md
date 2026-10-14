# usmelt

usmelt is a python package to control hardware devices necessary to run a sheet jet sample delivery experiment, like the one described in [https://doi.org/10.1107/S2052252523007972](https://doi.org/10.1107/S2052252523007972)

It currently controls:
- TG5012A function generator from Aim-TTi to trigger the Cobolt 06-01 DPL in current modulation

## Installation

To install it simply run `pip install .` inside the source directory, like any python package.

Notes for a fresh PC:

- On **Linux**, the sound-effect dependency (SimpleAudio) is compiled from source and
  needs ALSA headers plus a C compiler. Install them first, e.g. on Debian/Ubuntu:
  `sudo apt install build-essential libasound2-dev`
- On **Windows** no extra system packages are needed (the wheel builds with MSVC or a
  prebuilt wheel is used).
- On **macOS**, playsound==1.2.2 is installed instead of SimpleAudio to avoid a known
  seg fault in SimpleAudio on that platform.

## Usage

Just run `python usmelt_gui.py` from inside the source directory.

### Duplicate COM ports under Windows

Windows sometimes assigns two different devices to the same COM port (e.g. [1](https://superuser.com/questions/1587613/windows-10-two-serial-usb-devices-were-given-an-identical-port-number), [2](https://answers.microsoft.com/en-us/windows/forum/all/com-port-changes-and-same-for-two-devices-after/84837db6-2ef3-4fa6-9568-47e8805bd290)). This makes communication with the devices impossible using the COM port.
The workaround is to manually change the COM port assigned.
1. Open Device manager and right click on start button
and then on Device manager.
2. Expand port "COMS & LPT".
3. Right click on problematic device and then on properties.
4. Go to port settings and click on Advanced.
5. You will be able to make the changes on this screen.

