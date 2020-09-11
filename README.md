# rMview: a fast live viewer for reMarkable

![screenshot](https://raw.githubusercontent.com/bordaigorl/rmview/master/screenshot.png)

## Choose your flavour

There are two versions of rMview, presenting the same interface but using different back-ends (thus requiring different setups on the reMarkable):

* The "reStreamer-like" version, in the `master` branch
* The "VNC-based" version, in the `vnc` branch

In my tests, the VNC version is a clear winner, but it has different requirements, so I am keeping both alive for the moment.

**Volunteers wanted**: if you have experience with build systems/packaging for python, and/or experience in producing bundles with pyQt, and feel like contributing to the project, drop me a line!

## Instructions

To run the program you need python with pyqt5 installed.
Before running the program the first time, generate the resource file with

    pyrcc5 -o src/resources.py resources.qrc 

Then you can invoke the program with

    python src/rmview.py [config]

the optional `config` parameter is the filename of a json configuration file.
If the parameter is not found, the program will look for a `rmview.json` file in the current directory, or, if not found, for the path stored in the environment variable `RMVIEW_CONF`.
If none are found, or if the configuration is underspecified, the tool is going to prompt for address/password.

The supported configuration settings are below.
Look in file `example.json` for an example configuration.
All the settings are optional.

| Setting key              | Values                                                  | Default       |
| ------------------------ | ------------------------------------------------------- | ------------- |
| `ssh`                    | Connection parameters (see below)                       | `{}`          |
| `orientation`            | `"landscape"`, `"portrait"`, `"auto"`                   | `"landscape"` |
| `pen_size`               | diameter of pointer in px                               | `15`          |
| `pen_color`              | color of pointer or trail                               | `"red"`       |
| `pen_trail`              | persistence of trail in ms                              | `200`         |
| `background_color`       | color of window                                         | `"white"`     |
| `fetch_frame_delay`      | delay in sec after each frame fetch to throttle refresh | `0`           |
| `lz4_path_on_remarkable` | absolute path on the reMarkable                         | `"$HOME/lz4"` |
| `hide_pen_on_press`      | bool                                                    | `true`        |


Connection parameters are provided as a dictionary with the following keys (all optional):

| Parameter   | Values                                 | Comments                        |
| ----------- | -------------------------------------- | ------------------------------- |
| `address`   | IP of remarkable                       | tool prompts for it if missing  |
| `username`  | username for ssh access on reMarkable  | default: `"root"`               |
| `key`       | Local path to key for ssh              | not needed if password provided |
| `password`  | Password provide by reMarkable         | not needed if key provided      |
| `timeout`   | connection timeout in seconds          | default: 1                      |


Tested with Python 3.8.2, PyQt 5.14.2, MacOs 10.15.4, reMarkable firmware 2.1.1.3

## Requirements

### On your computer:

- Python 3
- PyQt5
- Paramiko
- lz4framed for `master` branch
- Twisted for `vnc` branch

They can be installed via `pip install pyqt5 paramiko py-lz4framed`.
If you use Anaconda, please install the dependencies via `conda` (and not `pip`).

### On the reMarkable:

*"reStreamer-like" version:*

- LZ4, installed by running `scp lz4.arm.static <REMARKABLE>:lz4`.
  Make sure `lz4` is executable by running `ssh <REMARKABLE> chmod +x lz4`.

*"VNC-based" version:*

- Install [rM-vnc-server][vnc] and its dependency [mxc_epdc_fb_damage](https://github.com/peter-sa/mxc_epdc_fb_damage). Instructions can be found in the [wiki](https://github.com/bordaigorl/rmview/wiki/How-to-run-the-VNC-based-version).

## To Do

 - [ ] Settings dialog
 - [ ] About dialog
 - [ ] Pause stream of screen/pen
 - [ ] Build system
 - [ ] Bundle
 - [ ] Add interaction for Lamy button? (1 331 1 down, 1 331 0 up)
 - [ ] Remove dependency to Twisted in `vnc` branch


## Credits

I took inspiration from the following projects:

- [QtImageViewer](https://github.com/marcel-goldschen-ohm/PyQtImageViewer/)
- [remarkable_mouse](https://github.com/Evidlo/remarkable_mouse/)
- [reStream](https://github.com/rien/reStream)
- [rM-vnc-server](https://github.com/peter-sa/rM-vnc-server)
- [VNC client](https://github.com/sibson/vncdotool) originally written by Chris Liechti

Icons adapted from designs by Freepik, xnimrodx from www.flaticon.com


## Disclaimer

This project is not affiliated to, nor endorsed by, [reMarkable AS](https://remarkable.com/).
**I assume no responsibility for any damage done to your device due to the use of this software.**

## Licence

GPLv3

[vnc]: https://github.com/peter-sa/rM-vnc-server
